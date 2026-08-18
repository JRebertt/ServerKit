"""Event-subscription use-case and HTTP-boundary tests."""

import ast
from pathlib import Path

from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash


def _developer_headers(db, username):
    from app.models import User

    user = User(
        email=f'{username}@test.local',
        username=username,
        password_hash=generate_password_hash('testpass'),
        role=User.ROLE_DEVELOPER,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user, {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


def _create(client, headers, name='Deploy hook'):
    return client.post('/api/v1/event-subscriptions/', headers=headers, json={
        'name': name,
        'url': 'https://hooks.example.test/serverkit',
        'events': ['app.deployed'],
        'generate_secret': True,
    })


def test_subscription_crud_uses_typed_boundary(client, auth_headers):
    created_response = _create(client, auth_headers)
    assert created_response.status_code == 201
    created = created_response.get_json()
    assert created['name'] == 'Deploy hook'
    assert created['secret'].startswith('whsec_')

    listed = client.get(
        '/api/v1/event-subscriptions/', headers=auth_headers
    ).get_json()['subscriptions']
    assert [item['id'] for item in listed] == [created['id']]
    assert 'secret' not in listed[0]

    updated_response = client.put(
        f"/api/v1/event-subscriptions/{created['id']}",
        headers=auth_headers,
        json={'name': 'Release hook', 'retry_count': 5},
    )
    assert updated_response.status_code == 200
    assert updated_response.get_json()['name'] == 'Release hook'
    assert updated_response.get_json()['retry_count'] == 5

    deleted = client.delete(
        f"/api/v1/event-subscriptions/{created['id']}", headers=auth_headers
    )
    assert deleted.status_code == 200

    missing = client.get(
        f"/api/v1/event-subscriptions/{created['id']}", headers=auth_headers
    )
    assert missing.status_code == 404
    assert missing.get_json()['code'] == 'event_subscription_not_found'


def test_subscription_schema_rejects_unknown_and_invalid_fields(
    client, auth_headers,
):
    response = client.post(
        '/api/v1/event-subscriptions/',
        headers={**auth_headers, 'X-Request-ID': 'subscription-contract'},
        json={
            'name': 'Hook',
            'url': 'https://hooks.example.test/serverkit',
            'events': [],
            'surprise': True,
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload['code'] == 'invalid_body'
    assert payload['request_id'] == 'subscription-contract'
    assert set(payload['details']['fields']) == {'events', 'surprise'}


def test_non_owner_cannot_read_or_mutate_subscription(client, app):
    from app import db

    owner, owner_headers = _developer_headers(db, 'hook_owner')
    _other, other_headers = _developer_headers(db, 'hook_other')
    created = _create(client, owner_headers, name='Private hook').get_json()

    for method, path, kwargs in (
        ('get', f"/api/v1/event-subscriptions/{created['id']}", {}),
        ('put', f"/api/v1/event-subscriptions/{created['id']}", {
            'json': {'name': 'Stolen'},
        }),
        ('delete', f"/api/v1/event-subscriptions/{created['id']}", {}),
    ):
        response = getattr(client, method)(path, headers=other_headers, **kwargs)
        assert response.status_code == 403
        assert response.get_json()['code'] == 'permission_denied'

    listed = client.get(
        '/api/v1/event-subscriptions/', headers=other_headers
    ).get_json()['subscriptions']
    assert listed == []
    assert owner.id == created['user_id']


def test_retry_commits_pending_state_before_enqueue(
    client, auth_headers, monkeypatch,
):
    from app import db
    from app.models.event_subscription import EventDelivery
    from app.services import event_service

    subscription = _create(client, auth_headers).get_json()
    delivery = EventDelivery(
        subscription_id=subscription['id'],
        event_type='app.deployed',
        status=EventDelivery.STATUS_FAILED,
        next_retry_at=None,
    )
    db.session.add(delivery)
    db.session.commit()

    observed = []

    def capture(delivery_id):
        row = db.session.get(EventDelivery, delivery_id)
        observed.append((row.id, row.status))

    monkeypatch.setattr(event_service, 'enqueue_webhook_delivery', capture)
    response = client.post(
        f"/api/v1/event-subscriptions/{subscription['id']}"
        f'/deliveries/{delivery.id}/retry',
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.get_json()['status'] == EventDelivery.STATUS_PENDING
    assert observed == [(delivery.id, EventDelivery.STATUS_PENDING)]


def test_event_subscription_routes_do_not_own_persistence():
    path = (
        Path(__file__).resolve().parents[1]
        / 'app' / 'api' / 'event_subscriptions.py'
    )
    tree = ast.parse(path.read_text(encoding='utf-8'))

    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    session_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == 'session'
    ]

    assert 'EventSubscription' not in imported_names
    assert 'EventDelivery' not in imported_names
    assert session_calls == []
