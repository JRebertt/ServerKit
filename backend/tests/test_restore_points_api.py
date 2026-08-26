"""Plan 81 M3: generic restore-point HTTP contracts and authorization."""

from copy import deepcopy

import pytest

from factories import headers_for, make_application, make_server, make_user


class MemoryAdapter:
    coverage = ('Only in-memory test state is covered.',)

    def __init__(self, state=None):
        self.state = deepcopy(state or {})
        self.refusals = []
        self.restore_result = None
        self.restore_calls = []

    def capture(self, scope_id, server_id=None):
        return deepcopy(self.state)

    def diff(self, old, new):
        from app.services.restore_point_service import diff_payloads
        return diff_payloads(old, new)

    def validate_restore(self, scope_id, payload, current_payload,
                         actor=None, server_id=None):
        return list(self.refusals)

    def restore(self, scope_id, payload, actor=None, server_id=None):
        self.restore_calls.append({
            'scope_id': scope_id,
            'actor_id': getattr(actor, 'id', None),
            'server_id': server_id,
        })
        if self.restore_result is not None:
            return deepcopy(self.restore_result)
        self.state = deepcopy(payload)
        return {'success': True, 'scope_id': scope_id}


@pytest.fixture
def memory_surface(monkeypatch):
    from app.services import restore_point_service

    adapter = MemoryAdapter({'mode': 'saved'})
    monkeypatch.setitem(
        restore_point_service.ADAPTERS, 'test_surface', adapter,
    )
    return adapter


def _capture(scope_type, scope_id, state, *, adapter=None, server_id=None):
    from app.services import restore_point_service

    if adapter is not None:
        adapter.state = deepcopy(state)
    point = restore_point_service.capture(
        scope_type, scope_id, 'pre_mutation', server_id=server_id,
    )
    assert point is not None
    return point


def test_route_authentication_boundaries(client, db_session, memory_surface):
    missing = '00000000-0000-0000-0000-000000000000'
    assert client.get('/api/v1/restore-points').status_code == 401
    assert client.post('/api/v1/restore-points', json={}).status_code == 401
    assert client.post(
        f'/api/v1/restore-points/{missing}/preview', json={},
    ).status_code == 401
    assert client.post(
        f'/api/v1/restore-points/{missing}/restore', json={},
    ).status_code == 401

    viewer = make_user(db_session, role='viewer')
    viewer_headers = headers_for(viewer)
    assert client.post(
        '/api/v1/restore-points', headers=viewer_headers,
        json={'scope_type': 'test_surface', 'scope_id': 'one'},
    ).status_code == 403
    assert client.post(
        f'/api/v1/restore-points/{missing}/preview', headers=viewer_headers,
    ).status_code == 403
    assert client.post(
        f'/api/v1/restore-points/{missing}/restore', headers=viewer_headers,
    ).status_code == 403


