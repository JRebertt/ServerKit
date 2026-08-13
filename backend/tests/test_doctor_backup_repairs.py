"""Plan 72 A.1 — the two doctor repair kinds that could never work.

``backup_drill_stale.*`` and ``backup_unverified.*`` both emitted
``repairable: True``, but ``DoctorService.repair()`` only knew drift, service,
dns and extension. Every Repair button those checks rendered came back
"Unknown repair kind: backup_drill" — a button that failed 100% of the time,
on the check family whose entire job is telling you whether your backups can
be trusted.

The dispatcher now handles both. They are deliberately asymmetric: a drill is
enqueued as a job (so the answer carries a job id), while verification runs
inline and returns a verdict — and verification itself picks its ladder from
what the run actually has, on disk or offsite.
"""
from unittest.mock import patch

import pytest

from app.services.doctor_service import DoctorService


class _Job:
    id = 4242


@pytest.fixture
def policy(app):
    """A backup policy the repair refs can point at."""
    from app import db
    from app.models.backup_policy import BackupPolicy

    row = BackupPolicy(target_type='app', target_id=1)
    db.session.add(row)
    db.session.commit()
    return row


def _run_for(policy, remote_key=None):
    """A successful backup run, offsite or local-only."""
    from app import db
    from app.models.backup_run import BackupRun

    run = BackupRun(policy_id=policy.id, kind='full', status='success')
    run.remote_key = remote_key
    db.session.add(run)
    db.session.commit()
    return run


def _tier1_setting(level, error=None):
    """Stand-in for verify_run_tier1, which mutates the run's verify ladder in
    place and does not commit."""
    def _apply(run, meta):
        run.verify_level = level
        run.verify_error = error
        return {}
    return _apply


# --------------------------------------------------------------------------- #
# The regression itself
# --------------------------------------------------------------------------- #
def test_both_kinds_are_known_to_the_dispatcher(app, policy):
    """The whole bug: these two came back 'Unknown repair kind'."""
    run = _run_for(policy, remote_key='s3://bucket/key')

    with patch('app.services.backup_drill_service.BackupDrillService.request_drill',
               return_value=_Job()), \
            patch('app.services.backup_policy_service.BackupPolicyService.verify_run',
                  return_value={'success': True, 'verified': True}):
        results = DoctorService.repair([
            {'kind': 'backup_drill', 'policy_id': policy.id},
            {'kind': 'backup_verify', 'policy_id': policy.id, 'run_id': run.id},
        ])

    assert [r['success'] for r in results] == [True, True]
    for r in results:
        assert 'Unknown repair kind' not in str(r.get('error') or '')


def test_unknown_kind_still_errors_cleanly(app):
    results = DoctorService.repair([{'kind': 'nonsense'}])

    assert results[0]['success'] is False
    assert 'Unknown repair kind: nonsense' in results[0]['error']


def test_each_result_echoes_its_input_item(app, policy):
    """DoctorPanel pairs answers back to checks by the echoed item."""
    with patch('app.services.backup_drill_service.BackupDrillService.request_drill',
               return_value=_Job()):
        item = {'kind': 'backup_drill', 'policy_id': policy.id}
        results = DoctorService.repair([item])

    assert results[0]['item'] == item


# --------------------------------------------------------------------------- #
# backup_drill — asynchronous, surfaces a job id
# --------------------------------------------------------------------------- #
class TestBackupDrillRepair:

    def test_enqueues_a_drill_and_returns_the_job_id(self, app, policy):
        with patch('app.services.backup_drill_service.BackupDrillService.request_drill',
                   return_value=_Job()) as request:
            result = DoctorService.repair(
                [{'kind': 'backup_drill', 'policy_id': policy.id}])[0]

        assert result['success'] is True
        assert result['job_id'] == 4242
        assert request.call_args.args[0].id == policy.id

    def test_the_drill_is_attributed_to_the_doctor(self, app, policy):
        """The drill history shows where a drill came from; a doctor-initiated
        one should not masquerade as someone pressing the manual button."""
        with patch('app.services.backup_drill_service.BackupDrillService.request_drill',
                   return_value=_Job()) as request:
            DoctorService.repair([{'kind': 'backup_drill', 'policy_id': policy.id}])

        assert request.call_args.kwargs['trigger'] == 'doctor'

    def test_a_refusal_is_reported_not_raised(self, app, policy):
        """'already drilling' / 'no successful backup' are ordinary answers."""
        from app.services.backup_drill_service import BackupDrillError

        with patch('app.services.backup_drill_service.BackupDrillService.request_drill',
                   side_effect=BackupDrillError('A restore drill is already in progress.')):
            result = DoctorService.repair(
                [{'kind': 'backup_drill', 'policy_id': policy.id}])[0]

        assert result['success'] is False
        assert 'already in progress' in result['error']

    def test_an_unexpected_failure_does_not_escape(self, app, policy):
        with patch('app.services.backup_drill_service.BackupDrillService.request_drill',
                   side_effect=RuntimeError('queue exploded')):
            result = DoctorService.repair(
                [{'kind': 'backup_drill', 'policy_id': policy.id}])[0]

        assert result['success'] is False
        assert 'queue exploded' in result['error']

    def test_a_deleted_policy_reads_as_gone(self, app):
        """policy_id comes back from the client echoing a repair_ref; a stale
        one must not raise."""
        result = DoctorService.repair(
            [{'kind': 'backup_drill', 'policy_id': 999999}])[0]

        assert result['success'] is False
        assert 'no longer exists' in result['error']


