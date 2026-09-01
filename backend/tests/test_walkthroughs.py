"""Guided walkthrough progress is validated and strictly self-scoped."""

from factories import headers_for, make_user


def _state(step='open-wizard'):
    return {
        'version': 1,
        'active_id': 'create-service',
        'progress': {
            'create-service': {
                'status': 'active',
                'completed_steps': [step],
                'started_at': '2026-08-21T12:00:00.000Z',
                'updated_at': '2026-08-21T12:01:00.000Z',
                'completed_at': None,
            },
        },
    }


def test_walkthrough_state_round_trip_is_self_scoped(client, db_session):
    first = make_user(db_session, role='viewer', username='guide-one')
    second = make_user(db_session, role='viewer', username='guide-two')

    response = client.put(
        '/api/v1/walkthroughs/state', headers=headers_for(first),
        json={'state': _state()})
    assert response.status_code == 200
    assert response.get_json()['state']['active_id'] == 'create-service'

    response = client.get(
        '/api/v1/walkthroughs/state', headers=headers_for(second))
    assert response.status_code == 200
    assert response.get_json()['state']['progress'] == {}

    response = client.get(
        '/api/v1/walkthroughs/state', headers=headers_for(first))
    assert response.get_json()['state']['progress']['create-service'][
        'completed_steps'] == ['open-wizard']


def test_walkthrough_state_rejects_unbounded_or_unknown_data(client, db_session):
    user = make_user(db_session, role='viewer', username='guide-invalid')
    bad = _state()
    bad['progress']['create-service']['status'] = 'invented'
    response = client.put(
        '/api/v1/walkthroughs/state', headers=headers_for(user),
        json={'state': bad})
    assert response.status_code == 400


def test_walkthrough_state_requires_authentication(client):
    assert client.get('/api/v1/walkthroughs/state').status_code in (401, 422)
    assert client.put('/api/v1/walkthroughs/state', json={}).status_code in (401, 422)


def _definition(guide_id='custom-guide'):
    return {
        'id': guide_id,
        'title': 'Custom guide',
        'description': 'Complete a safe, declarative task.',
        'duration': 'About 3 minutes',
        'secondary': True,
        'permissions': [{'feature': 'applications', 'level': 'write'}],
        'steps': [{
            'id': 'open-services',
            'title': 'Open services',
            'description': 'Navigate to the services list.',
            'action': 'Open services',
            'path': '/services',
            'target': 'services-list',
            'completion': {'type': 'route', 'path': '/services'},
        }],
    }


def test_admin_can_publish_panel_walkthroughs_visible_to_viewers(client, db_session):
    admin = make_user(db_session, role='admin', username='guide-admin')
    viewer = make_user(db_session, role='viewer', username='guide-reader')

    response = client.put(
        '/api/v1/walkthroughs/definitions',
        headers=headers_for(admin),
        json={'definitions': [_definition()]},
    )
    assert response.status_code == 200
    assert response.get_json()['definitions'][0]['id'] == 'custom-guide'

    response = client.get(
        '/api/v1/walkthroughs/definitions',
        headers=headers_for(viewer),
    )
    assert response.status_code == 200
    assert response.get_json()['definitions'][0]['title'] == 'Custom guide'


def test_viewer_cannot_publish_walkthrough_definitions(client, db_session):
    viewer = make_user(db_session, role='viewer', username='guide-publisher')
    response = client.put(
        '/api/v1/walkthroughs/definitions',
        headers=headers_for(viewer),
        json={'definitions': [_definition()]},
    )
    assert response.status_code == 403


def test_walkthrough_definition_rejects_executable_or_arbitrary_targets(client, db_session):
    admin = make_user(db_session, role='admin', username='guide-validator')
    definition = _definition()
    definition['steps'][0]['target'] = '#password-field'
    definition['steps'][0]['javascript'] = 'alert(1)'

    response = client.put(
        '/api/v1/walkthroughs/definitions',
        headers=headers_for(admin),
        json={'definitions': [definition]},
    )
    assert response.status_code == 400
    assert 'data-walkthrough token' in response.get_json()['error']


def test_walkthrough_definitions_require_authentication(client):
    assert client.get('/api/v1/walkthroughs/definitions').status_code in (401, 422)
    assert client.put(
        '/api/v1/walkthroughs/definitions',
        json={'definitions': [_definition()]},
    ).status_code in (401, 422)