def test_local_operational_reads_require_developer(
        client, db_session, memory_surface):
    point = _capture('test_surface', 'local', {'mode': 'saved'},
                     adapter=memory_surface)
    viewer = make_user(db_session, role='viewer')
    headers = headers_for(viewer)

    for path in (
        '/api/v1/restore-points?scope_type=test_surface&scope_id=local',
        f'/api/v1/restore-points/{point.id}',
        f'/api/v1/restore-points/{point.id}/diff',
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.get_json()['code'] == 'permission_denied'


def test_list_is_grant_filtered_before_limit_and_detail_includes_payload(
        client, db_session, monkeypatch, memory_surface):
    from app.services import restore_point_service
    from app.services.resource_grant_service import ResourceGrantService

    owner = make_user(db_session, role='developer')
    own_app = make_application(db_session, user_id=owner.id, name='owned')
    foreign_owner = make_user(db_session, role='developer')
    foreign_app = make_application(
        db_session, user_id=foreign_owner.id, name='foreign',
    )
    viewer = make_user(db_session, role='viewer')
    ResourceGrantService.grant(
        viewer.id, 'application', own_app.id, role='viewer',
    )

    env_adapter = MemoryAdapter({'env': {'VISIBLE': {'value': 'yes'}}})
    monkeypatch.setitem(restore_point_service.ADAPTERS, 'env', env_adapter)
    own_point = _capture('env', own_app.id, env_adapter.state,
                         adapter=env_adapter)
    env_adapter.state = {'env': {'HIDDEN': {'value': 'no'}}}
    foreign_point = _capture('env', foreign_app.id, env_adapter.state,
                             adapter=env_adapter)
    _capture('test_surface', 'local', {'mode': 'ops'},
             adapter=memory_surface)

    response = client.get(
        '/api/v1/restore-points?scope_type=env&limit=1',
        headers=headers_for(viewer),
    )
    assert response.status_code == 200
    rows = response.get_json()['restore_points']
    assert [row['id'] for row in rows] == [own_point.id]
    assert 'payload' not in rows[0]

    response = client.get(
        f'/api/v1/restore-points/{own_point.id}',
        headers=headers_for(viewer),
    )
    assert response.status_code == 200
    assert response.get_json()['restore_point']['payload'] == {
        'env': {'VISIBLE': {'value': 'yes'}},
    }

    denied = client.get(
        f'/api/v1/restore-points/{foreign_point.id}',
        headers=headers_for(viewer),
    )
    assert denied.status_code == 403


def test_broad_and_server_lists_union_ops_with_authorized_env_points(
        client, db_session, monkeypatch, memory_surface):
    from app.services import restore_point_service

    developer = make_user(db_session, role='developer')
    server = make_server(db_session)
    own_app = make_application(
        db_session, user_id=developer.id, server_id=server.id,
    )
    foreign_app = make_application(
        db_session, user_id=make_user(db_session).id, server_id=server.id,
        name='foreign',
    )
    env_adapter = MemoryAdapter({'env': {'OWN': {}}})
    monkeypatch.setitem(restore_point_service.ADAPTERS, 'env', env_adapter)
    own = _capture(
        'env', own_app.id, env_adapter.state, adapter=env_adapter,
        server_id=server.id,
    )
    env_adapter.state = {'env': {'FOREIGN': {}}}
    foreign = _capture(
        'env', foreign_app.id, env_adapter.state, adapter=env_adapter,
        server_id=server.id,
    )
    memory_surface.state = {'ops': True}
    operational = _capture(
        'test_surface', 'local', memory_surface.state,
        adapter=memory_surface, server_id=server.id,
    )

    headers = headers_for(developer)
    broad = client.get('/api/v1/restore-points', headers=headers)
    assert broad.status_code == 200
    assert {row['id'] for row in broad.get_json()['restore_points']} == {
        own.id, operational.id,
    }

    server_list = client.get(
        f'/api/v1/restore-points?server_id={server.id}', headers=headers,
    )
    assert server_list.status_code == 200
    ids = {row['id'] for row in server_list.get_json()['restore_points']}
    assert ids == {own.id, operational.id}
    assert foreign.id not in ids


def test_manual_env_quicksave_derives_server_and_rejects_client_stamp(
        client, db_session):
    from app.models import RestorePoint

    developer = make_user(db_session, role='developer')
    server = make_server(db_session)
    application = make_application(
        db_session, user_id=developer.id, server_id=server.id,
    )
    headers = headers_for(developer)

    response = client.post(
        '/api/v1/restore-points', headers=headers,
        json={
            'scope_type': 'env', 'scope_id': str(application.id),
            'label': 'before launch',
        },
    )
    assert response.status_code == 201
    data = response.get_json()['restore_point']
    assert data['server_id'] == server.id
    assert data['trigger'] == 'manual'
    assert data['label'] == 'before launch'
    assert data['keep'] is True
    assert data['actor_user_id'] == developer.id
    assert data['payload'] == {'env': {}}
    assert RestorePoint.query.get(data['id']).server_id == server.id

    stamped = client.post(
        '/api/v1/restore-points', headers=headers,
        json={
            'scope_type': 'env', 'scope_id': str(application.id),
            'server_id': '00000000-0000-0000-0000-000000000000',
        },
    )
    assert stamped.status_code == 400
    assert stamped.get_json()['details']['fields'] == ['server_id']


def test_manual_capture_validation_and_failure_are_typed(
        client, db_session, monkeypatch, memory_surface):
    from app.services import restore_point_service

    developer = make_user(db_session, role='developer')
    application = make_application(db_session, user_id=developer.id)
    headers = headers_for(developer)

    unsupported = client.post(
        '/api/v1/restore-points', headers=headers,
        json={'scope_type': 'application', 'scope_id': str(application.id)},
    )
    assert unsupported.status_code == 400
    assert unsupported.get_json()['code'] == 'restore_point_invalid'

    too_long = client.post(
        '/api/v1/restore-points', headers=headers,
        json={
            'scope_type': 'test_surface', 'scope_id': 'local',
            'label': 'x' * 256,
        },
    )
    assert too_long.status_code == 400
    assert too_long.get_json()['code'] == 'validation_error'

    monkeypatch.setattr(restore_point_service, 'capture', lambda *_a, **_k: None)
    failed = client.post(
        '/api/v1/restore-points', headers=headers,
        json={'scope_type': 'test_surface', 'scope_id': 'local'},
    )
    assert failed.status_code == 503
    assert failed.get_json()['code'] == 'restore_point_adapter_unavailable'


def test_diff_contract_default_explicit_and_cross_scope_error(
        client, db_session, memory_surface):
    developer = make_user(db_session, role='developer')
    headers = headers_for(developer)
    first = _capture('test_surface', 'one', {'mode': 'one'},
                     adapter=memory_surface)
    second = _capture('test_surface', 'one', {'mode': 'two'},
                      adapter=memory_surface)
    other = _capture('test_surface', 'other', {'mode': 'other'},
                     adapter=memory_surface)

    response = client.get(
        f'/api/v1/restore-points/{second.id}/diff', headers=headers,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['against_point_id'] == first.id
    assert body['has_changes'] is True
    assert body['diff']['changed']['mode'] == {'old': 'one', 'new': 'two'}

    explicit = client.get(
        f'/api/v1/restore-points/{second.id}/diff?against={first.id}',
        headers=headers,
    )
    assert explicit.status_code == 200
    assert explicit.get_json()['against_point_id'] == first.id

    crossed = client.get(
        f'/api/v1/restore-points/{second.id}/diff?against={other.id}',
        headers=headers,
    )
    assert crossed.status_code == 400
    assert crossed.get_json()['code'] == 'restore_point_invalid'

    unknown = client.get(
        f'/api/v1/restore-points/{second.id}/diff?typo=true',
        headers=headers,
    )
    assert unknown.status_code == 400
    assert unknown.get_json()['details']['fields'] == ['typo']


def test_preview_and_restore_lifecycle_contract(
        client, db_session, memory_surface):
    from app.models import RestorePoint

    developer = make_user(db_session, role='developer')
    point = _capture('test_surface', 'local', {'mode': 'saved'},
                     adapter=memory_surface)
    memory_surface.state = {'mode': 'drifted'}
    headers = headers_for(developer)

    preview = client.post(
        f'/api/v1/restore-points/{point.id}/preview', headers=headers,
    )
    assert preview.status_code == 200
    body = preview.get_json()
    assert body['point_id'] == point.id
    assert body['has_changes'] is True
    assert body['can_restore'] is True
    assert body['refusals'] == []
    assert 'Only in-memory test state is covered.' in body['outside_checkpoint']

    count_before = RestorePoint.query.count()
    restored = client.post(
        f'/api/v1/restore-points/{point.id}/restore', headers=headers,
    )
    assert restored.status_code == 200
    assert restored.get_json() == {'success': True, 'scope_id': 'local'}
    assert memory_surface.state == {'mode': 'saved'}
    assert memory_surface.restore_calls[-1]['actor_id'] == developer.id
    assert RestorePoint.query.count() == count_before + 1


def test_restore_refusal_and_adapter_failure_use_typed_errors(
        client, db_session, memory_surface):
    developer = make_user(db_session, role='developer')
    headers = headers_for(developer)
    point = _capture('test_surface', 'local', {'mode': 'saved'},
                     adapter=memory_surface)
    memory_surface.state = {'mode': 'drifted'}
    memory_surface.refusals = ['Safety admission would be lost.']

    preview = client.post(
        f'/api/v1/restore-points/{point.id}/preview', headers=headers,
    )
    assert preview.status_code == 200
    assert preview.get_json()['can_restore'] is False

    refused = client.post(
        f'/api/v1/restore-points/{point.id}/restore', headers=headers,
    )
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'restore_point_refused'

    memory_surface.refusals = []
    memory_surface.restore_result = {
        'success': False, 'error': 'host write failed', 'rolled_back': True,
    }
    failed = client.post(
        f'/api/v1/restore-points/{point.id}/restore', headers=headers,
    )
    assert failed.status_code == 503
    body = failed.get_json()
    assert body['code'] == 'restore_point_adapter_unavailable'
    assert body['details']['rolled_back'] is True


def test_env_grants_split_read_and_write(
        client, db_session, monkeypatch):
    from app.services import restore_point_service
    from app.services.resource_grant_service import ResourceGrantService

    owner = make_user(db_session, role='developer')
    application = make_application(db_session, user_id=owner.id)
    viewer = make_user(db_session, role='viewer')
    editor = make_user(db_session, role='developer')
    foreign = make_user(db_session, role='developer')
    ResourceGrantService.grant(
        viewer.id, 'application', application.id, role='viewer',
    )
    ResourceGrantService.grant(
        editor.id, 'application', application.id, role='editor',
    )
    adapter = MemoryAdapter({'env': {'KEY': {'value': 'saved'}}})
    monkeypatch.setitem(restore_point_service.ADAPTERS, 'env', adapter)
    point = _capture('env', application.id, adapter.state, adapter=adapter)
    adapter.state = {'env': {'KEY': {'value': 'drifted'}}}

    assert client.get(
        f'/api/v1/restore-points/{point.id}', headers=headers_for(viewer),
    ).status_code == 200
    assert client.get(
        f'/api/v1/restore-points/{point.id}', headers=headers_for(foreign),
    ).status_code == 403
    assert client.post(
        f'/api/v1/restore-points/{point.id}/preview',
        headers=headers_for(viewer),
    ).status_code == 403
    assert client.post(
        f'/api/v1/restore-points/{point.id}/preview',
        headers=headers_for(foreign),
    ).status_code == 403
    assert client.post(
        f'/api/v1/restore-points/{point.id}/preview',
        headers=headers_for(editor),
    ).status_code == 200


def test_deleted_and_inactive_jwt_users_fail_closed_on_get(
        app, client, db_session, memory_surface):
    from app import db

    point = _capture('test_surface', 'local', {'mode': 'saved'},
                     adapter=memory_surface)
    inactive = make_user(db_session, role='developer')
    inactive_headers = headers_for(inactive)
    inactive.is_active = False
    db.session.commit()

    response = client.get(
        f'/api/v1/restore-points/{point.id}', headers=inactive_headers,
    )
    assert response.status_code == 403
    assert response.get_json()['error'] == 'Account is deactivated'

    deleted = make_user(db_session, role='developer')
    deleted_headers = headers_for(deleted)
    db.session.delete(deleted)
    db.session.commit()
    response = client.get(
        f'/api/v1/restore-points/{point.id}', headers=deleted_headers,
    )
    assert response.status_code == 403
    assert response.get_json()['error'] == 'Authenticated user not found'


def test_developer_api_key_reaches_policy_guarded_post(
        client, db_session):
    from app.services.api_key_service import ApiKeyService

    developer = make_user(db_session, role='developer')
    _, raw_key = ApiKeyService.create_key(
        developer.id, name='restore-point-m3', scopes=['*'],
    )
    missing = '00000000-0000-0000-0000-000000000000'
    response = client.post(
        f'/api/v1/restore-points/{missing}/preview',
        headers={'X-API-Key': raw_key},
    )
    assert response.status_code == 404
    assert response.get_json()['code'] == 'restore_point_not_found'


def test_env_auto_capture_carries_application_server_id(
        app, db_session, monkeypatch):
    from app.models import RestorePoint
    from app.services import restore_point_adapter_env, restore_point_service
    from app.services.env_service import EnvService

    owner = make_user(db_session, role='developer')
    server = make_server(db_session)
    application = make_application(
        db_session, user_id=owner.id, server_id=server.id,
    )
    monkeypatch.setitem(
        restore_point_service.ADAPTERS, 'env', restore_point_adapter_env,
    )

    EnvService.set_env_var(
        application.id, 'FEATURE', 'on', user_id=owner.id,
    )

    point = RestorePoint.query.filter_by(
        scope_type='env', scope_id=str(application.id),
    ).one()
    assert point.server_id == server.id
