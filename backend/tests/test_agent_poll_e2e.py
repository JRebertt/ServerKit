"""
End-to-end integration test for the panel<->agent command loop.

This is the "does the whole thing actually work" test the agent subsystem was
missing. It drives the REST long-poll transport (POST /connect, /poll, /result)
because that path is plain HTTP yet shares the exact same code as the WebSocket
gateway for the parts that matter: HMAC authentication (verify_agent_auth),
agent registration in the in-memory registry, command queueing/routing
(send_command -> outbound_queue -> drain), and result delivery back to the
synchronous waiter.

If these pass, we know: a correctly-signed agent can authenticate, register,
receive a command the panel issued, and round-trip a result back to the caller.

Uses a temp-file SQLite DB (not the in-memory default) so the background
send_command thread and the request handlers share committed rows.
"""
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time

import pytest

import app.agent_gateway as gw
from app import db as _db
from app.models.server import Server
from app.services.agent_registry import agent_registry

CONNECT = "/api/v1/agent/connect"
POLL = "/api/v1/agent/poll"
RESULT = "/api/v1/agent/result"


# --------------------------------------------------------------------------
# Fixtures: temp-file app so threads + requests see the same committed data.
# --------------------------------------------------------------------------

@pytest.fixture()
def app():
    """Flask app on a temp-file SQLite DB (thread-shareable, unlike :memory:)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["TEST_DATABASE_URL"] = "sqlite:///" + path.replace("\\", "/")

    from app import create_app
    from app import db as db

    application = create_app("testing")
    with application.app_context():
        db.create_all()
        try:
            yield application
        finally:
            db.session.remove()
            db.drop_all()
    os.environ.pop("TEST_DATABASE_URL", None)
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Reset process-wide singleton state and no-op anomaly side-effects so each
    test starts clean and exercises only the auth/transport logic."""
    # Clear the shared per-IP auth rate limiter (a module singleton).
    gw._auth_attempts.clear()
    # Clear any agents left in the in-memory registry by a previous test.
    with agent_registry._lock:
        agent_registry._agents.clear()
        agent_registry._socket_to_server.clear()

    import app.services.anomaly_detection_service as ad
    for name in ("track_auth_attempt", "track_ip_blocked", "track_replay_attack",
                 "check_new_ip"):
        monkeypatch.setattr(ad.anomaly_detection_service, name,
                            lambda *a, **k: None, raising=False)

    yield

    gw._auth_attempts.clear()
    with agent_registry._lock:
        agent_registry._agents.clear()
        agent_registry._socket_to_server.clear()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_agent_server(monkeypatch, permissions=None):
    """Create a Server row with a known shared secret and return
    (server_id, agent_id, api_key_prefix, api_secret). get_api_secret is
    stubbed to the known secret so the test doesn't depend on the Fernet
    key setup (mirrors test_agent_registry_security)."""
    api_key, api_secret = Server.generate_api_credentials()
    server = Server(name="e2e", agent_id="agent-e2e")
    server.set_api_key(api_key)  # sets api_key_prefix = api_key[:12]
    server.permissions = permissions if permissions is not None else ["*"]
    _db.session.add(server)
    _db.session.commit()

    monkeypatch.setattr(Server, "get_api_secret", lambda self: api_secret)
    return server.id, server.agent_id, server.api_key_prefix, api_secret


def _auth_payload(agent_id, prefix, secret, nonce="nonce-e2e-1"):
    ts = int(time.time() * 1000)
    msg = f"{agent_id}:{ts}:{nonce}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "agent_id": agent_id,
        "api_key_prefix": prefix,
        "signature": sig,
        "timestamp": ts,
        "nonce": nonce,
    }


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_connect_authenticates_and_registers(client, monkeypatch):
    """A correctly-signed agent authenticates over the poll transport, gets a
    session token, and shows up in the registry as a poll-mode agent."""
    server_id, agent_id, prefix, secret = _make_agent_server(monkeypatch)

    resp = client.post(CONNECT, json=_auth_payload(agent_id, prefix, secret))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["success"] is True
    assert body["server_id"] == server_id
    token = body["session_token"]
    assert token

    agent = agent_registry.get_agent_by_token(token)
    assert agent is not None
    assert agent.server_id == server_id
    assert agent.transport == "poll"


def test_connect_rejects_bad_signature(client, monkeypatch):
    """Auth must fail closed when the HMAC doesn't match — no session issued."""
    server_id, agent_id, prefix, secret = _make_agent_server(monkeypatch)

    payload = _auth_payload(agent_id, prefix, secret)
    payload["signature"] = "deadbeef" * 8  # wrong signature

    resp = client.post(CONNECT, json=payload)
    assert resp.status_code == 401, resp.get_data(as_text=True)


