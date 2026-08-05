"""Tests for the backup "Protection" system: cost model, policy CRUD + schedule
wiring, full/incremental decision, chain-aware retention, and a real incremental
tar round-trip (skipped where GNU tar is unavailable, e.g. Windows dev)."""
import os
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

from app import db
from app.services.backup_cost_service import BackupCostService, GB
from app.services.backup_policy_service import BackupPolicyService, BackupPolicyError
from app.services.backup_service import BackupService

HAS_TAR = os.name == 'posix' and shutil.which('tar') is not None


# --------------------------------------------------------------------------- #
# Cost model
# --------------------------------------------------------------------------- #

def test_compute_cost_uses_per_gb_rate(app):
    # 5 GB on S3 at the $0.023/GB default ≈ $0.115.
    cost = BackupCostService.compute_cost(5 * GB, 's3')
    assert abs(float(cost) - 0.115) < 0.0005
    # Local is free by default — it's the operator's own server disk.
    assert float(BackupCostService.compute_cost(5 * GB, 'local')) == 0.0


def test_format_cost():
    assert BackupCostService.format_cost(0) == '$0.00'
    assert BackupCostService.format_cost(1.2) == '$1.20'
    assert BackupCostService.format_cost(0.0006) == '$0.0006'


def test_runs_per_month():
    assert BackupCostService.runs_per_month('0 2 * * *') == 30   # daily
    assert BackupCostService.runs_per_month('0 2 * * 0') in (4, 5)  # weekly


def test_expected_retained_count_and_projection(app, monkeypatch):
    policy = BackupPolicyService.get_or_create_policy('application', 1001)
    policy.schedule_cron = '0 2 * * *'  # daily
    policy.retention_count = 14
    policy.retention_days = 30
    # Daily for 30 days is capped by retention_count (14).
    assert BackupCostService.expected_retained_count(policy) == 14

    # With a non-zero local rate the projection is count * avg_size * rate.
    monkeypatch.setattr(BackupCostService, 'get_rates',
                        classmethod(lambda cls: {'local': 0.01, 's3': 0.023, 'b2': 0.006}))
    projected = BackupCostService.project_monthly_cost(policy, 1 * GB)
    assert abs(float(projected) - 0.14) < 0.0005  # 14 * 1GB * $0.01


# --------------------------------------------------------------------------- #
# Policy CRUD + schedule wiring
# --------------------------------------------------------------------------- #

def test_policy_update_syncs_scheduled_job(app):
    from app.jobs.models import ScheduledJob
    policy = BackupPolicyService.get_or_create_policy('application', 2002)
    BackupPolicyService.update_policy(policy, {
        'enabled': True, 'schedule_cron': '0 5 * * 0', 'retention_count': 7,
    })
    sched = ScheduledJob.query.filter_by(name='backup.application.2002').first()
    assert sched is not None
    assert sched.cron == '0 5 * * 0'
    assert sched.kind == 'backup.policy.run'
    assert sched.enabled is True
    assert policy.retention_count == 7

    # Toggling off propagates to the schedule (ensure() preserves enabled, so the
    # service must push it explicitly).
    BackupPolicyService.update_policy(policy, {'enabled': False})
    sched = ScheduledJob.query.filter_by(name='backup.application.2002').first()
    assert sched.enabled is False


def test_policy_validation(app):
    policy = BackupPolicyService.get_or_create_policy('application', 3003)
    with pytest.raises(BackupPolicyError):
        BackupPolicyService.update_policy(policy, {'retention_count': 0})
    with pytest.raises(BackupPolicyError):
        BackupPolicyService.update_policy(policy, {'schedule_cron': 'not a cron'})
    with pytest.raises(BackupPolicyError):
        BackupPolicyService.update_policy(policy, {'compression': 'turbo'})
    # No remote storage configured -> enabling remote_copy is rejected.
    with pytest.raises(BackupPolicyError):
        BackupPolicyService.update_policy(policy, {'remote_copy': True})


# --------------------------------------------------------------------------- #
# Full vs incremental decision
# --------------------------------------------------------------------------- #