# --------------------------------------------------------------------------- #
# backup_verify — synchronous, and routed by what the run actually has
#
# verify_run compares against the REMOTE copy and raises when there is none, so
# routing every run through it would leave the button broken for every install
# without offsite storage — the same defect this item exists to remove.
# --------------------------------------------------------------------------- #
class TestBackupVerifyRepair:

    def _repair(self, policy, run):
        return DoctorService.repair([{'kind': 'backup_verify',
                                      'policy_id': policy.id,
                                      'run_id': run.id}])[0]

    # -- offsite runs ------------------------------------------------------ #

    def test_a_verified_remote_copy_succeeds(self, app, policy):
        run = _run_for(policy, remote_key='s3://bucket/key')

        with patch('app.services.backup_policy_service.BackupPolicyService.verify_run',
                   return_value={'success': True, 'verified': True}) as remote, \
                patch('app.services.backup_verify_service.verify_run_tier1') as tier1:
            result = self._repair(policy, run)

        assert result['success'] is True
        assert result['verified'] is True
        assert remote.call_args.args[1] == run.id
        tier1.assert_not_called()

    def test_no_job_id_because_it_is_synchronous(self, app, policy):
        """Unlike the drill, nothing is queued — claiming a job id would send
        the console looking for a job that does not exist."""
        run = _run_for(policy, remote_key='s3://bucket/key')

        with patch('app.services.backup_policy_service.BackupPolicyService.verify_run',
                   return_value={'success': True, 'verified': True}):
            result = self._repair(policy, run)

        assert 'job_id' not in result

    def test_a_mismatching_remote_copy_is_a_failure_not_a_fix(self, app, policy):
        """Verification running and finding a BAD copy is a worse outcome than
        'unverified' — reporting it as a successful repair would be a lie."""
        run = _run_for(policy, remote_key='s3://bucket/key')

        with patch('app.services.backup_policy_service.BackupPolicyService.verify_run',
                   return_value={'success': True, 'verified': False,
                                 'detail': {'size': 'mismatch'}}):
            result = self._repair(policy, run)

        assert result['success'] is False
        assert 'did not match' in result['error']

    def test_a_policy_error_is_reported_not_raised(self, app, policy):
        from app.services.backup_policy_service import BackupPolicyError

        run = _run_for(policy, remote_key='s3://bucket/key')
        with patch('app.services.backup_policy_service.BackupPolicyService.verify_run',
                   side_effect=BackupPolicyError('Backup not found')):
            result = self._repair(policy, run)

        assert result['success'] is False
        assert 'Backup not found' in result['error']

    # -- local-only runs --------------------------------------------------- #

    def test_local_only_run_is_verified_on_disk_not_remotely(self, app, policy):
        run = _run_for(policy, remote_key=None)

        with patch('app.services.backup_verify_service.verify_run_tier1',
                   side_effect=_tier1_setting('hashed')) as tier1, \
                patch('app.services.backup_policy_service.BackupPolicyService.verify_run') as remote:
            result = self._repair(policy, run)

        assert result['success'] is True
        assert result['verify_level'] == 'hashed'
        tier1.assert_called_once()
        remote.assert_not_called()   # there is nothing to compare against

    def test_an_unreadable_archive_is_a_failure(self, app, policy):
        """Tier 1 leaves the level at 'none' when it cannot read the archive —
        the worst answer, and the one most worth knowing before a restore
        depends on it."""
        run = _run_for(policy)

        with patch('app.services.backup_verify_service.verify_run_tier1',
                   side_effect=_tier1_setting(
                       'none', 'Primary archive not found on disk (not readable).')):
            result = self._repair(policy, run)

        assert result['success'] is False
        assert 'not readable' in result['error']

    def test_a_checksum_mismatch_is_a_failure_even_though_it_is_readable(self, app, policy):
        """'listed' clears the doctor check, but a mismatch means the archive
        is not the one the manifest describes — not a fix."""
        run = _run_for(policy)

        with patch('app.services.backup_verify_service.verify_run_tier1',
                   side_effect=_tier1_setting(
                       'listed', 'Checksum mismatch: expected abc123…')):
            result = self._repair(policy, run)

        assert result['success'] is False
        assert 'Checksum mismatch' in result['error']

    def test_the_verified_level_is_persisted(self, app, policy):
        """verify_run_tier1 mutates without committing, so the commit is the
        repair's job — otherwise the doctor reports 'unverified' again on the
        very next sweep."""
        from app import db
        from app.models.backup_run import BackupRun

        run = _run_for(policy)
        with patch('app.services.backup_verify_service.verify_run_tier1',
                   side_effect=_tier1_setting('hashed')):
            self._repair(policy, run)
        db.session.expire_all()

        assert BackupRun.query.filter_by(id=run.id).first().verify_level == 'hashed'

    # -- lookup failures --------------------------------------------------- #

    def test_a_missing_run_reads_as_not_found(self, app, policy):
        result = DoctorService.repair([{'kind': 'backup_verify',
                                        'policy_id': policy.id,
                                        'run_id': 987654}])[0]

        assert result['success'] is False
        assert 'not found' in result['error'].lower()

    def test_a_deleted_policy_reads_as_gone(self, app):
        result = DoctorService.repair(
            [{'kind': 'backup_verify', 'policy_id': 999999, 'run_id': 7}])[0]

        assert result['success'] is False
        assert 'no longer exists' in result['error']


def test_every_unverified_backup_still_gets_a_button(app, policy):
    """The check must keep offering the repair regardless of offsite storage —
    now that both ladders work, gating it would hide a working fix."""
    _run_for(policy, remote_key=None)
    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'warn'
    assert check['repairable'] is True
    assert check['repair_ref']['kind'] == 'backup_verify'
