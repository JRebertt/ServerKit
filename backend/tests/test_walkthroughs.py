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
