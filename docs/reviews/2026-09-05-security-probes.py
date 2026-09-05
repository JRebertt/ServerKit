"""Review evidence: assertions describe observed defects, not desired policy.

To reproduce against this checkout, copy this file temporarily into backend/tests/
as test_review_20260905_probe.py and run it with that directory's pytest fixtures.
Remove the temporary copy afterward. These assertions must not become permanent
security tests: remediation tests should instead assert that the attempts fail.
Only synthetic users, database records and socket events are used; no AI provider
or production service is called.
"""
from flask_jwt_extended import create_refresh_token, decode_token
from factories import make_user, headers_for, make_application


def test_review_pending_mfa_can_mint_full_login(client, db_session):
    user = make_user(db_session, role='admin', password='ReviewPassword123!', totp_enabled=True)
    login = client.post('/api/v1/auth/login', json={'email': user.email, 'password': 'ReviewPassword123!'})
    assert login.status_code == 200, login.get_json()
    pending = login.get_json()['temp_token']
    assert 'exp' not in decode_token(pending)
    headers = {'Authorization': f'Bearer {pending}'}
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 403
    minted = client.post('/api/v1/auth/login-links', headers=headers, json={})
    assert minted.status_code == 201, minted.get_json()
    redeemed = client.post('/api/v1/auth/login-links/redeem', json={'token': minted.get_json()['token']})
    assert redeemed.status_code == 200, redeemed.get_json()
    full = redeemed.get_json()['access_token']
    assert not decode_token(full).get('2fa_pending')
    assert client.get('/api/v1/admin/users', headers={'Authorization': f'Bearer {full}'}).status_code == 200


def test_review_read_scoped_key_can_mint_full_login(client, db_session):
    from app.services.api_key_service import ApiKeyService
    user = make_user(db_session, role='admin')
    key, raw = ApiKeyService.create_key(user.id, 'review-read-only', scopes=['apps:read'])
    assert not key.has_scope('write')
    minted = client.post('/api/v1/auth/login-links', headers={'X-API-Key': raw}, json={})
    assert minted.status_code == 201, minted.get_json()
    redeemed = client.post('/api/v1/auth/login-links/redeem', json={'token': minted.get_json()['token']})
    assert redeemed.status_code == 200, redeemed.get_json()
    assert 'refresh_token' in redeemed.get_json()


def test_review_ai_lists_foreign_application(client, db_session):
    from app.services.ai_tool_registry import ToolDescriptor
    from app.services.ai_tools_builtin import list_applications
    from app.services.ai_service import _make_read_wrapper
    viewer = make_user(db_session, role='viewer')
    foreign = make_application(db_session, name='private-review-app')
    assert client.get(f'/api/v1/apps/{foreign.id}', headers=headers_for(viewer)).status_code == 403
    descriptor = ToolDescriptor(name='list_applications', qualified_name='core__list_applications',
        func=list_applications, description='review', parameters={}, rbac_feature='applications')
    result = _make_read_wrapper(descriptor, viewer)()
    assert foreign.id in [row['id'] for row in result]


def test_review_disabled_user_keeps_jwt_access(client, db_session):
    user = make_user(db_session)
    foreign = make_application(db_session, user_id=user.id)
    headers = headers_for(user)
    user.is_active = False
    db_session.session.commit()
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 200
    assert client.get(f'/api/v1/apps/{foreign.id}', headers=headers).status_code == 200


def test_review_password_change_needs_no_old_password_and_keeps_refresh(client, db_session):
    user = make_user(db_session, password='OldReviewPassword123!')
    headers = headers_for(user)
    refresh = create_refresh_token(identity=user.id)
    result = client.put('/api/v1/auth/me', headers=headers, json={'password': 'NewReviewPassword456!'})
    assert result.status_code == 200, result.get_json()
    assert user.check_password('NewReviewPassword456!')
    renewed = client.post('/api/v1/auth/refresh', headers={'Authorization': f'Bearer {refresh}'})
    assert renewed.status_code == 200, renewed.get_json()


def test_review_structured_ai_results_skip_redaction(monkeypatch):
    from app.services import ai_service
    monkeypatch.setattr(ai_service, '_pii_enabled', lambda: True)
    class Redactor:
        def redact(self, text):
            raise AssertionError('Structured output never reaches redactor')
    monkeypatch.setattr(ai_service, '_get_pii_redactor', lambda: Redactor())
    payload = {'email': 'review-person@example.test', 'nested': [{'password': 'synthetic-review-secret'}]}
    assert ai_service._maybe_redact_result(payload) == payload


def test_review_socket_accepts_pending_mfa_and_refresh(app, db_session):
    from flask_jwt_extended import create_access_token
    from app.sockets import socketio
    user = make_user(db_session, role='admin', totp_enabled=True)
    pending = create_access_token(identity=user.id, additional_claims={'2fa_pending': True})
    for token in (pending, create_refresh_token(identity=user.id)):
        sock = socketio.test_client(app, auth={'token': token})
        try:
            assert sock.is_connected()
        finally:
            if sock.is_connected():
                sock.disconnect()


def test_review_viewer_can_join_other_users_socket_room(app, db_session):
    from flask_jwt_extended import create_access_token
    from app.sockets import socketio
    viewer = make_user(db_session, role='viewer')
    other = make_user(db_session, role='admin')
    sock = socketio.test_client(app, auth={'token': create_access_token(identity=viewer.id)})
    try:
        assert sock.is_connected()
        sock.get_received()
        sock.emit('join_room', {'room': f'user_{other.id}'})
        socketio.emit('review_synthetic_private_event', {'marker': 'private-test-only'}, to=f'user_{other.id}')
        events = sock.get_received()
        assert any(event['name'] == 'review_synthetic_private_event' for event in events), events
    finally:
        if sock.is_connected():
            sock.disconnect()
