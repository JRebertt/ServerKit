"""Disk reclamation — find and free space when the panel host fills up.

Built for the failure mode where routine ``serverkit update`` runs fill the
disk on their own:

* ``queue_messages``, ``system_events`` and ``api_usage_logs`` have no
  retention handler, so the database grows without bound (~11 MB/day on a
  single-app box).
* Every update copies that database **twice** — a ``serverkit-pre-upgrade-*.db``
  and a full ``serverkit-tree-*/`` backup that contains it — and nothing caps
  how many of those snapshots accumulate.

Six updates against an 800 MB database is ~9.6 GB, which is enough to fill a
25 GB VPS from a standing start.

Two ordering rules are baked in because they are the difference between this
working and not working on a disk that is already at 100%:

1. Filesystem candidates always run **before** the database VACUUM. VACUUM
   rewrites the database into a temporary file alongside it, so it needs free
   space roughly equal to the database itself — it is the one step that cannot
   go first on a full disk.
2. Rows are deleted from ``jobs`` before ``queue_messages``, and any queue
   message still referenced by a surviving job is kept, so the
   ``jobs.queue_message_id`` link never dangles.

Everything is measured before anything is deleted, and every candidate can be
previewed with ``dry_run=True``.
"""
import os
import re
import shutil
from datetime import datetime, timedelta

from app.utils.system import run_checked

# ── Defaults (overridable per call so tests never touch real paths) ──────────

INSTALL_DIR = os.environ.get('SERVERKIT_DIR', '/opt/serverkit')
# Must match BACKUP_DIR in scripts/update.sh — that is what writes the
# snapshots this module reclaims.
BACKUP_DIR = os.environ.get('SERVERKIT_BACKUP_DIR', '/var/backups/serverkit')
TMP_DIR = os.environ.get('SERVERKIT_TMP_DIR', '/tmp')

DEFAULT_RETENTION_DAYS = 7
DEFAULT_KEEP_SNAPSHOTS = 1
DEFAULT_JOURNAL_CAP = '100M'

# mktemp -d names: "tmp." + exactly 10 alphanumerics. Anything else in /tmp is
# not ours to touch.
_MKTEMP_RE = re.compile(r'^tmp\.[A-Za-z0-9]{10}$')
_SNAPSHOT_RES = (
    re.compile(r'^serverkit-tree-(\d{8}-\d{6})$'),
    re.compile(r'^serverkit-pre-upgrade-(\d{8}-\d{6})\.db$'),
    # PostgreSQL installs snapshot with pg_dump instead of a file copy.
    re.compile(r'^serverkit-pre-upgrade-(\d{8}-\d{6})\.dump$'),
    re.compile(r'^serverkit-pre-prune-(\d{8}(?:-\d{6})?)\.db$'),
)

# Telemetry tables, in deletion order. ``keep_status`` rows are never removed
# regardless of age.
TELEMETRY_SPECS = (
    # (key,             table,              time_column,  status_column, deletable_statuses)
    ('jobs',            'jobs',             'created_at', 'status', ('succeeded', 'cancelled')),
    ('queue_messages',  'queue_messages',   'created_at', 'status', ('completed',)),
    ('system_events',   'system_events',    'created_at', None,     None),
    ('api_usage_logs',  'api_usage_logs',   'created_at', None,     None),
)


def human_bytes(n):
    """Format a byte count the way ``df -h`` does."""
    if n is None:
        return '-'
    n = float(n)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024.0 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024.0


def _run(cmd, timeout=300):
    """Run a command, returning (ok, stdout, stderr). Never raises.

    Routed through :func:`app.utils.system.run_checked` rather than calling
    subprocess directly, so a bare ``journalctl``/``docker`` name still
    resolves when the unit's $PATH omits sbin — that outage otherwise surfaces
    here as "nothing to reclaim", which is a false fact about the operator's
    disk rather than a visible error.

    A missing binary is a normal outcome for this sweep (a host with no docker
    or no systemd), so it degrades to a zero-sized candidate rather than
    aborting the scan; ``run_checked`` still puts the reason in stderr.
    """
    result = run_checked(cmd, timeout=timeout)
    return (result['success'], result['output'],
            result['stderr'] or (result['error'] or ''))


