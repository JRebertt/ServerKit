"""Tests for the saved table views API (/api/v1/views)."""

import pytest


def _create(client, headers, page='services', name='Running', state=None, is_default=False):
    return client.post('/api/v1/views', headers=headers, json={
        'page': page,
        'name': name,
        'state': state if state is not None else {'filter': 'running'},
        'is_default': is_default,
    })


def test_views_require_auth(client):
    assert client.get('/api/v1/views?page=services').status_code == 401
    assert client.post('/api/v1/views', json={}).status_code == 401


def test_list_requires_page_param(client, auth_headers):
    resp = client.get('/api/v1/views', headers=auth_headers)
    assert resp.status_code == 400


def test_create_and_list_view(client, auth_headers):
    resp = _create(client, auth_headers)
    assert resp.status_code == 201
    view = resp.get_json()
    assert view['name'] == 'Running'
    assert view['page'] == 'services'
    assert view['state'] == {'filter': 'running'}
    assert view['is_default'] is False

    resp = client.get('/api/v1/views?page=services', headers=auth_headers)
    assert resp.status_code == 200
    views = resp.get_json()['views']
    assert len(views) == 1
    assert views[0]['id'] == view['id']

    # A different page does not see the view
    resp = client.get('/api/v1/views?page=domains', headers=auth_headers)
    assert resp.get_json()['views'] == []


def test_create_validates_input(client, auth_headers):
    assert _create(client, auth_headers, page='').status_code == 400
    assert _create(client, auth_headers, name='').status_code == 400
    assert _create(client, auth_headers, state=['not', 'a', 'dict']).status_code == 400


def test_duplicate_name_rejected(client, auth_headers):
    assert _create(client, auth_headers).status_code == 201
    resp = _create(client, auth_headers)
    # ConflictError under the typed-error contract (was a generic 400).
    assert resp.status_code == 409
    assert 'already' in resp.get_json()['error']


def test_only_one_default_per_page(client, auth_headers):
    first = _create(client, auth_headers, name='One', is_default=True).get_json()
    second = _create(client, auth_headers, name='Two', is_default=True).get_json()

    views = client.get('/api/v1/views?page=services', headers=auth_headers).get_json()['views']
    by_id = {v['id']: v for v in views}
    assert by_id[first['id']]['is_default'] is False
    assert by_id[second['id']]['is_default'] is True

    # Un-defaulting leaves no default
    resp = client.put(f"/api/v1/views/{second['id']}", headers=auth_headers,
                      json={'is_default': False})
    assert resp.status_code == 200
    views = client.get('/api/v1/views?page=services', headers=auth_headers).get_json()['views']
    assert all(v['is_default'] is False for v in views)


def test_update_rename_and_state(client, auth_headers):
    view = _create(client, auth_headers).get_json()
    resp = client.put(f"/api/v1/views/{view['id']}", headers=auth_headers,
                      json={'name': 'Renamed', 'state': {'filter': 'stopped'}})
    assert resp.status_code == 200
    updated = resp.get_json()
    assert updated['name'] == 'Renamed'
    assert updated['state'] == {'filter': 'stopped'}


def test_views_are_scoped_to_their_owner(client, app, auth_headers):
    view = _create(client, auth_headers).get_json()

    # A second user must not see, update, or delete the first user's view
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash
    with app.app_context():
        other = User(email='other@test.local', username='other',
                     password_hash=generate_password_hash('pass'),
                     role=User.ROLE_ADMIN, is_active=True)
        db.session.add(other)
        db.session.commit()
        token = create_access_token(identity=other.id)
    other_headers = {'Authorization': f'Bearer {token}'}

    resp = client.get('/api/v1/views?page=services', headers=other_headers)
    assert resp.get_json()['views'] == []
    assert client.put(f"/api/v1/views/{view['id']}", headers=other_headers,
                      json={'name': 'Hijack'}).status_code == 404
    assert client.delete(f"/api/v1/views/{view['id']}", headers=other_headers).status_code == 404


def test_delete_view(client, auth_headers):
    view = _create(client, auth_headers).get_json()
    assert client.delete(f"/api/v1/views/{view['id']}", headers=auth_headers).status_code == 200
    assert client.delete(f"/api/v1/views/{view['id']}", headers=auth_headers).status_code == 404