def test_decide_kind(app, tmp_path, monkeypatch):
    from app.models.backup_run import BackupRun
    monkeypatch.setattr(BackupService, 'BACKUP_BASE_DIR', str(tmp_path))
    policy = BackupPolicyService.get_or_create_policy('application', 4004)

    # No snar yet -> full.
    assert BackupPolicyService._decide_kind(policy) == 'full'

    # Snar exists but no prior full run -> still full.
    snar = BackupPolicyService._snar_path(policy)
    os.makedirs(os.path.dirname(snar), exist_ok=True)
    open(snar, 'w').close()
    assert BackupPolicyService._decide_kind(policy) == 'full'

    # A recent full run -> next is incremental.
    full = BackupRun(policy_id=policy.id, kind='full', status='success',
                     started_at=datetime.utcnow())
    db.session.add(full)
    db.session.commit()
    assert BackupPolicyService._decide_kind(policy) == 'incremental'

    # Full is older than full_every_n_days -> full again.
    full.started_at = datetime.utcnow() - timedelta(days=policy.full_every_n_days + 1)
    db.session.commit()
    assert BackupPolicyService._decide_kind(policy) == 'full'

    # Non-application kinds are always full. wordpress_site lives in the WP
    # extension now (plan 52 D4), so prove the rule with a throwaway
    # registered kind rather than depending on the extension being mounted.
    from app.services import backup_kind_registry
    backup_kind_registry.register(
        'test.kind', resolve=lambda p: {'name': 'k'},
        execute=lambda p, t, k: ('/x', 1, {}), source='test-suite')
    try:
        wp = BackupPolicyService.get_or_create_policy('test.kind', 4040)
        assert BackupPolicyService._decide_kind(wp) == 'full'
    finally:
        backup_kind_registry.unregister('test-suite')


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #

def _mk_run(policy_id, kind, age_days, status='success', meta=None):
    from app.models.backup_run import BackupRun
    run = BackupRun(policy_id=policy_id, kind=kind, status=status,
                    started_at=datetime.utcnow() - timedelta(days=age_days))
    if meta:
        run.set_metadata(meta)
    db.session.add(run)
    db.session.commit()
    return run


def test_retention_keeps_recent_and_deletes_old(app):
    from app.models.backup_run import BackupRun
    policy = BackupPolicyService.get_or_create_policy('application', 5005)
    policy.retention_count = 3
    policy.retention_days = 30
    db.session.commit()

    # 5 daily fulls; the oldest two are out of count, all within days.
    runs = [_mk_run(policy.id, 'full', age) for age in (0, 1, 2, 3, 4)]
    BackupPolicyService.apply_retention(policy)
    remaining = {r.id for r in BackupRun.query.filter_by(policy_id=policy.id).all()}
    # Keep the newest 3 (ages 0,1,2); drop ages 3,4.
    assert runs[0].id in remaining and runs[1].id in remaining and runs[2].id in remaining
    assert runs[3].id not in remaining and runs[4].id not in remaining


def test_retention_always_keeps_last_even_if_too_old(app):
    from app.models.backup_run import BackupRun
    policy = BackupPolicyService.get_or_create_policy('application', 5006)
    policy.retention_count = 5
    policy.retention_days = 7
    db.session.commit()
    # One ancient backup, well past retention_days, is still the only/most recent.
    old = _mk_run(policy.id, 'full', 99)
    BackupPolicyService.apply_retention(policy)
    assert BackupRun.query.get(old.id) is not None


def test_retention_protects_incremental_chain(app):
    from app.models.backup_run import BackupRun
    policy = BackupPolicyService.get_or_create_policy('application', 5007)
    policy.retention_count = 2  # only the 2 newest would normally survive
    policy.retention_days = 30
    db.session.commit()

    full = _mk_run(policy.id, 'full', 5)
    incr1 = _mk_run(policy.id, 'incremental', 3, meta={'incremental': True, 'full_run_id': full.id})
    incr2 = _mk_run(policy.id, 'incremental', 1, meta={'incremental': True, 'full_run_id': full.id})

    BackupPolicyService.apply_retention(policy)
    remaining = {r.id for r in BackupRun.query.filter_by(policy_id=policy.id).all()}
    # incr2 + incr1 are the 2 newest; the full is older than retention_count but
    # MUST be protected because the kept incrementals depend on it.
    assert full.id in remaining
    assert incr1.id in remaining
    assert incr2.id in remaining


