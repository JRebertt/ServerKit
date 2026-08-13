"""Plan 72 A.1 — the two doctor repair kinds that could never work.

``backup_drill_stale.*`` and ``backup_unverified.*`` both emitted
``repairable: True``, but ``DoctorService.repair()`` only knew drift, service,
dns and extension. Every Repair button those checks rendered came back
"Unknown repair kind: backup_drill" — a button that failed 100% of the time.

The dispatcher now handles both. They are deliberately asymmetric: a drill is
enqueued as a job (so the answer carries a job id), while verification runs
inline and returns a verdict.
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


# --------------------------------------------------------------------------- #
# The regression itself
# --------------------------------------------------------------------------- #
def test_both_kinds_are_known_to_the_dispatcher(app, policy):
    """The whole bug: these two came back 'Unknown repair kind'."""
    with patch('app.services.backup_drill_service.BackupDrillService.request_drill',
               return_value=_Job()), \
            patch('app.services.backup_policy_service.BackupPolicyService.verify_run',
                  return_value={'success': True, 'verified': True}):
        results = DoctorService.repair([
            {'kind': 'backup_drill', 'policy_id': policy.id},
            {'kind': 'backup_verify', 'policy_id': policy.id, 'run_id': 7},
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
# backup_verify — synchronous, returns a verdict
# --------------------------------------------------------------------------- #
class TestBackupVerifyRepair:

    def _verify(self, policy, **patch_kwargs):
        with patch('app.services.backup_policy_service.BackupPolicyService.verify_run',
                   **patch_kwargs) as verify:
            result = DoctorService.repair([{'kind': 'backup_verify',
                                            'policy_id': policy.id,
                                            'run_id': 7}])[0]
        return result, verify

    def test_a_verified_copy_succeeds(self, app, policy):
        result, verify = self._verify(
            policy, return_value={'success': True, 'verified': True})

        assert result['success'] is True
        assert result['verified'] is True
        assert verify.call_args.args[1] == 7

    def test_no_job_id_because_it_is_synchronous(self, app, policy):
        """Unlike the drill, nothing is queued — claiming a job id would send
        the console looking for a job that does not exist."""
        result, _ = self._verify(
            policy, return_value={'success': True, 'verified': True})

        assert 'job_id' not in result

    def test_a_mismatching_copy_is_a_failure_not_a_fix(self, app, policy):
        """Verification running and finding a BAD copy is a worse outcome than
        'unverified' — reporting it as a successful repair would be a lie."""
        result, _ = self._verify(
            policy, return_value={'success': True, 'verified': False,
                                  'detail': {'size': 'mismatch'}})

        assert result['success'] is False
        assert 'did not match' in result['error']

    def test_a_policy_error_is_reported_not_raised(self, app, policy):
        from app.services.backup_policy_service import BackupPolicyError

        result, _ = self._verify(
            policy, side_effect=BackupPolicyError('Backup not found'))

        assert result['success'] is False
        assert 'Backup not found' in result['error']

    def test_a_deleted_policy_reads_as_gone(self, app):
        result = DoctorService.repair(
            [{'kind': 'backup_verify', 'policy_id': 999999, 'run_id': 7}])[0]

        assert result['success'] is False
        assert 'no longer exists' in result['error']


# --------------------------------------------------------------------------- #
# The other half: don't render a button that cannot work
# --------------------------------------------------------------------------- #
class TestVerifyButtonIsOnlyOfferedWhenItCanWork:
    """verify_run compares against the REMOTE copy and raises when there is
    none. A local-only backup would therefore render a Repair button that
    fails every time — the same defect A.1 exists to remove."""

    def _check_for(self, app, policy, remote_key):
        from app import db
        from app.models.backup_run import BackupRun

        run = BackupRun(policy_id=policy.id, kind='full', status='success')
        run.remote_key = remote_key
        db.session.add(run)
        db.session.commit()
        return DoctorService._backup_unverified_check(policy)

    def test_local_only_backup_is_not_repairable(self, app, policy):
        check = self._check_for(app, policy, None)

        assert check['status'] == 'warn'
        assert check['repairable'] is False
        assert check['repair_ref'] is None
        # and it says what WOULD fix it
        assert 'offsite' in check['detail'] or 'restore drill' in check['detail']

    def test_backup_with_a_remote_copy_is_repairable(self, app, policy):
        check = self._check_for(app, policy, 's3://bucket/key')

        assert check['status'] == 'warn'
        assert check['repairable'] is True
        assert check['repair_ref']['kind'] == 'backup_verify'
        assert check['repair_ref']['policy_id'] == policy.id