def _path_size(path):
    """Bytes used by a file or directory tree. Symlinks are counted, not followed."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_size
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in files + dirs:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def disk_usage(path='/'):
    """Free/total bytes for the filesystem holding ``path``."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {
        'path': path,
        'total': usage.total,
        'used': usage.used,
        'free': usage.free,
        'percent_used': round(usage.used * 100.0 / usage.total, 1) if usage.total else 0.0,
    }


# ── Filesystem candidates ───────────────────────────────────────────────────

def _parse_stamp(stamp):
    """YYYYmmdd-HHMMSS (or bare YYYYmmdd) to a datetime, or None."""
    for fmt in ('%Y%m%d-%H%M%S', '%Y%m%d'):
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def list_snapshots(backup_dir=BACKUP_DIR):
    """Every upgrade snapshot, newest first, grouped by timestamp.

    One update writes several files under the same stamp — a database copy
    (``.db`` or a PostgreSQL ``.dump``) and a full tree backup — so they are
    grouped and offered as a single unit. Deleting half a snapshot helps nobody.
    """
    try:
        entries = os.listdir(backup_dir)
    except OSError:
        return []

    groups = {}
    for name in entries:
        for pattern in _SNAPSHOT_RES:
            match = pattern.match(name)
            if match:
                groups.setdefault(match.group(1), []).append(os.path.join(backup_dir, name))
                break

    now = datetime.utcnow()
    snapshots = []
    for stamp, paths in groups.items():
        when = _parse_stamp(stamp)
        snapshots.append({
            'stamp': stamp,
            'paths': sorted(paths),
            'bytes': sum(_path_size(p) for p in paths),
            'taken_at': when.isoformat() if when else None,
            'age_days': (now - when).days if when else None,
        })
    # Stamps are zero-padded, so lexical order is chronological order.
    snapshots.sort(key=lambda s: s['stamp'], reverse=True)
    return snapshots


def select_snapshots(snapshots, keep=DEFAULT_KEEP_SNAPSHOTS, older_than_days=None):
    """Which snapshots to drop: everything past ``keep``, and — when
    ``older_than_days`` is given — only those at least that old.

    ``keep`` always wins, so an age filter can never empty the directory.
    """
    doomed = snapshots[keep:] if keep >= 0 else []
    if older_than_days is not None:
        doomed = [s for s in doomed
                  if s['age_days'] is not None and s['age_days'] >= older_than_days]
    return doomed


def _scan_upgrade_snapshots(backup_dir=BACKUP_DIR, keep=DEFAULT_KEEP_SNAPSHOTS,
                            older_than_days=None):
    """Pre-upgrade database copies and tree backups beyond the newest ``keep``."""
    doomed = select_snapshots(list_snapshots(backup_dir), keep, older_than_days)
    paths = sorted(path for snap in doomed for path in snap['paths'])
    return paths, sum(snap['bytes'] for snap in doomed)


def _looks_like_serverkit_staging(path):
    """True when a /tmp scratch dir holds an unpacked ServerKit release.

    Update staging dirs contain the extracted tree (``opt/serverkit`` and
    friends). Anything else under /tmp belongs to someone else.
    """
    try:
        top = os.listdir(path)
    except OSError:
        return False
    for name in top:
        if 'serverkit' in name.lower():
            return True
        if name in ('opt', 'usr', 'srv'):
            try:
                if any('serverkit' in child.lower()
                       for child in os.listdir(os.path.join(path, name))):
                    return True
            except OSError:
                continue
    return False