# --------------------------------------------------------------------------- #
# Real incremental tar round-trip (Linux/macOS only)
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not HAS_TAR, reason='GNU tar not available (e.g. Windows dev)')
def test_smart_backup_files_incremental_roundtrip(tmp_path):
    source = tmp_path / 'site'
    source.mkdir()
    (source / 'a.txt').write_text('first')
    dest_full = tmp_path / 'full'
    snar = str(tmp_path / 'incremental.snar')

    full = BackupService.smart_backup_files(str(source), str(dest_full), 'full', 'balanced', snar)
    assert full['kind'] == 'full' and os.path.exists(full['archive'])

    # Change the tree, then take an incremental.
    (source / 'b.txt').write_text('second')
    dest_incr = tmp_path / 'incr'
    incr = BackupService.smart_backup_files(str(source), str(dest_incr), 'incremental', 'fast', snar)
    assert incr['incremental'] is True
    # Real proof of incrementality: the incremental archive holds ONLY the
    # changed file (b.txt), not the unchanged a.txt. (Raw byte size isn't a
    # reliable signal for tiny trees — tar/gzip fixed overhead dominates.)
    listing = subprocess.run(['tar', '-tf', incr['archive']], capture_output=True, text=True).stdout
    names = [ln.rstrip('/') for ln in listing.splitlines()]
    assert any(n.endswith('b.txt') for n in names), listing
    assert not any(n.endswith('a.txt') for n in names), listing

    # Restore the chain (full -> incr) and confirm both files reappear.
    restore_to = tmp_path / 'restored' / 'site'
    BackupService.restore_incremental_chain([full['archive'], incr['archive']], str(restore_to))
    assert (restore_to / 'a.txt').read_text() == 'first'
    assert (restore_to / 'b.txt').read_text() == 'second'


# --------------------------------------------------------------------------- #
# Restore wiring
# --------------------------------------------------------------------------- #

def test_chain_archives_orders_full_then_incrementals(app, tmp_path, monkeypatch):
    from app.models.backup_run import BackupRun
    monkeypatch.setattr(BackupService, 'BACKUP_BASE_DIR', str(tmp_path))
    policy = BackupPolicyService.get_or_create_policy('application', 6006)

    def _run(kind, age, full_id=None):
        archive = tmp_path / f'{kind}_{age}.tar.gz'
        archive.write_text('x')
        meta = {'primary_archive': str(archive), 'incremental': kind == 'incremental'}
        if full_id:
            meta['full_run_id'] = full_id
        run = BackupRun(policy_id=policy.id, kind=kind, status='success',
                        started_at=datetime.utcnow() - timedelta(days=age))
        run.set_metadata(meta)
        db.session.add(run)
        db.session.commit()
        return run

    full = _run('full', 5)
    incr1 = _run('incremental', 3, full_id=full.id)
    incr2 = _run('incremental', 1, full_id=full.id)

    # Restoring incr2 needs full -> incr1 -> incr2 in order.
    chain = BackupPolicyService._chain_archives(policy, incr2)
    assert chain == [
        full.get_metadata()['primary_archive'],
        incr1.get_metadata()['primary_archive'],
        incr2.get_metadata()['primary_archive'],
    ]
    # Restoring the full alone needs only the full.
    assert BackupPolicyService._chain_archives(policy, full) == [full.get_metadata()['primary_archive']]


def test_request_restore_enqueues_job(app):
    from app.models.backup_run import BackupRun
    policy = BackupPolicyService.get_or_create_policy('application', 7007)
    run = BackupRun(policy_id=policy.id, kind='full', status='success',
                    started_at=datetime.utcnow())
    db.session.add(run)
    db.session.commit()

    job = BackupPolicyService.request_restore(policy, run.id, {'scope': 'full', 'safety_backup': True})
    assert job.kind == 'restore.run'
    payload = job.get_payload()
    assert payload['run_id'] == run.id
    assert payload['policy_id'] == policy.id
    assert payload['scope'] == 'full'

    # A non-existent run is rejected.
    with pytest.raises(BackupPolicyError):
        BackupPolicyService.request_restore(policy, 999999, {})


@pytest.mark.skipif(not HAS_TAR, reason='GNU tar not available')
def test_full_backup_resets_snar(tmp_path):
    source = tmp_path / 'app'
    source.mkdir()
    (source / 'x').write_text('x')
    snar = str(tmp_path / 'snar.snar')
    BackupService.smart_backup_files(str(source), str(tmp_path / 'f1'), 'full', 'fast', snar)
    assert os.path.exists(snar)
    # A second full deletes + recreates the snar (fresh level-0 chain).
    res = BackupService.smart_backup_files(str(source), str(tmp_path / 'f2'), 'full', 'fast', snar)
    assert res['kind'] == 'full' and os.path.exists(snar)
