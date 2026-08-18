"""Tests for the centralized error log: service dedup, admin API, client
ingestion, and the 500-handler recording hook."""
import pytest

from app import db
from app.models.error_log import ErrorLog
from app.services import error_log_service


def _record(message='boom', **kwargs):
    kwargs.setdefault('source', 'backend')
    return error_log_service.record_error(message=message, **kwargs)


# --------------------------------------------------------------------------- #
# Service: recording + dedup
# --------------------------------------------------------------------------- #

def test_record_creates_entry(app):
    entry, deduplicated = _record(
        message='something broke', exception_type='RuntimeError',
        endpoint='/api/v1/apps', method='GET', context={'k': 'v'})
    assert not deduplicated
    assert entry.id is not None
    assert entry.count == 1
    assert entry.fingerprint
    assert entry.get_context() == {'k': 'v'}
    assert entry.resolved is False


def test_dedup_increments_count(app):
    first, _ = _record(message='same crash', exception_type='ValueError')
    second, deduplicated = _record(message='same crash', exception_type='ValueError')
    assert deduplicated
    assert second.id == first.id
    assert second.count == 2
    assert ErrorLog.query.count() == 1


def test_resolved_error_dedups_no_more(app):
    first, _ = _record(message='fixed crash')
    error_log_service.set_resolved(first.id, True)
    second, deduplicated = _record(message='fixed crash')
    assert not deduplicated
    assert second.id != first.id
    assert ErrorLog.query.count() == 2


def test_record_error_never_raises(app, monkeypatch):
    # Broken query object -> failure is swallowed, session rolled back.
    monkeypatch.setattr(error_log_service.ErrorLog, 'query', None)
    entry, deduplicated = _record(message='still safe')
    assert entry is None and deduplicated is False
    assert db.session  # session usable after rollback


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #

