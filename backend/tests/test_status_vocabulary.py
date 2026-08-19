"""Plan 77 D1/D2 — canonical status vocabulary + run lifecycle transitions.

Parity gate: every status spelling a run model writes today is either a
canonical constant or a known legacy alias that normalize() maps home.
"""
import pytest

from app.models import status as st


MEASURED_LIFECYCLE_SPELLINGS = {
    # canonical
    'pending', 'queued', 'running', 'success', 'failed', 'cancelled',
    # legacy terminal spellings measured across run models (2026-08-18 audit)
    'succeeded', 'completed', 'done', 'failure', 'error', 'canceled',
    'scheduled',
}


def test_every_measured_lifecycle_spelling_normalizes_to_canonical():
    for spelling in MEASURED_LIFECYCLE_SPELLINGS:
        assert st.normalize(spelling) in st.ALL, spelling


def test_terminal_set_and_aliases():
    assert st.is_terminal('succeeded')
    assert st.is_terminal('done')
    assert st.is_terminal('failure')
    assert not st.is_terminal('running')
    assert not st.is_terminal('analyzing')  # domain phase, passes through


def test_normalize_passes_domain_states_through():
    assert st.normalize('rolled_back') == 'rolled_back'
    assert st.normalize(None) is None
    assert st.normalize('') == ''


def test_run_lifecycle_mixin_transitions(app):
    from app import db
    from app.models.mixins import RunLifecycleMixin

    class _FakeRun(RunLifecycleMixin):
        # stand-in with the standard columns; __table__ faked via a dict
        class _T:
            columns = {'status': None, 'started_at': None,
                       'completed_at': None, 'duration_seconds': None,
                       'error': None}
        __table__ = _T()
        status = None
        started_at = None
        completed_at = None
        duration_seconds = None
        error = None

    run = _FakeRun()
    run.mark_running()
    assert run.status == st.RUNNING and run.started_at is not None

    run.mark_succeeded()
    assert run.status == st.SUCCESS
    assert run.completed_at is not None
    assert run.duration_seconds is not None and run.duration_seconds >= 0

    run2 = _FakeRun()
    run2.mark_running()
    run2.mark_failed(error='boom')
    assert run2.status == st.FAILED and run2.error == 'boom'

    run3 = _FakeRun()
    run3.mark_cancelled()
    assert run3.status == st.CANCELLED


def test_legacy_spelling_override(app):
    from app.models.mixins import RunLifecycleMixin

    class _LegacyRun(RunLifecycleMixin):
        __status_success__ = 'succeeded'  # domain not yet data-migrated
        class _T:
            columns = {'status': None, 'completed_at': None}
        __table__ = _T()
        status = None
        started_at = None
        completed_at = None

    run = _LegacyRun()
    run.mark_succeeded()
    assert run.status == 'succeeded'
    assert st.normalize(run.status) == st.SUCCESS
