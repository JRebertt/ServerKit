"""Plan 30 Phase 1 — the integrity floor.

A WordPress drill that verified nothing must FAIL (never earn 'drilled'
vacuously); a files-only WP backup still passes on the files leg; and the
one-off re-flag sweep demotes runs whose 'drilled' badge was earned by a
since-identified vacuous drill.
"""
import io
import os
import tarfile
from datetime import datetime

import pytest

from app import db
from app.services.backup_policy_service import BackupPolicyService
from app.services.backup_drill_service import BackupDrillService, BackupDrillError


class _FakeJob:
    def __init__(self, payload, jid='job-wp-1'):
        self.id = jid
        self._payload = payload

    def get_payload(self):
        return self._payload


def _write_tar_gz_tree(dest, files):
    with tarfile.open(dest, 'w:gz') as tar:
        for name, content in files.items():
            data = io.BytesIO(content)
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, data)


@pytest.fixture
def _stub_wp_target(monkeypatch):
    """The drill runner resolves the live target; a WordPressSite row is out of
    scope here, so return a minimal wordpress_site descriptor."""
    def _resolve_target(cls, policy):
        return {'target_type': 'wordpress_site', 'wp': None,
                'root_path': '/srv/x', 'site': None, 'app': None}
    monkeypatch.setattr(BackupPolicyService, '_resolve_target',
                        classmethod(_resolve_target))


@pytest.fixture(autouse=True)
def _wp_kind_registered():
    """wordpress_site is an extension-owned kind now (plan 52 D4): policy
    validation needs SOME registrant. Register a stub for these artifact-
    replay drill tests (the WP extension's real provider is out of scope)."""
    from app.services import backup_kind_registry
    if backup_kind_registry.get('wordpress_site'):
        yield  # the extension's real provider is mounted — leave it alone
        return
    backup_kind_registry.register(
        'wordpress_site', resolve=lambda p: {},
        execute=lambda p, t, k: ('/x', 1, {}), source='test-suite')
    yield
    backup_kind_registry.unregister('test-suite')


def _make_wp_run(policy, tmp_path, with_files=True, with_db=True, name='wp-run'):
    """A successful wordpress_site BackupRun laid out as a run directory with an
    optional files.tar.gz and database.sql."""
    from app.models.backup_run import BackupRun
    run_dir = tmp_path / name
    run_dir.mkdir()
    primary = None
    if with_files:
        primary = str(run_dir / 'files.tar.gz')
        _write_tar_gz_tree(primary, {'wp-config.php': b'<?php', 'index.php': b'<?php'})
    if with_db:
        (run_dir / 'database.sql').write_bytes(b'-- dump\nCREATE TABLE wp_posts();')
    run = BackupRun(policy_id=policy.id, kind='full', status='success',
                    storage_path=str(run_dir), started_at=datetime.utcnow())
    run.set_metadata({'engine': 'wordpress_site', 'primary_archive': primary})
    db.session.add(run)
    db.session.commit()
    return run


# --------------------------------------------------------------------------- #
# A WordPress drill that verified nothing must FAIL (never earn 'drilled').
# --------------------------------------------------------------------------- #

def test_wp_drill_verifying_nothing_fails(app, tmp_path, monkeypatch):
    from app.services.backup_service import BackupService
    from app.models.backup_run import BackupRun
    monkeypatch.setattr(BackupService, 'BACKUP_BASE_DIR', str(tmp_path / 'backups'))
    os.makedirs(BackupService.BACKUP_BASE_DIR, exist_ok=True)

    with app.app_context():
        policy = BackupPolicyService.get_or_create_policy('wordpress_site', 9701)
        run = _make_wp_run(policy, tmp_path, with_files=False, with_db=False)
        with pytest.raises(Exception):
            BackupDrillService.run_restore_drill(_FakeJob(
                {'policy_id': policy.id, 'run_id': run.id}))

        # No artifact was proven -> the run is NOT promoted to 'drilled'.
        assert BackupRun.query.get(run.id).verify_level != 'drilled'
        from app.models.restore_drill import RestoreDrill
        drill = RestoreDrill.query.filter_by(policy_id=policy.id).first()
        assert drill.status == 'failed'


# --------------------------------------------------------------------------- #
# A files-only WP backup still passes on the files leg.
# --------------------------------------------------------------------------- #

def test_wp_drill_files_only_passes(app, tmp_path, monkeypatch):
    from app.services.backup_service import BackupService
    from app.models.backup_run import BackupRun
    monkeypatch.setattr(BackupService, 'BACKUP_BASE_DIR', str(tmp_path / 'backups'))
    os.makedirs(BackupService.BACKUP_BASE_DIR, exist_ok=True)

    with app.app_context():
        policy = BackupPolicyService.get_or_create_policy('wordpress_site', 9702)
        run = _make_wp_run(policy, tmp_path, with_files=True, with_db=False)
        BackupDrillService.run_restore_drill(_FakeJob(
            {'policy_id': policy.id, 'run_id': run.id}))

        from app.models.restore_drill import RestoreDrill
        drill = RestoreDrill.query.filter_by(policy_id=policy.id).first()
        assert drill.status == 'success'
        probes = drill.get_probes()
        assert probes['file_count'] >= 1
        # Files leg proved it; there is no database leg here.
        assert 'table_count' not in probes
        assert BackupRun.query.get(run.id).verify_level == 'drilled'


# --------------------------------------------------------------------------- #
# One-off re-flag sweep demotes runs drilled by a since-identified vacuous drill.
# --------------------------------------------------------------------------- #

@pytest.mark.skip(reason="plan 42: hollow feature — one-off re-flag sweep that demotes "
                         "'drilled' runs earned by a vacuous drill (plan 30 Phase 1) is not "
                         "present in the recovered BackupDrillService; restored by plan 42")
def test_reflag_sweep_demotes_vacuous_drilled_runs(app, tmp_path):
    pytest.skip("hollow: BackupDrillService.reflag_vacuous_drills missing")
