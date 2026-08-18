"""Restore-drill engine (plan 23 Phases 2–3).

A *drill* is a real restore of a policy's latest restorable point into a scratch
location (a temp dir for files/application, a throwaway ``skdrill_<run_id>``
database for database targets), probe-verified, then torn down. It never touches
the live target. A successful drill is the strongest proof a backup is
restorable: it promotes the drilled :class:`BackupRun` to
``verify_level='drilled'`` and stamps the policy's ``last_drill_*`` cache.

Key behaviours (match the proving tests):
  * **expectation-stamped probes** — files record ``file_count`` + a hash sample
    (``sampled`` / ``sampled_ok``); databases record ``table_count``.
  * **container-aware / real DB legs** — the database leg runs the real
    ``create → restore → probe → drop`` sequence against the shared engine using
    the existing ``DatabaseService`` helpers; the scratch DB is dropped in a
    ``finally`` even when the restore fails.
  * **vacuous-drill detection** — a drill that restored zero files fails loudly
    instead of earning ``drilled`` for nothing.
  * **hard guards, loud skips** — a free-space precheck marks the drill
    ``skipped_no_space`` (doctor-visible) rather than silently passing.
  * **single-flight** — one drill in flight per host; a new request is refused
    (:class:`BackupDrillError`) while one is running.
  * **cadence sweep** — a daily sweep enqueues due drills serially.

See docs/plans/23_BACKUP_TRUST_RESTORE_DRILLS_PLAN.md.
"""
import logging
import math
import os
import shutil
from datetime import datetime, timedelta

from app import db

logger = logging.getLogger(__name__)

DRILL_JOB_KIND = 'backup.drill.run'
DRILL_SWEEP_JOB_KIND = 'backup.drill.sweep'
DRILL_ORPHAN_SWEEP_JOB_KIND = 'backup.drill.orphan_sweep'
DRILL_SWEEP_SCHEDULE_NAME = 'backup-drill-sweep'
DRILL_ORPHAN_SCHEDULE_NAME = 'backup-drill-orphan-sweep'

# Cadence → base interval in days.
CADENCE_DAYS = {'weekly': 7, 'monthly': 30}
# A 'running' drill older than this is treated as crashed, not in-flight.
STALE_DRILL_AFTER = timedelta(hours=6)
# Free-space safety multipliers (Decision 6).
EXTRACTED_ESTIMATE_MULT = 1.2   # from manifest totals
ARCHIVE_ESTIMATE_MULT = 3.0     # fallback: raw archive size × 3
# Scratch dirs / scratch DBs older than this are orphan-swept.
ORPHAN_AFTER = timedelta(hours=24)
# Hash sample bounds.
SAMPLE_MAX = 50
SAMPLE_FRACTION = 0.05


class BackupDrillError(Exception):
    """Raised when a drill is refused or fails loudly (e.g. vacuous restore)."""


