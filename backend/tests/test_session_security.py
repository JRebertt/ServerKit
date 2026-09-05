"""Regression coverage for cross-authentication credential and revocation chains."""
from datetime import timedelta

import pyotp
import pytest
from flask_jwt_extended import create_access_token, decode_token

from factories import make_user, headers_for
from app.services.api_key_service import ApiKeyService


@pytest.fixture(autouse=True)
def _isolated_throttles(app):
    from app import limiter
    limiter.reset()
    yield
    limiter.reset()


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


def _login(client, user):
    response = client.post('/api/v1/auth/login', json={
        'email': user.email, 'password': 'password123',
    })
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _refresh(client, token):
    return client.post('/api/v1/auth/refresh', headers=_headers(token))


def test_pending_mfa_cannot_mint_link_and_has_five_minute_expiry(client, db_session):
    user = make_user(db_session, role='admin', password='password123',
                     totp_enabled=True, totp_secret=pyotp.random_base32())
    pending = _login(client, user)
    claims = decode_token(pending['temp_token'])
    assert 0 < claims['exp'] - claims['iat'] <= 300
    for path in ('/api/v1/auth/login-links', '/api/v1/auth/logout'):
        response = client.post(path, headers=_headers(pending['temp_token']), json={})
        assert response.status_code in (401, 403)
    assert client.get('/api/v1/auth/me', headers=_headers(pending['temp_token'])).status_code == 401

    verified = client.post('/api/v1/auth/2fa/verify', json={
        'temp_token': pending['temp_token'], 'code': pyotp.TOTP(user.totp_secret).now(),
    })
    assert verified.status_code == 200
    assert client.get('/api/v1/auth/me', headers=_headers(verified.json['access_token'])).status_code == 200


@pytest.mark.parametrize('scopes', [['apps:read'], ['*']])
def test_api_keys_cannot_mint_browser_sessions(client, db_session, scopes):
    user = make_user(db_session, role='admin')
    _, raw_key = ApiKeyService.create_key(user.id, name='session-probe', scopes=scopes)
    # Even combining a valid JWT with a key must not silently ignore the key.
    for headers in ({'X-API-Key': raw_key}, {**headers_for(user), 'X-API-Key': raw_key}):
        response = client.post('/api/v1/auth/login-links', json={}, headers=headers)
        assert response.status_code == 403


def test_login_link_redemption_respects_target_mfa(client, db_session):
    admin = make_user(db_session, role='admin')
    target = make_user(db_session, totp_enabled=True, totp_secret=pyotp.random_base32())
    created = client.post('/api/v1/auth/login-links', headers=headers_for(admin),
                          json={'user_id': target.id})
    assert created.status_code == 201
    redeemed = client.post('/api/v1/auth/login-links/redeem', json={'token': created.json['token']})
    assert redeemed.status_code == 200
    assert redeemed.json['requires_2fa'] is True
    assert 'access_token' not in redeemed.json and 'refresh_token' not in redeemed.json
    result = client.post('/api/v1/auth/2fa/verify', json={
        'temp_token': redeemed.json['temp_token'], 'code': pyotp.TOTP(target.totp_secret).now(),
    })
    assert result.status_code == 200 and result.json['user']['id'] == target.id


def test_password_change_requires_current_password_and_revokes_previous_tokens(client, db_session):
    user = make_user(db_session, password='password123')
    original = _login(client, user)
    headers = _headers(original['access_token'])
    for body in ({'password': 'replacement123'},
                 {'password': 'replacement123', 'current_password': 'incorrect'}):
        assert client.put('/api/v1/auth/me', headers=headers, json=body).status_code == 403
    updated = client.put('/api/v1/auth/me', headers=headers, json={
        'password': 'replacement123', 'current_password': 'password123',
    })
    assert updated.status_code == 200
    assert _refresh(client, original['refresh_token']).status_code == 401
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401
    assert client.get('/api/v1/auth/me', headers=_headers(updated.json['access_token'])).status_code == 200
    assert _refresh(client, updated.json['refresh_token']).status_code == 200


def test_disable_reenable_and_admin_password_reset_revoke_existing_tokens(client, db_session):
    user = make_user(db_session, password='password123')
    tokens = _login(client, user)
    user.is_active = False
    db_session.session.commit()
    assert client.get('/api/v1/auth/me', headers=_headers(tokens['access_token'])).status_code == 401
    user.is_active = True
    db_session.session.commit()
    assert _refresh(client, tokens['refresh_token']).status_code == 401
    fresh = _login(client, user)
    admin = make_user(db_session, role='admin')
    response = client.put(f'/api/v1/admin/users/{user.id}', headers=headers_for(admin),
                          json={'password': 'adminreset123'})
    assert response.status_code == 200
    assert _refresh(client, fresh['refresh_token']).status_code == 401


