"""A crash a route handled itself must still reach /monitoring/errors (plan 76, B).

The global 500 handler is what logs a crash and writes it to the centralized
error log. A route that catches ``Exception`` itself answers before that
handler runs, so the crash is recorded nowhere — and the errors page reads
empty precisely because someone "handled" it. 43 API handlers did this while
also returning ``str(exc)`` to the caller.

These tests pin both halves of the contract: the crash is recorded, and the
caller gets a correlatable request id instead of the exception text.

No blueprint is registered here on purpose. The ``app`` fixture is per-test but
the application object underneath it is built once per session, so a route
added in a test stays mounted for every later one. The door is a plain
function; a request context is all it needs.
"""

import pytest
from flask import jsonify

from app.error_reporting import (
    record_unexpected,
    unexpected_error_body,
    unexpected_response,
)


def _boom(message='secret-connstring-in-here'):
    """A raised-and-caught exception, so it carries a real traceback."""
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        return exc


def _errors_for(endpoint):
    from app.models.error_log import ErrorLog
    return ErrorLog.query.filter_by(endpoint=endpoint).all()


class TestTheOldShapeLosesTheCrash:
    """Why this milestone exists — asserted, not assumed."""

    def test_catching_the_exception_yourself_records_nothing(self, app):
        with app.test_request_context('/__probe/handled-badly'):
            try:
                raise RuntimeError('secret-connstring-in-here')
            except Exception as exc:  # noqa: BLE001 - the shape being replaced
                body, status = jsonify({'error': str(exc)}), 500

            assert status == 500
            assert body.get_json()['error'] == 'secret-connstring-in-here'
            assert _errors_for('/__probe/handled-badly') == [], (
                'the locally-handled crash was expected to bypass the error log; '
                'if it now records, the bypass is closed and this test should '
                'become the positive assertion'
            )


class TestTheDoorRecordsAndRedacts:

    def test_the_crash_reaches_the_error_log(self, app):
        with app.test_request_context('/__probe/recorded'):
            unexpected_response(_boom())

        rows = _errors_for('/__probe/recorded')
        assert len(rows) == 1, 'the swallowed crash did not reach the error log'
        assert rows[0].exception_type == 'RuntimeError'
        assert 'secret-connstring-in-here' in rows[0].message

    def test_the_traceback_is_kept_for_whoever_reads_the_log(self, app):
        with app.test_request_context('/__probe/traceback'):
            unexpected_response(_boom())

        row = _errors_for('/__probe/traceback')[0]
        assert 'RuntimeError' in (row.traceback or '')

    def test_the_caller_gets_a_request_id_not_the_exception_text(self, app):
        with app.test_request_context('/__probe/redacted'):
            body, status = unexpected_response(_boom())

        assert status == 500
        assert body['error'] == 'Internal server error'
        assert body['code'] == 'internal_error'
        assert body['request_id']
        assert 'secret-connstring' not in str(body)

    def test_the_recorded_request_id_matches_the_one_returned(self, app):
        """An id the caller can quote is the point; a different id in the log
        makes it useless for support."""
        with app.test_request_context('/__probe/correlated'):
            body, _ = unexpected_response(_boom())

        row = _errors_for('/__probe/correlated')[0]
        assert (row.get_context() or {}).get('request_id') == body['request_id']

    def test_the_endpoint_and_method_are_recorded(self, app):
        with app.test_request_context('/__probe/where', method='POST'):
            unexpected_response(_boom())

        row = _errors_for('/__probe/where')[0]
        assert row.method == 'POST'

    def test_repeated_crashes_dedupe_rather_than_flood(self, app):
        """error_log_service dedupes by fingerprint; routing through the door
        must not defeat that and turn a hot loop into a million rows."""
        for _ in range(3):
            with app.test_request_context('/__probe/deduped'):
                unexpected_response(_boom())

        rows = _errors_for('/__probe/deduped')
        assert len(rows) == 1
        assert rows[0].count == 3


class TestReportingNeverMasksTheCrash:
    """`record_error` is bulletproof by contract; the door must be too, or a
    failure to *report* a crash becomes a second, louder crash."""

    def test_a_broken_recorder_does_not_raise(self, app, monkeypatch):
        from app.services import error_log_service

        def _explode(*_a, **_kw):
            raise RuntimeError('error log is down')

        monkeypatch.setattr(error_log_service, 'record_error', _explode)

        with app.test_request_context('/__probe/recorder-down'):
            body, status = unexpected_response(_boom())

        assert status == 500
        assert body['request_id']

    def test_it_survives_a_session_already_in_a_failed_transaction(self, app):
        """The case the rollback exists for: a DB-caused crash leaves the shared
        session unusable, and record_error's first query would raise."""
        from app import db

        with app.test_request_context('/__probe/failed-txn'):
            try:
                db.session.execute(db.text('SELECT * FROM table_that_is_not_there'))
            except Exception:  # noqa: BLE001
                pass
            body, status = unexpected_response(_boom())

        assert status == 500
        assert len(_errors_for('/__probe/failed-txn')) == 1


def test_the_global_handler_and_the_door_answer_identically(app, client):
    """Two doors that answer differently are two contracts again."""
    with app.test_request_context('/__probe/shape'):
        body, _ = unexpected_response(_boom())

    assert body == unexpected_error_body(body['request_id'])


def test_record_unexpected_returns_the_id_it_recorded_under(app):
    with app.test_request_context('/__probe/returns-id'):
        request_id = record_unexpected(_boom())

    assert request_id
    recorded = _errors_for('/__probe/returns-id')[0].get_context() or {}
    assert recorded.get('request_id') == request_id