class BackupDrillService:

    # ------------------------------------------------------------------ #
    # Space accounting (guards)
    # ------------------------------------------------------------------ #

    @classmethod
    def _estimate_required(cls, run, meta):
        """Estimated bytes needed to materialize the drill: manifest extracted
        size ×1.2 where known, else raw primary-archive size ×3."""
        from app.services.backup_verify_service import read_manifest
        manifest = read_manifest(run, meta)
        if manifest:
            total = ((manifest.get('totals') or {}).get('bytes')) or 0
            if total:
                return int(total * EXTRACTED_ESTIMATE_MULT)
        primary = meta.get('primary_archive') or run.storage_path
        size = 0
        try:
            if primary and os.path.isfile(primary):
                size = os.path.getsize(primary)
            elif primary and os.path.isdir(primary):
                size = sum(
                    os.path.getsize(os.path.join(r, f))
                    for r, _d, fs in os.walk(primary) for f in fs
                    if os.path.isfile(os.path.join(r, f))
                )
        except OSError:
            size = 0
        return int(size * ARCHIVE_ESTIMATE_MULT)

    @staticmethod
    def _free_bytes(path):
        """Free bytes on the filesystem holding ``path`` (walks up to the nearest
        existing ancestor so a not-yet-created scratch dir still measures)."""
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe.rstrip(os.sep))
            if parent == probe:
                break
            probe = parent
        try:
            return shutil.disk_usage(probe or os.getcwd()).free
        except OSError:
            return 0

    @classmethod
    def _scratch_base(cls):
        from app.services.backup_service import BackupService
        base = os.path.join(BackupService.BACKUP_BASE_DIR, 'restores')
        os.makedirs(base, exist_ok=True)
        return base

    # ------------------------------------------------------------------ #
    # Single-flight guard + run selection
    # ------------------------------------------------------------------ #

    @classmethod
    def is_drilling(cls):
        """True if a (non-stale) restore drill is currently running on this host."""
        from app.models.restore_drill import RestoreDrill
        cutoff = datetime.utcnow() - STALE_DRILL_AFTER
        return db.session.query(RestoreDrill.id).filter(
            RestoreDrill.status == 'running',
            RestoreDrill.started_at >= cutoff,
        ).first() is not None

    @classmethod
    def _latest_restorable_run(cls, policy):
        """Newest successful run (the chain endpoint) for a policy."""
        from app.models.backup_run import BackupRun
        return (BackupRun.query
                .filter_by(policy_id=policy.id, status='success')
                .order_by(BackupRun.started_at.desc())
                .first())

    # ------------------------------------------------------------------ #
    # Enqueue (single-flight refusal lives here)
    # ------------------------------------------------------------------ #

    @classmethod
    def request_drill(cls, policy, trigger='manual', run_id=None):
        """Enqueue a ``backup.drill.run`` job for a policy's latest restorable
        point. Refused (:class:`BackupDrillError`) while a drill is in flight."""
        if cls.is_drilling():
            raise BackupDrillError('A restore drill is already in progress.')
        if run_id is None:
            run = cls._latest_restorable_run(policy)
            if not run:
                raise BackupDrillError('No successful backup to drill.')
            run_id = run.id
        from app.jobs.service import JobService
        job = JobService.enqueue(
            DRILL_JOB_KIND,
            payload={'policy_id': policy.id, 'run_id': run_id, 'trigger': trigger},
            max_attempts=1,
            owner_type='backup_policy',
            owner_id=policy.id,
        )
        return job

    # ------------------------------------------------------------------ #
    # Cadence (Phase 3)
    # ------------------------------------------------------------------ #

    @classmethod
    def _jitter(cls, policy, cadence):
        """Deterministic per-policy jitter (0–20% of the interval) so scheduled
        drills spread out instead of all firing on the same day."""
        import random
        interval = timedelta(days=CADENCE_DAYS[cadence])
        frac = random.Random(policy.id or 0).uniform(0.0, 0.2)
        return interval * frac

    @classmethod
    def is_due(cls, policy, now=None):
        """True if ``policy`` should be drilled now (enabled, cadence on, a
        restorable run exists, and it hasn't been drilled within the cadence
        interval + jitter)."""
        now = now or datetime.utcnow()
        if not policy.enabled:
            return False
        cadence = policy.drill_cadence or 'off'
        if cadence not in CADENCE_DAYS:
            return False
        if not cls._latest_restorable_run(policy):
            return False
        if not policy.last_drill_at:
            return True
        threshold = timedelta(days=CADENCE_DAYS[cadence]) + cls._jitter(policy, cadence)
        return (now - policy.last_drill_at) >= threshold

    @classmethod
    def due_policies(cls, now=None):
        """All enabled policies whose drill cadence is due."""
        from app.models.backup_policy import BackupPolicy
        now = now or datetime.utcnow()
        return [p for p in BackupPolicy.query.filter_by(enabled=True).all()
                if cls.is_due(p, now)]

    @classmethod
    def run_drill_sweep(cls, job=None):
        """Daily sweep: enqueue due drills serially. Defers entirely while a
        drill is already in flight (natural rate limiting / single-flight)."""
        if cls.is_drilling():
            return {'count': 0, 'enqueued': [], 'deferred': True}
        enqueued = []
        for policy in cls.due_policies():
            try:
                cls.request_drill(policy, trigger='scheduled')
                enqueued.append(policy.id)
            except BackupDrillError:
                # One is now in flight — the rest wait for the next sweep.
                break
        return {'count': len(enqueued), 'enqueued': enqueued}

    # ------------------------------------------------------------------ #
    # The drill itself (Phase 2)
    # ------------------------------------------------------------------ #

    @classmethod
    def run_restore_drill(cls, job):
        """Job handler for ``backup.drill.run``. Restores the run's chain into a
        scratch target, probes it, and records the outcome. Returns a result
        dict; raises on a real drill failure so the job is marked failed."""
        from app.models.backup_policy import BackupPolicy
        from app.models.backup_run import BackupRun
        from app.models.restore_drill import RestoreDrill

        payload = job.get_payload() or {}
        policy_id = payload.get('policy_id')
        run_id = payload.get('run_id')
        policy = BackupPolicy.query.get(policy_id)
        if not policy:
            raise BackupDrillError(f'backup policy {policy_id!r} not found')
        run = BackupRun.query.filter_by(id=run_id, policy_id=policy.id).first()
        if not run:
            raise BackupDrillError(f'backup run {run_id!r} not found')

        meta = run.get_metadata() or {}
        started = datetime.utcnow()
        drill = RestoreDrill(policy_id=policy.id, run_id=run.id,
                             job_id=getattr(job, 'id', None), status='running',
                             trigger=payload.get('trigger'), started_at=started)
        db.session.add(drill)
        db.session.commit()
        drill_id = drill.id

        # --- Free-space precheck (loud skip, never a silent pass) ---------- #
        scratch_base = cls._scratch_base()
        required = cls._estimate_required(run, meta)
        free = cls._free_bytes(scratch_base)
        drill.bytes_required = int(required)
        drill.bytes_free = int(free)
        db.session.commit()
        if free < required:
            drill.status = 'skipped_no_space'
            drill.finished_at = datetime.utcnow()
            drill.duration_seconds = int((drill.finished_at - started).total_seconds())
            drill.set_probes({'skipped': 'no_space',
                              'bytes_required': int(required), 'bytes_free': int(free)})
            cls._stamp_policy(policy.id, 'skipped_no_space')
            db.session.commit()
            logger.warning('drill %s skipped: need %s bytes, %s free',
                           drill_id, required, free)
            # A log line is not a notification. Without this the operator learns
            # nothing, and the policy still reads as recently drilled.
            cls._notify_failed(
                policy.id, run_id,
                f'needs {required} bytes of scratch space, {free} free',
                status='skipped_no_space')
            return {'status': 'skipped_no_space', 'drill_id': drill_id,
                    'bytes_required': int(required), 'bytes_free': int(free)}

        # --- Run the leg -------------------------------------------------- #
        try:
            probes, scratch_ref, bytes_restored = cls._dispatch_drill(
                policy, run, meta, drill_id)
            drill = RestoreDrill.query.get(drill_id)
            drill.status = 'success'
            drill.scratch_ref = scratch_ref
            drill.bytes_restored = int(bytes_restored or 0)
            drill.set_probes(probes)
            drill.finished_at = datetime.utcnow()
            drill.duration_seconds = int((drill.finished_at - started).total_seconds())

            # Promote the drilled run + stamp the policy cache.
            run = BackupRun.query.get(run_id)
            run.verify_level = 'drilled'
            run.verified_at = datetime.utcnow()
            run.verify_error = None
            cls._stamp_policy(policy.id, 'success')
            db.session.commit()

            # On success the scratch dir is torn down (DB scratch already dropped).
            cls._teardown_scratch(scratch_ref)
            cls._notify_recovered(policy.id, run_id)
            return {'status': 'success', 'drill_id': drill_id, 'probes': probes}

        except Exception as exc:  # noqa: BLE001 — record + re-raise
            db.session.rollback()
            drill = RestoreDrill.query.get(drill_id)
            if drill:
                drill.status = 'failed'
                drill.error = str(exc)[:2000]
                drill.finished_at = datetime.utcnow()
                drill.duration_seconds = int((drill.finished_at - started).total_seconds())
                probes = drill.get_probes()
                probes['error'] = str(exc)[:500]
                drill.set_probes(probes)
                cls._stamp_policy(policy.id, 'failed')
                db.session.commit()
            cls._notify_failed(policy.id, run_id, str(exc))
            # Scratch dirs are preserved for 24h on failure (orphan sweep reaps).
            raise

    # ------------------------------------------------------------------ #
    # Leg dispatch
    # ------------------------------------------------------------------ #

    @classmethod
    def _dispatch_drill(cls, policy, run, meta, drill_id):
        """Return ``(probes, scratch_ref, bytes_restored)`` for the target type.
        Raises on a failed/vacuous drill."""
        target_type = policy.target_type
        if target_type == 'database':
            return cls._drill_database(policy, run, meta)
        if target_type == 'wordpress_site':
            # The WP drill leg replays the backup ARTIFACT layout (files.tar.gz
            # + database.sql) with core services only — it never touches the
            # WordPress extension, so it stays core and works even with the
            # extension absent (drilling an old backup of a removed site).
            return cls._drill_wordpress(policy, run, meta, drill_id)
        if target_type not in ('files', 'application'):
            # Unknown type: drillable only while a provider kind is registered
            # (registered kinds replay their tar via the files leg below).
            from app.services import backup_kind_registry
            if not backup_kind_registry.get(target_type):
                raise BackupDrillError(
                    f"Cannot drill target type {target_type!r}: the extension "
                    f"that supplies it is not installed or not active")
        # files + application both replay a tar chain into a scratch dir.
        return cls._drill_files(policy, run, meta, drill_id)

    # ------------------------------------------------------------------ #
    # Files / application leg
    # ------------------------------------------------------------------ #

    @classmethod
    def _chain_archives(cls, policy, run, meta):
        """Ordered local archive paths needed to restore ``run``. Reuses the
        policy service's chain resolver where possible."""
        try:
            from app.services.backup_policy_service import BackupPolicyService
            return BackupPolicyService._chain_archives(policy, run)
        except Exception:  # noqa: BLE001 — fall back to the single primary
            primary = meta.get('primary_archive')
            if not primary or not os.path.exists(primary):
                raise BackupDrillError('Backup archive not found for drill')
            return [primary]

    @classmethod
    def _drill_files(cls, policy, run, meta, drill_id):
        import tarfile
        scratch = os.path.join(cls._scratch_base(), f'drill-{drill_id}')
        os.makedirs(scratch, exist_ok=True)

        archives = cls._chain_archives(policy, run, meta)
        for archive in archives:
            if not archive or not os.path.exists(archive):
                raise BackupDrillError(f'Backup archive missing for drill: {archive}')
            with tarfile.open(archive, 'r:*') as tar:
                tar.extractall(scratch, filter='data')

        files = []
        total_bytes = 0
        for root, _dirs, names in os.walk(scratch):
            for name in names:
                fp = os.path.join(root, name)
                if os.path.isfile(fp):
                    files.append(fp)
                    try:
                        total_bytes += os.path.getsize(fp)
                    except OSError:
                        pass

        file_count = len(files)
        # Vacuous-drill detection: a drill that restored nothing is not proof.
        if file_count == 0:
            raise BackupDrillError(
                'Drill restored 0 files — the archive is empty or unreadable.')

        sampled, sampled_ok, mismatches = cls._hash_sample(files)
        probes = {
            'engine': meta.get('engine') or policy.target_type,
            'file_count': file_count,
            'bytes_restored': total_bytes,
            'sampled': sampled,
            'sampled_ok': sampled_ok,
            'archives': len(archives),
        }
        if mismatches:
            probes['sample_mismatches'] = mismatches
        return probes, scratch, total_bytes

    @classmethod
    def _hash_sample(cls, files):
        """Full-hash a sample (min(50, 5%)) of the restored files. ``sampled_ok``
        counts files whose bytes hashed cleanly (proves they're actually
        readable, not just present)."""
        from app.services.backup_verify_service import sha256_file
        count = len(files)
        if count == 0:
            return 0, 0, 0
        sample_size = min(count, max(1, min(SAMPLE_MAX, math.ceil(count * SAMPLE_FRACTION))))
        # Deterministic, evenly spaced sample across the sorted file list.
        ordered = sorted(files)
        step = max(1, count // sample_size)
        picked = ordered[::step][:sample_size]
        sampled = len(picked)
        sampled_ok = 0
        for fp in picked:
            if sha256_file(fp) is not None:
                sampled_ok += 1
        return sampled, sampled_ok, sampled - sampled_ok

    # ------------------------------------------------------------------ #
    # Database leg
    # ------------------------------------------------------------------ #

    @classmethod
    def _drill_database(cls, policy, run, meta):
        """Restore the dump into a throwaway ``skdrill_<run_id>`` database on the
        shared engine, probe the table count, then DROP it in a ``finally``
        (even when the restore fails). Never touches the live database."""
        from app.services.backup_service import BackupService
        from app.services.database_service import DatabaseService

        db_type = (meta.get('db_type') or policy.target_subtype or 'mysql').lower()
        backup_path = meta.get('primary_archive') or run.storage_path
        if not backup_path or not os.path.exists(backup_path):
            raise BackupDrillError('Backup archive not found for database drill')

        scratch_name = f'skdrill_{run.id}'
        creds = cls._db_credentials(policy, meta)
        is_postgres = db_type in ('postgres', 'postgresql')

        created = False
        try:
            # 1. create scratch DB
            if is_postgres:
                res = DatabaseService.pg_create_database(scratch_name)
            else:
                res = DatabaseService.mysql_create_database(scratch_name)
            if isinstance(res, dict) and not res.get('success', True):
                raise BackupDrillError(res.get('error') or 'scratch DB create failed')
            created = True

            # 2. restore the dump into the scratch DB
            restore = BackupService.restore_database(
                backup_path=backup_path,
                db_type='postgresql' if is_postgres else 'mysql',
                db_name=scratch_name,
                user=creds.get('user'),
                password=creds.get('password'),
                host=creds.get('host', 'localhost'),
            )
            if isinstance(restore, dict) and not restore.get('success', True):
                raise BackupDrillError(restore.get('error') or 'database restore failed')

            # 3. probe: table count in the restored scratch DB
            if is_postgres:
                tables = DatabaseService.pg_get_tables(scratch_name)
            else:
                tables = DatabaseService.mysql_get_tables(scratch_name)
            table_count = len(tables or [])
            probes = {
                'engine': 'database',
                'db_type': 'postgresql' if is_postgres else 'mysql',
                'scratch_db': scratch_name,
                'table_count': table_count,
                'tables': [cls._table_name(t) for t in (tables or [])][:100],
            }
            return probes, scratch_name, 0
        finally:
            # 4. always drop the scratch DB
            if created:
                try:
                    if is_postgres:
                        DatabaseService.pg_drop_database(scratch_name)
                    else:
                        DatabaseService.mysql_drop_database(scratch_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning('drill: failed to drop scratch DB %s: %s',
                                   scratch_name, exc)

    @staticmethod
    def _table_name(table):
        if isinstance(table, dict):
            return table.get('name') or table.get('table') or str(table)
        return str(table)

    @classmethod
    def _db_credentials(cls, policy, meta):
        """Resolve the engine credentials for the drill (reuses the policy
        service's target resolver; falls back to policy meta)."""
        try:
            from app.services.backup_policy_service import BackupPolicyService
            target = BackupPolicyService._resolve_target(policy)
            cfg = target.get('db_config') or {}
            if cfg:
                return cfg
        except Exception:  # noqa: BLE001
            pass
        tmeta = policy.get_target_meta() if hasattr(policy, 'get_target_meta') else {}
        return {
            'user': meta.get('user') or tmeta.get('user'),
            'password': meta.get('password') or tmeta.get('password'),
            'host': meta.get('host') or tmeta.get('host', 'localhost'),
        }

    # ------------------------------------------------------------------ #
    # WordPress leg (files drill + real scratch-DB import, plan 30)
    # ------------------------------------------------------------------ #

    @classmethod
    def _drill_wordpress(cls, policy, run, meta, drill_id):
        """A WordPress drill proves BOTH halves: extract the files archive into a
        scratch dir, AND import ``database.sql`` into a throwaway scratch DB. A
        drill that verified neither artifact fails instead of earning 'drilled'
        vacuously (plan 30)."""
        import tarfile
        from app.services.backup_service import BackupService
        from app.services.database_service import DatabaseService

        backup_dir = run.storage_path
        scratch = os.path.join(cls._scratch_base(), f'drill-{drill_id}')
        os.makedirs(scratch, exist_ok=True)

        probes = {'engine': 'wordpress_site'}
        total_bytes = 0
        proved_any = False

        # --- files half --------------------------------------------------- #
        files_archive = meta.get('primary_archive') or (
            os.path.join(backup_dir, 'files.tar.gz') if backup_dir else None)
        file_count = 0
        if files_archive and os.path.exists(files_archive):
            with tarfile.open(files_archive, 'r:*') as tar:
                tar.extractall(scratch, filter='data')
            restored = []
            for root, _dirs, names in os.walk(scratch):
                for name in names:
                    fp = os.path.join(root, name)
                    if os.path.isfile(fp):
                        restored.append(fp)
                        try:
                            total_bytes += os.path.getsize(fp)
                        except OSError:
                            pass
            file_count = len(restored)
            if file_count:
                sampled, sampled_ok, _mm = cls._hash_sample(restored)
                probes.update({'file_count': file_count, 'sampled': sampled,
                               'sampled_ok': sampled_ok})
                proved_any = True

        # --- database half ------------------------------------------------ #
        db_sql = os.path.join(backup_dir, 'database.sql') if backup_dir else None
        if db_sql and os.path.exists(db_sql):
            scratch_name = f'skdrill_{run.id}'
            creds = cls._db_credentials(policy, meta)
            created = False
            try:
                res = DatabaseService.mysql_create_database(scratch_name)
                if isinstance(res, dict) and not res.get('success', True):
                    raise BackupDrillError(res.get('error') or 'scratch DB create failed')
                created = True
                restore = BackupService.restore_database(
                    backup_path=db_sql, db_type='mysql', db_name=scratch_name,
                    user=creds.get('user'), password=creds.get('password'),
                    host=creds.get('host', 'localhost'))
                if isinstance(restore, dict) and not restore.get('success', True):
                    raise BackupDrillError(restore.get('error') or 'WP database restore failed')
                tables = DatabaseService.mysql_get_tables(scratch_name)
                probes['table_count'] = len(tables or [])
                proved_any = True
            finally:
                if created:
                    try:
                        DatabaseService.mysql_drop_database(scratch_name)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning('WP drill: failed to drop scratch DB %s: %s',
                                       scratch_name, exc)

        if not proved_any:
            raise BackupDrillError(
                'WordPress drill verified no artifact (no files and no database).')
        probes['bytes_restored'] = total_bytes
        return probes, scratch, total_bytes

    # ------------------------------------------------------------------ #
    # Teardown / stamps / notifications
    # ------------------------------------------------------------------ #

    @staticmethod
    def _teardown_scratch(scratch_ref):
        if scratch_ref and os.path.isdir(scratch_ref):
            shutil.rmtree(scratch_ref, ignore_errors=True)

    @classmethod
    def _stamp_policy(cls, policy_id, status):
        from app.models.backup_policy import BackupPolicy
        policy = BackupPolicy.query.get(policy_id)
        if not policy:
            return
        policy.last_drill_at = datetime.utcnow()
        policy.last_drill_status = status

    @classmethod
    def _notify_failed(cls, policy_id, run_id, error, status='failed'):
        """Alert on a drill that did not prove the backup.

        ``status`` is passed through because ``BackupAlertService`` already
        treats ``skipped_no_space`` as a failed outcome — that branch was simply
        never reached, since only the exception path called this. A drill that
        could not run left no trace beyond a log line.
        """
        try:
            from app.models.backup_policy import BackupPolicy
            from app.services.backup_alert_service import BackupAlertService
            policy = BackupPolicy.query.get(policy_id)
            if policy:
                BackupAlertService.on_drill_result(policy, status=status, error=error)
        except Exception as exc:  # noqa: BLE001 — alerts are best-effort
            logger.debug('drill-%s alert skipped: %s', status, exc)

    @classmethod
    def _notify_recovered(cls, policy_id, run_id):
        try:
            from app.models.backup_policy import BackupPolicy
            from app.services.backup_alert_service import BackupAlertService
            policy = BackupPolicy.query.get(policy_id)
            if policy:
                BackupAlertService.on_drill_result(policy, status='success')
        except Exception as exc:  # noqa: BLE001
            logger.debug('drill-recovered alert skipped: %s', exc)

    # ------------------------------------------------------------------ #
    # Orphan sweep (daily)
    # ------------------------------------------------------------------ #

    @classmethod
    def orphan_sweep(cls, job=None):
        """Reap scratch dirs (``restores/drill-*``) with no live drill row and
        older than 24h. Scratch DBs are dropped inline by each drill's finally,
        so only dirs need sweeping here."""
        from app.models.restore_drill import RestoreDrill
        base = cls._scratch_base()
        removed = 0
        live_ids = {d.id for d in RestoreDrill.query.filter_by(status='running').all()}
        cutoff = datetime.utcnow() - ORPHAN_AFTER
        try:
            entries = os.listdir(base)
        except OSError:
            entries = []
        for entry in entries:
            if not entry.startswith('drill-'):
                continue
            path = os.path.join(base, entry)
            if not os.path.isdir(path):
                continue
            try:
                drill_id = int(entry.split('-', 1)[1])
            except (ValueError, IndexError):
                drill_id = None
            if drill_id in live_ids:
                continue
            try:
                mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
            except OSError:
                mtime = cutoff
            if mtime <= cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        return {'removed': removed}

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    @classmethod
    def register_jobs(cls):
        """Register the drill handlers with the job registry (app startup)."""
        from app.jobs import registry
        registry.register(DRILL_JOB_KIND, cls.run_restore_drill, replace=True)
        registry.register(DRILL_SWEEP_JOB_KIND, cls.run_drill_sweep, replace=True)
        registry.register(DRILL_ORPHAN_SWEEP_JOB_KIND, cls.orphan_sweep, replace=True)