def test_command_roundtrip_via_send_command(app, client, monkeypatch):
    """The full loop through the real public API:

    panel send_command -> queued -> agent /poll receives it -> agent /result
    posts the outcome -> send_command's synchronous waiter resolves with it.
    """
    server_id, agent_id, prefix, secret = _make_agent_server(monkeypatch)

    # Agent authenticates and gets a session token.
    resp = client.post(CONNECT, json=_auth_payload(agent_id, prefix, secret))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    token = resp.get_json()["session_token"]

    # Panel issues a command from a background thread (send_command blocks until
    # the result comes back). It needs its own app context for DB writes.
    holder = {}

    def _issue():
        with app.app_context():
            holder["result"] = agent_registry.send_command(
                server_id=server_id,
                action="system:info",
                params={"probe": True},
                timeout=15.0,
            )

    t = threading.Thread(target=_issue, daemon=True)
    t.start()

    # Agent long-polls and should receive the queued command. drain_outbound
    # blocks until the command is queued, so there's no race with the thread.
    poll = client.post(POLL, headers={"X-Session-Token": token}, json={})
    assert poll.status_code == 200, poll.get_data(as_text=True)
    commands = poll.get_json()["commands"]
    assert len(commands) == 1, f"expected one queued command, got {commands}"
    cmd = commands[0]
    assert cmd["action"] == "system:info"
    assert cmd["params"] == {"probe": True}
    command_id = cmd["id"]

    # Agent reports the outcome.
    result_payload = {
        "command_id": command_id,
        "success": True,
        "data": {"hostname": "test-host", "os": "linux"},
        "duration": 12,
    }
    res = client.post(RESULT, headers={"X-Session-Token": token},
                      json=result_payload)
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["ok"] is True

    # The panel-side waiter must resolve with exactly what the agent reported.
    t.join(timeout=10)
    assert not t.is_alive(), "send_command did not return after result posted"
    result = holder.get("result")
    assert result is not None
    assert result["success"] is True
    assert result["data"] == {"hostname": "test-host", "os": "linux"}


def test_result_for_unknown_command_is_rejected(client, monkeypatch):
    """Posting a result for a command the panel never issued is a 404 — the
    token is valid but there's no matching pending command."""
    server_id, agent_id, prefix, secret = _make_agent_server(monkeypatch)
    token = client.post(
        CONNECT, json=_auth_payload(agent_id, prefix, secret)
    ).get_json()["session_token"]

    res = client.post(RESULT, headers={"X-Session-Token": token},
                      json={"command_id": "never-issued", "success": True})
    assert res.status_code == 404, res.get_data(as_text=True)


# --------------------------------------------------------------------------
# Plan 77 A1 — capability side-effects are transport-neutral
# --------------------------------------------------------------------------

def _stub_tunnel_broker(monkeypatch):
    """Install a fake serverkit-remote-access TunnelBrokerService and return
    the list schedule_reconcile appends to."""
    calls = []

    class _FakeBroker:
        @staticmethod
        def schedule_reconcile(server_id):
            calls.append(server_id)

    import app.services.plugin_service as plugin_service

    real = plugin_service.get_installed_extension_attr

    def fake_get_attr(ext, module, attr):
        if (ext, module, attr) == (
            'serverkit-remote-access', 'tunnel_broker_service', 'TunnelBrokerService'
        ):
            return _FakeBroker
        return real(ext, module, attr)

    monkeypatch.setattr(plugin_service, 'get_installed_extension_attr', fake_get_attr)
    return calls


def test_poll_capabilities_trigger_tunnel_reconcile(app, client, monkeypatch):
    """A WireGuard-capable agent on the long-poll fallback transport must
    self-heal its tunnels exactly like one on WebSocket: the capability
    payload arriving via POST /poll schedules a tunnel reconcile.

    Regression for the plan-77 A1 bug: schedule_reconcile was only invoked
    from the WS on_capabilities handler, so poll-mode agents never healed."""
    server_id, agent_id, prefix, secret = _make_agent_server(monkeypatch)
    calls = _stub_tunnel_broker(monkeypatch)

    resp = client.post(CONNECT, json=_auth_payload(agent_id, prefix, secret))
    assert resp.status_code == 200
    token = resp.get_json()["session_token"]

    # Patch drain so the long-poll returns immediately.
    monkeypatch.setattr(agent_registry, "drain_outbound", lambda agent, max_wait_s=0: [])

    resp = client.post(
        POLL,
        headers={"X-Session-Token": token},
        json={
            "metrics": {"cpu_percent": 1.0},
            "capabilities": {
                "capabilities": {"docker": True, "wireguard": True},
                "platform": "linux",
            },
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert calls == [server_id]


def test_ws_ingest_path_still_triggers_tunnel_reconcile(app, client, monkeypatch):
    """The WS handler delegates to the same registry ingest — a capability
    payload through update_capabilities (what on_capabilities calls)
    schedules the reconcile too, so the door is shared, not moved."""
    server_id, agent_id, prefix, secret = _make_agent_server(monkeypatch)
    calls = _stub_tunnel_broker(monkeypatch)

    resp = client.post(CONNECT, json=_auth_payload(agent_id, prefix, secret))
    assert resp.status_code == 200

    agent_registry.update_capabilities(
        server_id,
        {"capabilities": {"wireguard": True}, "platform": "linux"},
    )
    assert calls == [server_id]


def test_non_wireguard_capabilities_do_not_reconcile(app, client, monkeypatch):
    """No wireguard capability -> no reconcile scheduling on either path."""
    server_id, agent_id, prefix, secret = _make_agent_server(monkeypatch)
    calls = _stub_tunnel_broker(monkeypatch)

    resp = client.post(CONNECT, json=_auth_payload(agent_id, prefix, secret))
    assert resp.status_code == 200

    agent_registry.update_capabilities(
        server_id, {"capabilities": {"docker": True}, "platform": "linux"}
    )
    assert calls == []
