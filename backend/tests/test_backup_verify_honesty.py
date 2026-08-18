"""A backup that FAILED verification must not read as a verified backup.

Plan 75 §A1 follow-up — the sibling surface the drill fix did not cover.

`verify_run_tier1` is honest: an unreadable archive lands at level `none` with
an error, a checksum mismatch lands at `listed` with an explicit mismatch
message, and "no stored checksum" is recorded as its own state. The honesty was
lost at the summarising boundary, exactly as with the drill badge:
`_backup_unverified_check` returned `ok` for any level that was not literally
`'none'`, so Doctor reported

    Latest backup verified (listed).

about a run whose `verify_error` said "Checksum mismatch" — the single worst
signal a verifier can produce, rendered as a green check. An unreadable
archive (`none` + error) likewise read as "has not been verified yet",
understating positive evidence of a problem as a mere absence of checks.

The repair path (`_verify_run_locally`) was already honest; only the dashboard
check collapsed the states. The rule is the drill rule: **`ok` must be
positively earned.**
"""

from datetime import datetime

import pytest

from app import db
from app.models.backup_policy import BackupPolicy
from app.models.backup_run import BackupRun
from app.services.doctor_service import DoctorService


def _policy(app):
    policy = BackupPolicy(target_type='application', target_id=1)
    db.session.add(policy)
    db.session.commit()
    return policy


def _run(app, policy, verify_level='none', verify_error=None, verified=False):
    run = BackupRun(policy_id=policy.id, kind='full', status='success',
                    started_at=datetime.utcnow(),
                    verify_level=verify_level, verify_error=verify_error,
                    verified=verified)
    db.session.add(run)
    db.session.commit()
    return run


# --------------------------------------------------------------------------- #
# Verification that ran and came back bad is a failure, not "unverified"
# --------------------------------------------------------------------------- #

def test_checksum_mismatch_is_not_ok(app):
    """The bug, stated directly: corruption evidence rendered as verified."""
    policy = _policy(app)
    _run(app, policy, verify_level='listed',
         verify_error='Checksum mismatch: expected abc123…, got def456…')

    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'fail'
    assert 'Checksum mismatch' in check['detail']


def test_unreadable_archive_is_a_failure_not_an_absence(app):
    """`none` + an error means verification RAN and the archive could not be
    read — worse than "not checked yet", and worded accordingly."""
    policy = _policy(app)
    _run(app, policy, verify_level='none',
         verify_error='Primary archive is not readable: unexpected EOF')

    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'fail'
    assert 'failed verification' in check['detail']


# --------------------------------------------------------------------------- #
# "Couldn't check" is its own answer — never ok
# --------------------------------------------------------------------------- #

def test_listed_without_a_stored_checksum_is_unproven_not_verified(app):
    policy = _policy(app)
    _run(app, policy, verify_level='listed',
         verify_error='No stored checksum available to compare against.')

    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'warn'
    assert 'unproven' in check['detail']


def test_never_verified_warns_as_before(app):
    """The pre-existing honest path keeps its behaviour."""
    policy = _policy(app)
    _run(app, policy, verify_level='none')

    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'warn'
    assert 'has not been verified' in check['detail']


# --------------------------------------------------------------------------- #
# ok must be positively earned — and still is
# --------------------------------------------------------------------------- #

def test_hashed_is_ok(app):
    policy = _policy(app)
    _run(app, policy, verify_level='hashed')

    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'ok'
    assert 'hashed' in check['detail']


def test_drilled_is_ok(app):
    policy = _policy(app)
    _run(app, policy, verify_level='drilled')

    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'ok'


def test_legacy_remote_verified_run_is_still_ok(app):
    """The legacy ``verified`` boolean maps to 'listed' with no error — a real
    (if shallow) remote existence check, not a "couldn't check"."""
    policy = _policy(app)
    _run(app, policy, verify_level='none', verified=True)

    check = DoctorService._backup_unverified_check(policy)

    assert check['status'] == 'ok'


def test_no_successful_run_means_no_check(app):
    policy = _policy(app)

    assert DoctorService._backup_unverified_check(policy) is None


# --------------------------------------------------------------------------- #
# The probe itself: a verification that cannot run never promotes the run
# --------------------------------------------------------------------------- #

def test_a_missing_archive_never_reaches_hashed(app, tmp_path):
    """Contract shape: the probe's failure mode is `none` + error, never a
    silent positive."""
    from app.services import backup_verify_service

    policy = _policy(app)
    run = _run(app, policy)
    meta = {'primary_archive': str(tmp_path / 'gone.tar.gz')}

    probes = backup_verify_service.verify_run_tier1(run, meta)

    assert run.verify_level == 'none'
    assert run.verify_error
    assert probes['hashed'] is False