def _scan_tmp_staging(tmp_dir=TMP_DIR, min_age_hours=24):
    """Abandoned ``mktemp -d`` staging dirs left behind by past updates."""
    cutoff = datetime.utcnow() - timedelta(hours=min_age_hours)
    # Only ever reap scratch dirs belonging to whoever is running the reclaim
    # (root in production). Another user's /tmp is never ours to clear.
    euid = os.geteuid() if hasattr(os, 'geteuid') else None
    paths = []
    try:
        entries = os.listdir(tmp_dir)
    except OSError:
        return [], 0

    for name in entries:
        if not _MKTEMP_RE.match(name):
            continue
        path = os.path.join(tmp_dir, name)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if euid is not None and st.st_uid != euid:
            continue
        if datetime.utcfromtimestamp(st.st_mtime) > cutoff:
            continue
        if os.path.isdir(path) and not _looks_like_serverkit_staging(path):
            continue
        paths.append(path)
    paths.sort()
    return paths, sum(_path_size(p) for p in paths)


def _scan_oversized_logs(min_bytes=10 * 1024 * 1024):
    """Failed/successful-login binary logs that have grown past a sane size.

    ``btmp`` in particular balloons under sustained SSH brute-force. These are
    truncated rather than deleted so the files keep their ownership and mode.
    """
    paths = []
    for path in ('/var/log/btmp', '/var/log/btmp.1', '/var/log/wtmp', '/var/log/wtmp.1'):
        try:
            size = os.lstat(path).st_size
        except OSError:
            continue
        if size >= min_bytes:
            paths.append(path)
    return paths, sum(_path_size(p) for p in paths)


_SCALE = {'': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}


def _to_bytes(number, suffix):
    return int(float(number) * _SCALE.get(suffix.upper().rstrip('B'), 1))


def _parse_reclaimed(output):
    """Bytes from docker's 'Total reclaimed space: 1.234GB' trailer."""
    match = re.search(r'Total reclaimed space:\s*([\d.]+)\s*([KMGT]?B)', output or '')
    return _to_bytes(match.group(1), match.group(2)) if match else 0


def _journal_bytes():
    """Bytes currently held by the systemd journal, or 0 if journalctl is absent."""
    ok, out, _ = _run(['journalctl', '--disk-usage'], timeout=30)
    if not ok:
        return 0
    match = re.search(r'take up ([\d.]+)([KMGT]?)B?', out)
    return _to_bytes(match.group(1), match.group(2)) if match else 0


def _scan_journal(cap=DEFAULT_JOURNAL_CAP):
    """Systemd journal bytes above ``cap``."""
    current = _journal_bytes()
    cap_match = re.match(r'^([\d.]+)([KMGT]?)$', str(cap).upper().rstrip('B'))
    cap_bytes = _to_bytes(cap_match.group(1), cap_match.group(2)) if cap_match else 0
    return max(0, current - cap_bytes)


def _scan_package_caches():
    """Package-manager and language caches — all re-downloadable."""
    paths = []
    for path in ('/var/cache/apt/archives', '/var/cache/dnf', '/var/cache/yum',
                 '/root/.cache/pip', '/root/.npm/_cacache'):
        if os.path.isdir(path) and _path_size(path) > 0:
            paths.append(path)
    return paths, sum(_path_size(p) for p in paths)


def _scan_docker():
    """Dangling images and build cache. Tagged images and volumes are never touched."""
    ok, out, _ = _run(['docker', 'system', 'df', '--format', '{{.Type}}|{{.Reclaimable}}'],
                      timeout=60)
    if not ok:
        return 0
    total = 0
    for line in out.splitlines():
        if '|' not in line:
            continue
        kind, reclaimable = line.split('|', 1)
        if kind.strip() != 'Build Cache':
            # Docker's image/volume "reclaimable" counts tagged-but-unused
            # images and named volumes, which we deliberately never remove —
            # so only the build cache can be estimated up front. Dangling
            # images are pruned too, and reported from docker's own tally.
            continue
        match = re.match(r'\s*([\d.]+)\s*([KMGT]?B)', reclaimable)
        if match:
            total += _to_bytes(match.group(1), match.group(2))
    return total


