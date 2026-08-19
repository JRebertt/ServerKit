"""Plan 77 A2 gate — ONE agent handshake, exercised for both transports.

agent_registry.authenticate_and_register is the single implementation of
rate-limit -> HMAC verify -> allowed-IPs + anomaly -> new-IP check ->
version parse -> register. The WS namespace and the long-poll /connect are
thin adapters; the ratchet at the bottom asserts neither re-grows its own
copy of the sequence.
"""
import hashlib
import hmac
import time
from pathlib import Path

import pytest

import app.services.agent_registry as reg_mod
from app import db as _db
from app.models.server import Server
from app.services.agent_registry import agent_registry

TRANSPORTS = ['ws', 'poll']


@pytest.fixture(autouse=True)
def _isolate(app, monkeypatch):
    reg_mod._auth_attempts.clear()
    with agent_registry._lock:
        agent_registry._agents.clear()
        agent_registry._socket_to_server.clear()
    import app.services.anomaly_detection_service as ad
    for name in ("track_auth_attempt", "track_ip_blocked", "track_replay_attack",
                 "check_new_ip"):
        monkeypatch.setattr(ad.anomaly_detection_service, name,
                            lambda *a, **k: None, raising=False)
    yield
    reg_mod._auth_attempts.clear()
    with agent_registry._lock:
        agent_registry._agents.clear()
        agent_registry._socket_to_server.clear()


def _mk_agent_server(monkeypatch, allowed_ips=None):
    api_key, api_secret = Server.generate_api_credentials()
    server = Server(name='hs-matrix', agent_id='agent-hs')
    server.set_api_key(api_key)
    if allowed_ips is not None:
        server.allowed_ips = allowed_ips
    _db.session.add(server)
    _db.session.commit()
    monkeypatch.setattr(Server, 'get_api_secret', lambda self: api_secret)
    return server, api_secret


def _payload(server, secret, nonce='n-1'):
    ts = int(time.time() * 1000)
    msg = f"{server.agent_id}:{ts}:{nonce}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        'agent_id': server.agent_id,
        'api_key_prefix': server.api_key_prefix,
        'signature': sig,
        'timestamp': ts,
        'nonce': nonce,
    }


@pytest.mark.parametrize('transport', TRANSPORTS)
def test_good_handshake_registers(app, monkeypatch, transport):
    server, secret = _mk_agent_server(monkeypatch)
    token, srv, error = agent_registry.authenticate_and_register(
        _payload(server, secret), '198.51.100.7',
        user_agent='ServerKit-Agent/9.9.9', transport=transport,
        socket_id='sid-1' if transport == 'ws' else None,
    )
    assert error is None
    assert srv.id == server.id
    agent = agent_registry.get_agent_by_token(token)
    assert agent is not None and agent.transport == transport
    assert agent.agent_version == '9.9.9'
    if transport == 'poll':
        assert agent.socket_id.startswith('poll-')


@pytest.mark.parametrize('transport', TRANSPORTS)
def test_bad_hmac_fails_closed(app, monkeypatch, transport):
    server, secret = _mk_agent_server(monkeypatch)
    payload = _payload(server, secret)
    payload['signature'] = 'deadbeef' * 8
    token, srv, error = agent_registry.authenticate_and_register(
        payload, '198.51.100.7', transport=transport)
    assert error == 'auth_failed'
    assert token is None


@pytest.mark.parametrize('transport', TRANSPORTS)
def test_missing_fields_fail(app, monkeypatch, transport):
    token, srv, error = agent_registry.authenticate_and_register(
        {'agent_id': 'x'}, '198.51.100.7', transport=transport)
    assert error == 'missing_fields'
    assert token is None


@pytest.mark.parametrize('transport', TRANSPORTS)
def test_blocked_ip_tracks_anomaly(app, monkeypatch, transport):
    server, secret = _mk_agent_server(monkeypatch, allowed_ips=['203.0.113.50'])
    blocked = []
    import app.services.anomaly_detection_service as ad
    monkeypatch.setattr(ad.anomaly_detection_service, 'track_ip_blocked',
                        lambda sid, ip, allowed: blocked.append((sid, ip)))
    token, srv, error = agent_registry.authenticate_and_register(
        _payload(server, secret), '198.51.100.7', transport=transport)
    assert error == 'ip_not_allowed'
    assert token is None
    assert blocked == [(server.id, '198.51.100.7')]


@pytest.mark.parametrize('transport', TRANSPORTS)
def test_new_ip_anomaly_check_runs(app, monkeypatch, transport):
    server, secret = _mk_agent_server(monkeypatch)
    seen = []
    import app.services.anomaly_detection_service as ad
    monkeypatch.setattr(ad.anomaly_detection_service, 'check_new_ip',
                        lambda sid, ip: seen.append((sid, ip)))
    token, srv, error = agent_registry.authenticate_and_register(
        _payload(server, secret), '198.51.100.7', transport=transport)
    assert error is None
    assert seen == [(server.id, '198.51.100.7')]


@pytest.mark.parametrize('transport', TRANSPORTS)
def test_rate_limit_applies_before_auth(app, monkeypatch, transport):
    server, secret = _mk_agent_server(monkeypatch)
    for _ in range(reg_mod._AUTH_RATE_LIMIT):
        assert reg_mod._check_auth_rate_limit('198.51.100.9')
    token, srv, error = agent_registry.authenticate_and_register(
        _payload(server, secret), '198.51.100.9', transport=transport)
    assert error == 'rate_limited'
    assert token is None


# ---------------------------------------------------------------------------
# Ratchet: the transports stay thin adapters.
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parents[1] / 'app'

# Word-anchored: 'unregister_agent(' must NOT count as 'register_agent('
# (substring greps have produced false blockers here before).
FORBIDDEN = [
    r'(?<![\w.])verify_agent_auth\(',   # HMAC step belongs to the door
    r'(?<![\w])register_agent\(',       # registration step belongs to the door
    r'(?<![\w.])is_ip_allowed\(',       # allowlist step belongs to the door
    r'(?<![\w.])check_new_ip\(',        # anomaly step belongs to the door
]


@pytest.mark.parametrize('adapter', ['agent_gateway.py', 'api/agent_poll.py'])
def test_no_second_handshake_implementation(adapter):
    import re
    src = (APP_DIR / adapter).read_text(encoding='utf-8')
    hits = [tok for tok in FORBIDDEN if re.search(tok, src)]
    assert not hits, (
        f"{adapter} re-implements handshake steps {hits} — extend "
        "agent_registry.authenticate_and_register instead (plan 77 A2)."
    )
