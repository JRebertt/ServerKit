"""Dashboard board persistence tests (plan 62).

Proves the backend contract behind the widget grid: shipped defaults are seeded
once per user, boards are CRUD-able, a default board can be restored, one user
can never see or touch another's board (404, never 403), and a malformed widget
payload is refused before it reaches the database.
"""
import pytest

from app.services.dashboard_service import DEFAULT_BOARDS, GRID_COLS


def _headers_for(app, username):
    """A second (non-admin) user's auth headers — the neighbour whose boards
    must stay invisible."""
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    with app.app_context():
        user = User(
            email=f'{username}@test.local', username=username,
            password_hash=generate_password_hash('x'),
            role=User.ROLE_DEVELOPER, is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


@pytest.fixture
def other_headers(app):
    return _headers_for(app, 'boardneighbour')


def _widget(i='w1', wtype='stat', x=0, y=0, w=3, h=2, cfg=None):
    return {'i': i, 'type': wtype, 'x': x, 'y': y, 'w': w, 'h': h, 'cfg': cfg or {}}


# ---------------------------------------------------------------- auth gate

def test_boards_require_auth(client):
    assert client.get('/api/v1/dashboards').status_code == 401


# ------------------------------------------------------------- seed defaults

def test_first_get_seeds_shipped_defaults(client, auth_headers):
    resp = client.get('/api/v1/dashboards', headers=auth_headers)
    assert resp.status_code == 200
    boards = resp.get_json()['boards']

    assert [b['slug'] for b in boards] == ['overview', 'infra', 'apps']
    assert [b['position'] for b in boards] == [0, 1, 2]
    assert [b['icon'] for b in boards] == ['grid', 'server', 'rocket']
    assert all(b['widgets'] for b in boards)

    overview = boards[0]
    types = [w['type'] for w in overview['widgets']]
    assert types.count('stat') == 4
    assert {'timeseries', 'actions', 'specs', 'table', 'feed'}.issubset(set(types))
    table = next(w for w in overview['widgets'] if w['type'] == 'table')
    assert table['cfg']['source'] == 'apps'


def test_defaults_are_seeded_only_once(client, auth_headers):
    first = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    second = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    assert [b['id'] for b in first] == [b['id'] for b in second]
    assert len(second) == len(DEFAULT_BOARDS)


def test_default_layouts_obey_the_grid_rules():
    """12 columns, no overlaps, gravity-up — the same invariants the frontend
    grid enforces at runtime."""
    for spec in DEFAULT_BOARDS:
        widgets = spec['widgets']
        assert len({w['i'] for w in widgets}) == len(widgets), spec['slug']

        cells = {}
        for w in widgets:
            assert w['x'] >= 0 and w['y'] >= 0, (spec['slug'], w['i'])
            assert w['w'] >= 1 and w['h'] >= 1, (spec['slug'], w['i'])
            assert w['x'] + w['w'] <= GRID_COLS, (spec['slug'], w['i'])
            for col in range(w['x'], w['x'] + w['w']):
                for row in range(w['y'], w['y'] + w['h']):
                    assert (col, row) not in cells, (
                        f"{spec['slug']}: {w['i']} overlaps {cells.get((col, row))}")
                    cells[(col, row)] = w['i']

        # Gravity-up: nothing may float. A widget below row 0 must be blocked
        # by something directly above it.
        for w in widgets:
            if w['y'] == 0:
                continue
            blocked = any((col, w['y'] - 1) in cells
                          for col in range(w['x'], w['x'] + w['w']))
            assert blocked, f"{spec['slug']}: {w['i']} floats above a hole"


# --------------------------------------------------------------------- CRUD

def test_create_board(client, auth_headers):
    client.get('/api/v1/dashboards', headers=auth_headers)  # seed the defaults
    resp = client.post('/api/v1/dashboards', headers=auth_headers, json={
        'name': 'Night shift', 'icon': 'zap',
        'widgets': [_widget(wtype='gauge', w=3, h=3)],
    })
    assert resp.status_code == 201, resp.get_json()
    board = resp.get_json()
    assert board['name'] == 'Night shift'
    assert board['icon'] == 'zap'
    assert board['slug'] is None
    assert len(board['widgets']) == 1

    listing = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    assert len(listing) == len(DEFAULT_BOARDS) + 1
    # Created boards land after the seeded defaults.
    assert listing[-1]['id'] == board['id']


def test_create_board_requires_a_name(client, auth_headers):
    resp = client.post('/api/v1/dashboards', headers=auth_headers, json={'icon': 'zap'})
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_update_board_stores_layout(client, auth_headers):
    boards = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    board_id = boards[0]['id']

    layout = [_widget('a', 'stat', 0, 0, 4, 2), _widget('b', 'logs', 4, 0, 8, 4)]
    resp = client.put(f'/api/v1/dashboards/{board_id}', headers=auth_headers,
                      json={'name': 'Renamed', 'icon': 'cpu', 'widgets': layout})
    assert resp.status_code == 200, resp.get_json()
    updated = resp.get_json()
    assert updated['name'] == 'Renamed'
    assert updated['icon'] == 'cpu'
    assert [w['i'] for w in updated['widgets']] == ['a', 'b']

    reread = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    assert reread[0]['widgets'][1]['type'] == 'logs'


def test_update_board_accepts_partial_payload(client, auth_headers):
    boards = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    board = boards[1]
    resp = client.put(f"/api/v1/dashboards/{board['id']}", headers=auth_headers,
                      json={'position': 9})
    assert resp.status_code == 200
    updated = resp.get_json()
    assert updated['position'] == 9
    assert updated['name'] == board['name']
    assert updated['widgets'] == board['widgets']


def test_delete_board(client, auth_headers):
    boards = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    victim = boards[2]['id']

    assert client.delete(f'/api/v1/dashboards/{victim}',
                         headers=auth_headers).status_code == 200

    remaining = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    assert victim not in [b['id'] for b in remaining]
    # The survivors are NOT re-seeded — seeding only happens for a user with no
    # boards at all.
    assert len(remaining) == len(DEFAULT_BOARDS) - 1


def test_unknown_board_is_404(client, auth_headers):
    assert client.put('/api/v1/dashboards/99999', headers=auth_headers,
                      json={'name': 'x'}).status_code == 404
    assert client.delete('/api/v1/dashboards/99999',
                         headers=auth_headers).status_code == 404
    assert client.post('/api/v1/dashboards/99999/reset',
                       headers=auth_headers).status_code == 404


# -------------------------------------------------------------------- reset

def test_reset_restores_the_shipped_default(client, auth_headers):
    boards = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    overview = boards[0]
    original = overview['widgets']

    client.put(f"/api/v1/dashboards/{overview['id']}", headers=auth_headers,
               json={'name': 'Wrecked', 'widgets': [_widget('solo', 'note')]})

    resp = client.post(f"/api/v1/dashboards/{overview['id']}/reset", headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    restored = resp.get_json()
    assert restored['name'] == 'Overview'
    assert restored['widgets'] == original


def test_reset_refuses_a_user_created_board(client, auth_headers):
    created = client.post('/api/v1/dashboards', headers=auth_headers,
                          json={'name': 'Mine'}).get_json()
    resp = client.post(f"/api/v1/dashboards/{created['id']}/reset", headers=auth_headers)
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


# ----------------------------------------------------------- user isolation

def test_boards_are_scoped_per_user(client, auth_headers, other_headers):
    mine = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    theirs = client.get('/api/v1/dashboards', headers=other_headers).get_json()['boards']

    # Each user got their own seeded copy — same slugs, different rows.
    assert [b['slug'] for b in mine] == [b['slug'] for b in theirs]
    assert not set(b['id'] for b in mine) & set(b['id'] for b in theirs)


def test_a_foreign_board_is_404_not_403(client, auth_headers, other_headers):
    mine = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    target = mine[0]['id']

    # Seed the neighbour so their own boards exist and the id is simply not theirs.
    client.get('/api/v1/dashboards', headers=other_headers)

    assert client.put(f'/api/v1/dashboards/{target}', headers=other_headers,
                      json={'name': 'stolen'}).status_code == 404
    assert client.post(f'/api/v1/dashboards/{target}/reset',
                       headers=other_headers).status_code == 404
    assert client.delete(f'/api/v1/dashboards/{target}',
                         headers=other_headers).status_code == 404

    # The owner's board is untouched.
    still = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    assert still[0]['id'] == target
    assert still[0]['name'] == 'Overview'


# ------------------------------------------------------- payload validation

@pytest.mark.parametrize('payload,reason', [
    ('not-a-list', 'widgets must be a list'),
    ({'i': 'w1'}, 'a dict is not a list'),
    ([{'type': 'stat', 'x': 0, 'y': 0, 'w': 3, 'h': 2}], 'missing i'),
    ([{'i': 5, 'type': 'stat', 'x': 0, 'y': 0, 'w': 3, 'h': 2}], 'non-string i'),
    ([{'i': 'w1', 'x': 0, 'y': 0, 'w': 3, 'h': 2}], 'missing type'),
    ([{'i': 'w1', 'type': 'stat', 'x': '0', 'y': 0, 'w': 3, 'h': 2}], 'string x'),
    ([{'i': 'w1', 'type': 'stat', 'x': 0, 'y': 0, 'w': 3.5, 'h': 2}], 'float w'),
    ([{'i': 'w1', 'type': 'stat', 'x': True, 'y': 0, 'w': 3, 'h': 2}], 'bool x'),
    ([{'i': 'w1', 'type': 'stat', 'x': -1, 'y': 0, 'w': 3, 'h': 2}], 'negative x'),
    ([{'i': 'w1', 'type': 'stat', 'x': 0, 'y': 0, 'w': 0, 'h': 2}], 'zero width'),
    ([{'i': 'w1', 'type': 'stat', 'x': 10, 'y': 0, 'w': 4, 'h': 2}], 'overflows 12 cols'),
    ([{'i': 'w1', 'type': 'stat', 'x': 0, 'y': 0, 'w': 3, 'h': 2, 'cfg': 'nope'}], 'cfg not an object'),
    (['just-a-string'], 'entry is not an object'),
])
def test_bad_widget_payloads_are_rejected(client, auth_headers, payload, reason):
    resp = client.post('/api/v1/dashboards', headers=auth_headers,
                       json={'name': 'Bad', 'widgets': payload})
    assert resp.status_code == 400, f'{reason} should be rejected'
    assert 'error' in resp.get_json()


def test_duplicate_widget_ids_are_rejected(client, auth_headers):
    resp = client.post('/api/v1/dashboards', headers=auth_headers, json={
        'name': 'Dupes', 'widgets': [_widget('w1'), _widget('w1', x=3)],
    })
    assert resp.status_code == 400
    assert 'duplicate' in resp.get_json()['error'].lower()


def test_oversized_widget_payload_is_rejected(client, auth_headers):
    huge = [_widget(f'w{n}', x=(n % 4) * 3, y=n) for n in range(101)]
    resp = client.post('/api/v1/dashboards', headers=auth_headers,
                       json={'name': 'Huge', 'widgets': huge})
    assert resp.status_code == 400
    assert '100' in resp.get_json()['error']


def test_update_rejects_a_bad_layout_without_touching_the_board(client, auth_headers):
    boards = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    board = boards[0]

    resp = client.put(f"/api/v1/dashboards/{board['id']}", headers=auth_headers,
                      json={'name': 'Attempted', 'widgets': [{'i': 'w1'}]})
    assert resp.status_code == 400

    unchanged = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    assert unchanged[0]['name'] == board['name']
    assert unchanged[0]['widgets'] == board['widgets']


def test_widget_cfg_round_trips_verbatim(client, auth_headers):
    cfg = {'metric': 'cpu', 'agg': 'p95', 'resource': '$server',
           'thresholds': [70, 90], 'nested': {'deep': ['a', 1, None]}}
    created = client.post('/api/v1/dashboards', headers=auth_headers, json={
        'name': 'Cfg', 'widgets': [_widget(cfg=cfg)],
    }).get_json()
    assert created['widgets'][0]['cfg'] == cfg

    reread = client.get('/api/v1/dashboards', headers=auth_headers).get_json()['boards']
    assert reread[-1]['widgets'][0]['cfg'] == cfg
