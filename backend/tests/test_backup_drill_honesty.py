"""A restore drill that never ran must not read as proof that it did.

Plan 75 §A1. The live bug this pins down:

`_drill_badge` returned `ok` for any status that was not literally `'failed'`.
A drill skipped for lack of scratch space records `skipped_no_space` AND stamps
`last_drill_at`, so it fell through every branch — and Doctor reported

    "A recent restore drill proved this backup restores."

about a drill that never executed. It also self-perpetuated: each skip
refreshed `last_drill_at`, so a policy permanently short of scratch space could
never even go `stale`. It would report proven, forever, having proven nothing.

The drill service itself was careful — its own comment reads "loud skip, never a
silent pass" — and the frontend renders an amber pill. The honesty was lost in
the one place that summarises it, which is the place Doctor reads.

Second defect: `BackupAlertService.on_drill_result` already maps
`skipped_no_space` to a failed outcome, but only the exception path ever called
it, so that branch was unreachable and a skipped drill notified nobody.

The rule: **`ok` must be positively earned.**
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app import db
from app.models.backup_policy import BackupPolicy
from app.services.backup_policy_service import BackupPolicyService
from app.services.doctor_service import DoctorService


def _policy(app, status, drilled_ago=timedelta(hours=1), cadence='weekly'):
    policy = BackupPolicy(target_type='application', target_id=1,
                          drill_cadence=cadence)
    policy.last_drill_status = status
    policy.last_drill_at = datetime.utcnow() - drilled_ago
    db.session.add(policy)
    db.session.commit()
    return policy


# --------------------------------------------------------------------------- #
# The badge
# --------------------------------------------------------------------------- #

def test_skipped_drill_is_not_ok(app):
    """The bug, stated directly."""
    policy = _policy(app, 'skipped_no_space')

    assert BackupPolicyService._drill_badge(policy) == 'skipped'


def test_successful_drill_is_ok(app):
    policy = _policy(app, 'success')

    assert BackupPolicyService._drill_badge(policy) == 'ok'


def test_failed_drill_is_failed(app):
    policy = _policy(app, 'failed')

    assert BackupPolicyService._drill_badge(policy) == 'failed'


def test_never_drilled_is_never(app):
    policy = BackupPolicy(target_type='application', target_id=1,
                          drill_cadence='weekly')
    db.session.add(policy)
    db.session.commit()

    assert BackupPolicyService._drill_badge(policy) == 'never'


def test_unrecognised_status_is_not_ok(app):
    """A status the panel does not know is not evidence of anything.

    Reporting an unhandled state as ok is precisely how the skip bug happened;
    a future drill outcome must not be able to reintroduce it.
    """
    policy = _policy(app, 'partially_restored_maybe')

    assert BackupPolicyService._drill_badge(policy) == 'unknown'


def test_stale_only_applies_to_a_successful_drill(app):
    """Staleness is a property of proof, not of attempts."""
    old = _policy(app, 'success', drilled_ago=timedelta(days=90))

    assert BackupPolicyService._drill_badge(old) == 'stale'


def test_a_recent_skip_does_not_mask_an_old_success(app):
    """The self-perpetuating half: a skip refreshes last_drill_at.

    Before the fix this returned 'ok' — the skip reset the staleness clock and
    the policy looked freshly proven. It must now report the skip.
    """
    policy = _policy(app, 'skipped_no_space', drilled_ago=timedelta(minutes=1))

    assert BackupPolicyService._drill_badge(policy) == 'skipped'


# --------------------------------------------------------------------------- #
# What Doctor tells the operator
# --------------------------------------------------------------------------- #

def test_doctor_does_not_claim_a_skipped_backup_is_proven(app):
    """The sentence that was wrong: "proved this backup restores"."""
    policy = _policy(app, 'skipped_no_space')

    check = DoctorService._backup_drill_stale_check(policy)

    assert check['status'] == 'warn'
    assert 'proved' not in check['detail']
    assert 'could not run' in check['detail']
    assert 'Nothing has been proven' in check['detail']


def test_doctor_reports_a_successful_drill_as_ok(app):
    policy = _policy(app, 'success')

    check = DoctorService._backup_drill_stale_check(policy)

    assert check['status'] == 'ok'


def test_doctor_warns_on_an_unrecognised_state(app):
    policy = _policy(app, 'something_new')

    check = DoctorService._backup_drill_stale_check(policy)

    assert check['status'] == 'warn'
    assert 'unproven' in check['detail']


def test_drill_check_is_skipped_when_cadence_is_off(app):
    """No cadence means no expectation — not a warning."""
    policy = _policy(app, 'skipped_no_space', cadence='off')

    assert DoctorService._backup_drill_stale_check(policy) is None


# --------------------------------------------------------------------------- #
# The operator actually gets told
# --------------------------------------------------------------------------- #

def test_a_skipped_drill_notifies(app):
    """on_drill_result already handled skipped_no_space; nothing called it."""
    policy = _policy(app, 'skipped_no_space')

    with patch('app.services.backup_alert_service.BackupAlertService'
               '.on_drill_result') as alert:
        from app.services.backup_drill_service import BackupDrillService
        BackupDrillService._notify_failed(
            policy.id, 'run-1', 'needs 10 bytes, 1 free',
            status='skipped_no_space')

    alert.assert_called_once()
    assert alert.call_args.kwargs['status'] == 'skipped_no_space'


def test_a_failed_drill_still_notifies_as_failed(app):
    """The pre-existing path must keep its behaviour."""
    policy = _policy(app, 'failed')

    with patch('app.services.backup_alert_service.BackupAlertService'
               '.on_drill_result') as alert:
        from app.services.backup_drill_service import BackupDrillService
        BackupDrillService._notify_failed(policy.id, 'run-1', 'boom')

    assert alert.call_args.kwargs['status'] == 'failed'


def test_alert_service_treats_a_skip_as_a_failed_outcome(app):
    """Pins the mapping the skip path now depends on."""
    from app.services.backup_alert_service import BackupAlertService

    policy = _policy(app, 'skipped_no_space')

    with patch.object(BackupAlertService, '_get_state', return_value=None), \
         patch.object(BackupAlertService, '_set_state'), \
         patch.object(BackupAlertService, '_notify') as notify:
        BackupAlertService.on_drill_result(policy, status='skipped_no_space',
                                           error='no space')

    assert notify.call_args[0][0] == 'backup.drill_failed'
