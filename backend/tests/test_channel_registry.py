"""Plan 77 E2 — the declarative channel registry: one auth model, per-channel gates.

Drives the generated handlers directly (the flask-socketio test client is
incompatible with the pinned Flask), with emit/join_room patched and the
authenticated-identity map seeded like the connect handler would.
"""
import re
from pathlib import Path

import pytest

import app.sockets as sk
from app import db
from factories import make_user

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def wire(app, monkeypatch):
    """Patch the socket wire functions; returns the captured event list."""
    events = []
    monkeypatch.setattr(sk, 'emit', lambda name, payload=None, **k: events.append((name, payload)))
    monkeypatch.setattr(sk, 'join_room', lambda room: events.append(('__join__', room)))
    monkeypatch.setattr(sk, 'leave_room', lambda room: events.append(('__leave__', room)))
    yield events
    sk.metric_subscribers.clear()
    with sk._connected_clients_lock:
        sk.connected_clients.clear()


def _run(app, handler, data=None, sid='sid-1'):
    with app.test_request_context('/'):
        from flask import request
        request.sid = sid
        handler(data)


def _authed(sid='sid-1', role='developer'):
    with sk._connected_clients_lock:
        from flask_jwt_extended import create_access_token, decode_token
        user = make_user(db, role=role)
        sk.connected_clients[sid] = {
            'user_id': user.id, 'role': role,
            'claims': decode_token(create_access_token(identity=user.id)),
        }


def test_registered_channels_exist(app):
    assert {'metrics', 'container_status', 'terminal', 'deploy'} <= set(sk.CHANNELS)


def test_unauthenticated_socket_is_rejected_on_every_channel(app, wire):
    for name, spec in sk.CHANNELS.items():
        wire.clear()
        _run(app, spec['subscribe'], {}, sid='ghost')
        assert wire and wire[0] == ('error', {'message': 'Authentication required'}), name


def test_metrics_subscribe_ack_and_state(app, wire, monkeypatch):
    # Don't actually start the broadcast thread in tests.
    monkeypatch.setattr(sk.metrics_loop, 'start', lambda *a, **k: True)
    _authed()
    _run(app, sk.CHANNELS['metrics']['subscribe'])
    assert ('subscribed', {'channel': 'metrics'}) in wire
    assert 'sid-1' in sk.metric_subscribers

    wire.clear()
    _run(app, sk.CHANNELS['metrics']['unsubscribe'])
    assert ('unsubscribed', {'channel': 'metrics'}) in wire
    assert 'sid-1' not in sk.metric_subscribers


def test_deploy_requires_job_id_then_joins_room(app, wire):
    _authed()
    _run(app, sk.CHANNELS['deploy']['subscribe'], {})
    assert ('error', {'message': 'job_id required'}) in wire

    wire.clear()
    from app.models.deployment_job import DeploymentJob
    db.session.add(DeploymentJob(id='job-1', kind='test', requested_by=sk.connected_clients['sid-1']['user_id']))
    db.session.commit()
    _run(app, sk.CHANNELS['deploy']['subscribe'], {'job_id': 'job-1'})
    assert ('__join__', 'deploy_job-1') in wire
    assert ('subscribed', {'channel': 'deploy', 'job_id': 'job-1'}) in wire


def test_terminal_gate_rejects_viewer(app, wire):
    _authed(role='viewer')
    _run(app, sk.CHANNELS['terminal']['subscribe'], {'session_id': 'whatever'})
    assert wire == [('error', {'message': 'Developer role required for terminal access'})]


def test_terminal_unknown_session_for_developer(app, wire):
    _authed(role='developer')
    _run(app, sk.CHANNELS['terminal']['subscribe'], {'session_id': 'nope'})
    assert wire == [('error', {'message': 'Unknown terminal session'})]


def test_terminal_unsubscribe_does_not_ack(app, wire):
    """The legacy handler never acked the leave; the registry preserves that."""
    _authed(role='developer')
    _run(app, sk.CHANNELS['terminal']['unsubscribe'], {'session_id': 'nope'})
    assert wire == []  # no leave (unknown session), no ack


def test_generic_join_room_still_gates_terminal_rooms(app, wire):
    _authed(role='viewer')
    _run(app, sk.handle_join_room, {'room': 'server_s1_terminal:sess'})
    assert wire == [('error', {'message': 'Room access denied'})]


def test_raw_subscribe_handlers_are_frozen():
    """Ratchet: new channels go through register_channel, not raw handlers."""
    src = (BACKEND / 'app' / 'sockets.py').read_text(encoding='utf-8')
    raw = set(re.findall(r"@socketio\.on\('subscribe_(\w+)'\)", src))
    assert raw == {'logs', 'container_logs'}, (
        f'Raw subscribe handlers changed: {sorted(raw)}. New channels must use '
        'register_channel() (plan 77 E2); the two legacy handlers own per-sid '
        'OS resources and are frozen until they migrate.'
    )