# ── Database candidate ──────────────────────────────────────────────────────

def _sqlite_path():
    """Filesystem path of the SQLite database, or None for other engines."""
    from flask import current_app
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite:'):
        return None
    path = uri.split('///')[-1].split('?')[0]
    return path or None


def _table_shares(db_path):
    """Bytes held by each table *including its indexes*, via the dbstat vtable.

    Returns {} when dbstat is unavailable — it is a compile-time option, so its
    absence is a missing estimate, not an error.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    except Exception:
        return {}
    try:
        # Each dbstat row names one btree — a table, or one of its indexes.
        # Map every index back to its table before summing, otherwise the
        # indexes (which here outweigh the tables) go uncounted.
        owner = {
            name: tbl_name for name, tbl_name in conn.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type IN ('table', 'index')")
        }
        shares = {}
        for name, size in conn.execute('SELECT name, SUM(pgsize) FROM dbstat GROUP BY name'):
            table = owner.get(name, name)
            shares[table] = shares.get(table, 0) + (size or 0)
        return shares
    except Exception:
        return {}
    finally:
        conn.close()


def scan_telemetry(days=DEFAULT_RETENTION_DAYS):
    """Count prunable telemetry rows and estimate the bytes they hold.

    Must run inside a Flask app context.
    """
    from sqlalchemy import text
    from app import db

    cutoff = datetime.utcnow() - timedelta(days=days)
    db_path = _sqlite_path()
    shares = _table_shares(db_path) if db_path and os.path.exists(db_path) else {}

    tables = []
    estimated = 0
    for key, table, time_col, status_col, statuses in TELEMETRY_SPECS:
        where = [f'{time_col} < :cutoff']
        params = {'cutoff': cutoff}
        if status_col and statuses:
            placeholders = ', '.join(f':s{i}' for i in range(len(statuses)))
            where.append(f'{status_col} IN ({placeholders})')
            params.update({f's{i}': value for i, value in enumerate(statuses)})
        clause = ' AND '.join(where)
        try:
            deletable = db.session.execute(
                text(f'SELECT COUNT(*) FROM {table} WHERE {clause}'), params).scalar() or 0
            total = db.session.execute(
                text(f'SELECT COUNT(*) FROM {table}')).scalar() or 0
        except Exception:
            continue

        own = shares.get(table, 0)
        share = int(own * deletable / total) if (own and total) else 0
        estimated += share
        tables.append({
            'key': key, 'table': table, 'rows': total,
            'deletable': deletable, 'bytes': share or None,
        })

    return {
        'days': days,
        'cutoff': cutoff.isoformat(),
        'tables': tables,
        'deletable_rows': sum(t['deletable'] for t in tables),
        'bytes': estimated or None,
        'db_path': db_path,
        'db_bytes': os.path.getsize(db_path) if db_path and os.path.exists(db_path) else None,
    }


def prune_telemetry(days=DEFAULT_RETENTION_DAYS, batch_size=5000, vacuum=True,
                    allow_restart=False, dry_run=False):
    """Delete aged telemetry rows, then VACUUM to hand the pages back to the OS.

    Deleting alone does not shrink the file — the pages land on SQLite's
    freelist and get reused. VACUUM is what actually returns the space, and it
    needs free disk roughly equal to the current database size, so run the
    filesystem reclaimers first.
    """
    from sqlalchemy import text
    from app import db

    report = scan_telemetry(days=days)
    if dry_run:
        report['dry_run'] = True
        return report

    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = {}
    for key, table, time_col, status_col, statuses in TELEMETRY_SPECS:
        where = [f'{time_col} < :cutoff']
        params = {'cutoff': cutoff}
        if status_col and statuses:
            placeholders = ', '.join(f':s{i}' for i in range(len(statuses)))
            where.append(f'{status_col} IN ({placeholders})')
            params.update({f's{i}': value for i, value in enumerate(statuses)})
        if table == 'queue_messages':
            # Keep anything a surviving job still points at, or
            # jobs.queue_message_id starts dangling.
            where.append('id NOT IN (SELECT queue_message_id FROM jobs '
                         'WHERE queue_message_id IS NOT NULL)')
        clause = ' AND '.join(where)

        removed = 0
        if report.get('db_path'):
            # SQLite: batch on rowid so a large backlog never locks the table
            # in one statement.
            while True:
                result = db.session.execute(text(
                    f'DELETE FROM {table} WHERE rowid IN '
                    f'(SELECT rowid FROM {table} WHERE {clause} LIMIT {int(batch_size)})'
                ), params)
                db.session.commit()
                if not result.rowcount:
                    break
                removed += result.rowcount
                if result.rowcount < batch_size:
                    break
        else:
            # Other engines have no portable rowid; one statement, one commit.
            result = db.session.execute(
                text(f'DELETE FROM {table} WHERE {clause}'), params)
            db.session.commit()
            removed = result.rowcount or 0
        deleted[key] = removed

    report['deleted'] = deleted
    report['deleted_rows'] = sum(deleted.values())

    if vacuum:
        report['vacuum'] = _vacuum(report.get('db_path'), allow_restart=allow_restart)
        if report.get('db_path') and os.path.exists(report['db_path']):
            report['db_bytes_after'] = os.path.getsize(report['db_path'])
    return report


def _vacuum(db_path, allow_restart=False, service='serverkit'):
    """VACUUM the database, restarting the panel only if a lock demands it."""
    from sqlalchemy import text
    from app import db

    if not db_path or not os.path.exists(db_path):
        return {'ok': False, 'error': 'not a SQLite database; skipped'}

    needed = os.path.getsize(db_path)
    free = disk_usage(os.path.dirname(db_path) or '/')
    if free and free['free'] < needed:
        # VACUUM rewrites the whole database beside itself before swapping.
        return {
            'ok': False,
            'error': (f'needs ~{human_bytes(needed)} free to rewrite the database, '
                      f'only {human_bytes(free["free"])} available — '
                      f'reclaim filesystem space first'),
        }

    try:
        # VACUUM cannot run inside a transaction, and SQLAlchemy opens one for
        # every session statement — so it needs its own autocommit connection.
        db.session.commit()
        with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            conn.execute(text('VACUUM'))
        return {'ok': True, 'restarted': False}
    except Exception as exc:
        if not allow_restart:
            return {'ok': False, 'error': f'{exc} (retry with --allow-restart)'}
        locked_by = exc

    # Something else holds a write lock. Stop the panel, vacuum, start it back.
    db.session.remove()
    stopped, _, err = _run(['systemctl', 'stop', service], timeout=120)
    if not stopped:
        return {'ok': False,
                'error': f'{locked_by}; could not stop {service}: {err.strip()}'}
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=60)
        try:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            conn.execute('VACUUM')
        finally:
            conn.close()
        return {'ok': True, 'restarted': True}
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'restarted': True}
    finally:
        _run(['systemctl', 'start', service], timeout=120)


# ── Candidate registry ──────────────────────────────────────────────────────

def scan(days=DEFAULT_RETENTION_DAYS, keep=DEFAULT_KEEP_SNAPSHOTS,
         backup_dir=BACKUP_DIR, tmp_dir=TMP_DIR, with_db=True,
         older_than_days=None):
    """Measure every reclaim candidate. Reads only — deletes nothing."""
    candidates = []

    all_snapshots = list_snapshots(backup_dir)
    doomed = select_snapshots(all_snapshots, keep, older_than_days)
    kept = len(all_snapshots) - len(doomed)
    if older_than_days is not None:
        title = f'Upgrade snapshots older than {older_than_days} days'
    else:
        title = f'Old upgrade snapshots (keeping newest {keep})'
    candidates.append({
        'key': 'upgrade-snapshots', 'safety': 'safe',
        'title': title,
        'detail': (f'{len(doomed)} of {len(all_snapshots)} snapshot(s) in {backup_dir}'
                   f', {kept} kept' if all_snapshots else f'none in {backup_dir}'),
        'bytes': sum(s['bytes'] for s in doomed),
        'paths': sorted(p for s in doomed for p in s['paths']),
        # The whole inventory, so the CLI can offer a per-snapshot choice.
        'snapshots': all_snapshots,
        'doomed_stamps': [s['stamp'] for s in doomed],
    })

    staging, staging_bytes = _scan_tmp_staging(tmp_dir)
    candidates.append({
        'key': 'tmp-staging', 'safety': 'safe',
        'title': 'Abandoned update staging dirs',
        'detail': f'{len(staging)} item(s) in {tmp_dir}, older than 24h',
        'bytes': staging_bytes, 'paths': staging,
    })

    logs, log_bytes = _scan_oversized_logs()
    candidates.append({
        'key': 'login-logs', 'safety': 'safe',
        'title': 'Oversized btmp/wtmp login logs',
        'detail': ', '.join(os.path.basename(p) for p in logs) or 'none oversized',
        'bytes': log_bytes, 'paths': logs,
    })

    caches, cache_bytes = _scan_package_caches()
    candidates.append({
        'key': 'package-caches', 'safety': 'safe',
        'title': 'Package and build caches (apt/dnf/pip/npm)',
        'detail': ', '.join(caches) or 'none found',
        'bytes': cache_bytes, 'paths': caches,
    })

    candidates.append({
        'key': 'journal', 'safety': 'safe',
        'title': f'Systemd journal above {DEFAULT_JOURNAL_CAP}',
        'detail': 'rotates then vacuums archived journals',
        'bytes': _scan_journal(), 'paths': [],
    })

    candidates.append({
        'key': 'docker-build-cache', 'safety': 'safe',
        'title': 'Docker build cache and dangling images',
        'detail': 'build cache measured; dangling images extra. '
                  'Tagged images and named volumes are left alone',
        'bytes': _scan_docker(), 'paths': [],
    })

    if with_db:
        telemetry = scan_telemetry(days=days)
        rows = telemetry['deletable_rows']
        if rows:
            hit = ', '.join(t['table'] for t in telemetry['tables'] if t['deletable'])
            detail = f'{rows:,} rows across {hit} — then VACUUM'
        else:
            detail = 'nothing to prune'
        candidates.append({
            'key': 'telemetry', 'safety': 'review',
            'title': f'Telemetry rows older than {days} days',
            'detail': detail,
            'bytes': telemetry['bytes'] or 0, 'paths': [],
            'telemetry': telemetry,
        })

    return {
        'disk': disk_usage('/'),
        'candidates': candidates,
        'total_bytes': sum(c['bytes'] or 0 for c in candidates),
    }


def _reclaim_paths(paths, truncate=False):
    """Delete (or truncate) a list of paths, returning bytes actually freed."""
    freed = 0
    for path in paths:
        size = _path_size(path)
        try:
            if truncate:
                with open(path, 'wb'):
                    pass
            elif os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            freed += size
        except OSError:
            continue
    return freed


def reclaim(keys, days=DEFAULT_RETENTION_DAYS, keep=DEFAULT_KEEP_SNAPSHOTS,
            backup_dir=BACKUP_DIR, tmp_dir=TMP_DIR, dry_run=False,
            allow_restart=False, older_than_days=None, snapshot_stamps=None):
    """Run the selected reclaimers.

    Filesystem work is forced ahead of the database VACUUM regardless of the
    order ``keys`` arrives in — see the module docstring.

    ``snapshot_stamps`` deletes exactly those upgrade snapshots, for when the
    operator hand-picked them; otherwise ``keep``/``older_than_days`` decide.
    """
    keys = list(keys)
    before = disk_usage('/')
    results = []

    def record(key, freed, note=''):
        results.append({'key': key, 'bytes': freed, 'note': note})

    if 'upgrade-snapshots' in keys:
        if snapshot_stamps is not None:
            wanted = set(snapshot_stamps)
            chosen = [s for s in list_snapshots(backup_dir) if s['stamp'] in wanted]
            paths = sorted(p for s in chosen for p in s['paths'])
            size = sum(s['bytes'] for s in chosen)
            count = len(chosen)
        else:
            doomed = select_snapshots(list_snapshots(backup_dir), keep, older_than_days)
            paths = sorted(p for s in doomed for p in s['paths'])
            size = sum(s['bytes'] for s in doomed)
            count = len(doomed)
        record('upgrade-snapshots', size if dry_run else _reclaim_paths(paths),
               f'{count} snapshot(s), {len(paths)} file(s)')

    if 'tmp-staging' in keys:
        paths, size = _scan_tmp_staging(tmp_dir)
        record('tmp-staging', size if dry_run else _reclaim_paths(paths),
               f'{len(paths)} staging dir(s)')

    if 'login-logs' in keys:
        paths, size = _scan_oversized_logs()
        record('login-logs', size if dry_run else _reclaim_paths(paths, truncate=True),
               f'{len(paths)} log(s) truncated')

    if 'package-caches' in keys:
        paths, size = _scan_package_caches()
        if dry_run:
            record('package-caches', size)
        else:
            # Measure the delta: apt-get clean empties the archives itself, so
            # anything counted afterwards would read as zero.
            _run(['apt-get', 'clean'], timeout=120)
            _reclaim_paths(paths)
            after_size = sum(_path_size(p) for p in paths)
            record('package-caches', max(0, size - after_size))

    if 'journal' in keys:
        size = _scan_journal()
        if dry_run:
            record('journal', size)
        else:
            before_journal = _journal_bytes()
            # --rotate first: --vacuum-size only ever removes *archived*
            # journals, so without a rotation an over-cap active journal is
            # reported as "freed 0B".
            _run(['journalctl', '--rotate'], timeout=60)
            ok, _, err = _run(['journalctl', f'--vacuum-size={DEFAULT_JOURNAL_CAP}'], timeout=120)
            freed = max(0, before_journal - _journal_bytes()) if ok else 0
            record('journal', freed, '' if ok else err.strip()[:120])

    if 'docker-build-cache' in keys:
        size = _scan_docker()
        if dry_run:
            record('docker-build-cache', size)
        else:
            freed = 0
            notes = []
            for cmd in (['docker', 'image', 'prune', '-f'],
                        ['docker', 'builder', 'prune', '-f']):
                ok, out, err = _run(cmd, timeout=600)
                if ok:
                    # docker reports the truth; our scan can only estimate,
                    # because shared layers make dangling-image sizes overlap.
                    freed += _parse_reclaimed(out)
                else:
                    notes.append(err.strip()[:80])
            record('docker-build-cache', freed, '; '.join(notes))

    # Database last: VACUUM needs the headroom the steps above just freed.
    if 'telemetry' in keys:
        report = prune_telemetry(days=days, dry_run=dry_run, allow_restart=allow_restart)
        if dry_run:
            record('telemetry', report.get('bytes') or 0,
                   f"{report['deletable_rows']:,} row(s)")
        else:
            freed = 0
            if report.get('db_bytes') and report.get('db_bytes_after'):
                freed = max(0, report['db_bytes'] - report['db_bytes_after'])
            vacuum = report.get('vacuum') or {}
            note = f"{report['deleted_rows']:,} row(s) deleted"
            if not vacuum.get('ok'):
                note += f"; VACUUM skipped: {vacuum.get('error', 'unknown')}"
            elif vacuum.get('restarted'):
                note += '; panel restarted for VACUUM'
            record('telemetry', freed, note)

    after = disk_usage('/')
    return {
        'dry_run': dry_run,
        'results': results,
        'freed_bytes': sum(r['bytes'] or 0 for r in results),
        'disk_before': before,
        'disk_after': after,
    }