def test_logout_revokes_entire_browser_family_but_preserves_other_browser(client, db_session):
    user = make_user(db_session, role='viewer', password='password123')
    first = _login(client, user)
    second = _login(client, user)
    refreshed = _refresh(client, first['refresh_token'])
    assert refreshed.status_code == 200
    assert decode_token(first['access_token'])['session_id'] == decode_token(first['refresh_token'])['session_id']
    assert client.post('/api/v1/auth/logout', headers=_headers(first['access_token'])).status_code == 200
    for token in (first['access_token'], refreshed.json['access_token']):
        assert client.get('/api/v1/auth/me', headers=_headers(token)).status_code == 401
    assert _refresh(client, first['refresh_token']).status_code == 401
    assert client.get('/api/v1/auth/me', headers=_headers(second['access_token'])).status_code == 200
    assert _refresh(client, second['refresh_token']).status_code == 200


@pytest.mark.parametrize('change', ['disable', 'password'])
def test_revoked_pending_mfa_cannot_finish_login(client, db_session, change):
    user = make_user(db_session, password='password123', totp_enabled=True,
                     totp_secret=pyotp.random_base32())
    pending = _login(client, user)
    if change == 'disable':
        user.is_active = False
    else:
        user.set_password('resetpassword123')
    db_session.session.commit()
    response = client.post('/api/v1/auth/2fa/verify', json={
        'temp_token': pending['temp_token'], 'code': pyotp.TOTP(user.totp_secret).now(),
    })
    assert response.status_code == 401


def test_unexpired_legacy_or_expired_mfa_tokens_are_rejected(client, db_session):
    user = make_user(db_session, totp_enabled=True, totp_secret=pyotp.random_base32())
    legacy = create_access_token(identity=user.id, additional_claims={'auth_version': None})
    assert client.get('/api/v1/auth/me', headers=_headers(legacy)).status_code == 401
    for expiration in (False, timedelta(seconds=-1)):
        pending = create_access_token(identity=user.id, additional_claims={'2fa_pending': True},
                                       expires_delta=expiration)
        response = client.post('/api/v1/auth/2fa/verify', json={
            'temp_token': pending, 'code': pyotp.TOTP(user.totp_secret).now(),
        })
        assert response.status_code == 401


def test_password_reset_invalidates_outstanding_login_links(client, db_session):
    admin = make_user(db_session, role='admin')
    target = make_user(db_session)
    created = client.post('/api/v1/auth/login-links', headers=headers_for(admin),
                          json={'user_id': target.id})
    assert created.status_code == 201
    target.set_password('resetpassword123')
    db_session.session.commit()
    assert client.post('/api/v1/auth/login-links/redeem',
                       json={'token': created.json['token']}).status_code == 401


def test_sso_tokens_share_session_and_pending_tokens_expire(app, db_session):
    from app.api.sso import _complete_sso_login
    user = make_user(db_session, auth_provider='oidc', password_hash=None)
    with app.test_request_context('/api/v1/sso/callback/oidc'):
        response, status = _complete_sso_login(user, 'oidc', False)
        assert status == 200
        pair = response.get_json()
        assert decode_token(pair['access_token'])['session_id'] == decode_token(pair['refresh_token'])['session_id']
        user.totp_enabled = True
        db_session.session.commit()
        response, status = _complete_sso_login(user, 'oidc', False)
        assert status == 200
        claims = decode_token(response.get_json()['temp_token'])
        assert claims['2fa_pending'] is True
        assert 0 < claims['exp'] - claims['iat'] <= 300


def test_refresh_cannot_renew_recent_authentication(client, db_session):
    import time
    from flask_jwt_extended import create_refresh_token
    user = make_user(db_session, auth_provider='oidc', password_hash=None)
    stale_auth = int(time.time()) - 600
    refresh_token = create_refresh_token(identity=user.id, additional_claims={'auth_time': stale_auth})
    refreshed = _refresh(client, refresh_token)
    assert refreshed.status_code == 200
    token = refreshed.json['access_token']
    assert decode_token(token)['auth_time'] == stale_auth
    assert client.put('/api/v1/auth/me', headers=_headers(token),
                      json={'password': 'replacement123'}).status_code == 403


def test_session_migration_upgrades_existing_users_and_is_repeatable(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[1] / 'migrations/versions/097_user_auth_version.py'
    spec = importlib.util.spec_from_file_location('session_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite:///' + (tmp_path / 'previous.db').as_posix())
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)')
        connection.exec_driver_sql("INSERT INTO users VALUES (1, 'existing')")
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert connection.exec_driver_sql('SELECT username, auth_version FROM users').one() == ('existing', '0')
        assert 'revoked_sessions' in sa.inspect(connection).get_table_names()
        migration.downgrade()
        assert 'auth_version' not in {c['name'] for c in sa.inspect(connection).get_columns('users')}
    engine.dispose()


def test_revocation_rows_cascade_on_user_deletion(db_session):
    from app.models import RevokedSession
    user = make_user(db_session)
    db_session.session.add(RevokedSession(session_id='a' * 32, user_id=user.id))
    db_session.session.commit()
    assert RevokedSession.query.filter_by(user_id=user.id).count() == 1
    connection = db_session.session.connection()
    connection.exec_driver_sql('PRAGMA foreign_keys=ON')
    assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
    try:
        db_session.session.delete(user)
        db_session.session.commit()
        assert RevokedSession.query.count() == 0
    finally:
        db_session.session.rollback()
        db_session.session.connection().exec_driver_sql('PRAGMA foreign_keys=OFF')