def test_list_filters(client, auth_headers):
    _record(message='backend crash A', endpoint='/api/v1/x')
    _record(message='frontend crash B', source='frontend')
    entry, _ = _record(message='backend crash C resolved')
    error_log_service.set_resolved(entry.id, True)

    res = client.get('/api/v1/error-logs?source=frontend', headers=auth_headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data['total'] == 1
    assert data['items'][0]['message'] == 'frontend crash B'

    res = client.get('/api/v1/error-logs?resolved=true', headers=auth_headers)
    assert res.get_json()['total'] == 1

    res = client.get('/api/v1/error-logs?search=crash+A', headers=auth_headers)
    assert res.get_json()['total'] == 1


def test_list_requires_admin(client, app):
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash
    with app.app_context():
        user = User(email='dev@t.local', username='dev',
                    password_hash=generate_password_hash('x'),
                    role=User.ROLE_DEVELOPER, is_active=True)
        db.session.add(user)
        db.session.commit()
        headers = {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}
    assert client.get('/api/v1/error-logs', headers=headers).status_code == 403


def test_resolve_and_unresolve(client, auth_headers):
    entry, _ = _record(message='to resolve')
    res = client.post(f'/api/v1/error-logs/{entry.id}/resolve',
                      json={'resolved': True}, headers=auth_headers)
    assert res.status_code == 200
    assert res.get_json()['resolved'] is True

    res = client.post(f'/api/v1/error-logs/{entry.id}/resolve',
                      json={'resolved': False}, headers=auth_headers)
    assert res.get_json()['resolved'] is False

    assert client.post('/api/v1/error-logs/9999/resolve', json={'resolved': True},
                       headers=auth_headers).status_code == 404
    assert client.post(f'/api/v1/error-logs/{entry.id}/resolve', json={},
                       headers=auth_headers).status_code == 400


def test_delete(client, auth_headers):
    entry, _ = _record(message='to delete')
    assert client.delete(f'/api/v1/error-logs/{entry.id}',
                         headers=auth_headers).status_code == 200
    assert ErrorLog.query.count() == 0
    assert client.delete(f'/api/v1/error-logs/{entry.id}',
                         headers=auth_headers).status_code == 404


def test_stats(client, auth_headers):
    _record(message='s1')
    _record(message='s2', source='frontend')
    entry, _ = _record(message='s3')
    error_log_service.set_resolved(entry.id, True)

    res = client.get('/api/v1/error-logs/stats', headers=auth_headers)
    assert res.status_code == 200
    stats = res.get_json()
    assert stats['total'] == 3
    assert stats['unresolved'] == 2
    assert stats['last_24h'] == 3
    assert stats['by_source'] == {'backend': 2, 'frontend': 1}


# --------------------------------------------------------------------------- #
# Client ingestion endpoint
# --------------------------------------------------------------------------- #

def test_client_endpoint_requires_message(client):
    res = client.post('/api/v1/error-logs/client', json={})
    assert res.status_code == 400
    res = client.post('/api/v1/error-logs/client', json={'message': 42})
    assert res.status_code == 400


def test_client_endpoint_records_frontend_error(client):
    res = client.post('/api/v1/error-logs/client', json={
        'message': 'TypeError: x is not a function',
        'exception_type': 'TypeError',
        'endpoint': '/apps/123',
        'context': {'component': 'AppList'},
    })
    assert res.status_code == 201
    body = res.get_json()
    assert body['deduplicated'] is False

    entry = ErrorLog.query.get(body['id'])
    assert entry.source == 'frontend'
    assert entry.endpoint == '/apps/123'

    # Same error again dedups.
    res = client.post('/api/v1/error-logs/client', json={
        'message': 'TypeError: x is not a function',
        'exception_type': 'TypeError',
        'endpoint': '/apps/123',
    })
    assert res.get_json()['deduplicated'] is True
    assert entry.count == 2


# --------------------------------------------------------------------------- #
# 500-handler hook
# --------------------------------------------------------------------------- #

@pytest.mark.fresh_app
def test_500_handler_records_error_and_keeps_response(client, app):
    @app.route('/api/v1/__test_boom')
    def _boom():
        raise RuntimeError('kaboom')

    # Flask only routes to the 500 handler when not propagating exceptions.
    app.config['TESTING'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = False

    res = client.get('/api/v1/__test_boom')
    assert res.status_code == 500
    assert res.get_json() == {'error': 'Internal server error'}

    entry = ErrorLog.query.filter_by(source='backend').first()
    assert entry is not None
    assert entry.exception_type == 'RuntimeError'
    assert 'kaboom' in entry.message
    assert 'RuntimeError' in entry.traceback
    assert entry.endpoint == '/api/v1/__test_boom'
    assert entry.method == 'GET'


@pytest.mark.fresh_app
def test_500_from_a_db_error_is_still_recorded(client, app):
    """A crash caused by the database must not be the one crash we cannot log.

    The 500 handler shares the app-context-scoped ``db.session`` with the view
    that just failed. When the failure IS a database error, that session is
    already in a failed transaction, so ``record_error``'s first query raises
    PendingRollbackError -- which its own never-raise contract then swallows,
    silently dropping the report. Rolling back before recording is what makes
    this class of 500 visible in the tracker at all.
    """
    @app.route('/api/v1/__test_db_boom')
    def _db_boom():
        # A REAL failed flush, not a hand-built IntegrityError: only an actual
        # constraint violation leaves the session in the failed-transaction
        # state that makes the next query raise. `message` is NOT NULL.
        db.session.add(ErrorLog(fingerprint='x' * 64, source='backend',
                                level='error', message=None))
        db.session.flush()  # raises IntegrityError, poisoning the session

    app.config['TESTING'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = False

    res = client.get('/api/v1/__test_db_boom')
    assert res.status_code == 500

    entry = ErrorLog.query.filter_by(endpoint='/api/v1/__test_db_boom').first()
    assert entry is not None, 'a DB-caused 500 was not recorded'
    assert entry.exception_type == 'IntegrityError'


@pytest.mark.fresh_app
def test_500_handler_does_not_commit_the_crashed_request_work(client, app):
    """record_error's commit() must not persist what the failing view left pending.

    Without the rollback, the handler's commit flushes any ORM state still
    sitting in the shared session -- so a view that add()s a row and then
    crashes ships a half-applied write.
    """
    from app.models.error_log import ErrorLog as _EL

    @app.route('/api/v1/__test_partial_write')
    def _partial():
        db.session.add(_EL(fingerprint='pending-should-not-persist',
                           source='backend', level='error', message='pending'))
        db.session.flush()
        raise RuntimeError('crash after a pending write')

    app.config['TESTING'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = False

    assert client.get('/api/v1/__test_partial_write').status_code == 500

    assert ErrorLog.query.filter_by(
        fingerprint='pending-should-not-persist').count() == 0
    # ...but the crash itself was still recorded.
    assert ErrorLog.query.filter_by(
        endpoint='/api/v1/__test_partial_write').count() == 1
