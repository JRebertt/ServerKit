"""Proving tests for the trusted client-IP seam (plan 48, Phase 1).

The old code hand-parsed the *leftmost* X-Forwarded-For token — a value the
client fully controls — to key rate-limit buckets, audit-log source IPs and
API-key attribution. These tests pin the corrected behaviour:

- With trust OFF (dev default), a forged X-Forwarded-For never changes the IP
  the app trusts: get_client_ip() stays the socket peer (remote_addr).
- With trust ON behind one proxy hop, ProxyFix takes the *rightmost* hop the
  trusted proxy appended, so a forged leftmost value is discarded.
- The rate-limit key follows the real client, so two requests forging the same
  leftmost value from different real peers land in *different* buckets, and
  flask-limiter isolates them.
"""
import pytest

from app import create_app

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


def _build_app(monkeypatch, trust, hops=1):
    """Create a testing app with the trusted-proxy config forced on/off.

    from_object reads the class attribute at create_app time, so monkeypatching
    it before the call drives the real ProxyFix gating in create_app().
    """
    from config import TestingConfig
    monkeypatch.setattr(TestingConfig, 'TRUST_PROXY_HEADERS', trust)
    monkeypatch.setattr(TestingConfig, 'TRUSTED_PROXY_HOPS', hops)
    app = create_app('testing')

    from app.utils.client_ip import get_client_ip
    from app.middleware.rate_limit import get_rate_limit_key

    # Non-/api probe so the audit/analytics/2FA before-request handlers skip it.
    def _probe():
        return {'ip': get_client_ip() or '', 'rlkey': get_rate_limit_key()}

    app.add_url_rule('/__probe_ip', '__probe_ip', _probe)
    return app


# --- Trust OFF: forged headers must be ignored --------------------------

def test_forged_xff_ignored_when_trust_off(monkeypatch):
    app = _build_app(monkeypatch, trust=False)
    client = app.test_client()

    resp = client.get(
        '/__probe_ip',
        headers={'X-Forwarded-For': '9.9.9.9'},
        environ_overrides={'REMOTE_ADDR': '203.0.113.7'},
    )
    assert resp.status_code == 200
    # remote_addr wins — the forged 9.9.9.9 is never trusted.
    assert resp.get_json()['ip'] == '203.0.113.7'


def test_forged_xreal_ip_ignored_when_trust_off(monkeypatch):
    app = _build_app(monkeypatch, trust=False)
    client = app.test_client()

    resp = client.get(
        '/__probe_ip',
        headers={'X-Real-IP': '9.9.9.9', 'X-Forwarded-For': '8.8.8.8'},
        environ_overrides={'REMOTE_ADDR': '198.51.100.4'},
    )
    assert resp.get_json()['ip'] == '198.51.100.4'


# --- Trust ON, one hop: rightmost (proxy-appended) hop wins -------------

def test_proxy_appended_hop_wins_when_trust_on(monkeypatch):
    app = _build_app(monkeypatch, trust=True, hops=1)
    client = app.test_client()

    # nginx received "9.9.9.9" from the client and appended the real peer.
    resp = client.get(
        '/__probe_ip',
        headers={'X-Forwarded-For': '9.9.9.9, 203.0.113.7'},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},  # nginx -> flask
    )
    assert resp.status_code == 200
    assert resp.get_json()['ip'] == '203.0.113.7'


def test_multiple_forged_hops_all_discarded(monkeypatch):
    app = _build_app(monkeypatch, trust=True, hops=1)
    client = app.test_client()

    resp = client.get(
        '/__probe_ip',
        headers={'X-Forwarded-For': '1.2.3.4, 5.6.7.8, 203.0.113.7'},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    # Only the rightmost (the single trusted hop) survives.
    assert resp.get_json()['ip'] == '203.0.113.7'


# --- Rate-limit key follows the real client, not the forged prefix ------

def test_same_forged_prefix_different_peer_not_merged(monkeypatch):
    app = _build_app(monkeypatch, trust=True, hops=1)
    client = app.test_client()

    a = client.get('/__probe_ip',
                   headers={'X-Forwarded-For': '1.1.1.1, 10.0.0.1'})
    b = client.get('/__probe_ip',
                   headers={'X-Forwarded-For': '1.1.1.1, 10.0.0.2'})

    # Same forged leftmost, different real peer -> different IPs and rl-keys.
    assert a.get_json()['ip'] == '10.0.0.1'
    assert b.get_json()['ip'] == '10.0.0.2'
    assert a.get_json()['rlkey'] != b.get_json()['rlkey']
    assert a.get_json()['rlkey'] == 'ip:10.0.0.1'


def test_different_forged_prefix_same_peer_is_one_bucket(monkeypatch):
    app = _build_app(monkeypatch, trust=True, hops=1)
    client = app.test_client()

    a = client.get('/__probe_ip',
                   headers={'X-Forwarded-For': '1.1.1.1, 10.0.0.9'})
    b = client.get('/__probe_ip',
                   headers={'X-Forwarded-For': '2.2.2.2, 10.0.0.9'})

    # Rotating the forged prefix cannot escape the real client's bucket.
    assert a.get_json()['rlkey'] == b.get_json()['rlkey'] == 'ip:10.0.0.9'


def test_flask_limiter_isolates_real_client_buckets(monkeypatch):
    """flask-limiter's 5/min on /login must key on the real client, so
    exhausting one client's bucket does not lock out a different client that
    merely shares a forged leftmost XFF value."""
    app = _build_app(monkeypatch, trust=True, hops=1)
    client = app.test_client()

    def _login(rightmost):
        return client.post(
            '/api/v1/auth/login',
            json={'email': 'nobody@test.local', 'password': 'wrong'},
            headers={'X-Forwarded-For': f'1.1.1.1, {rightmost}'},
        )

    # Client A (real peer 203.0.113.10) exhausts its 5/min login budget.
    statuses = [_login('203.0.113.10').status_code for _ in range(6)]
    assert 429 in statuses, statuses  # limiter tripped for client A

    # Client B forges the SAME leftmost 1.1.1.1 but is a different real peer:
    # it must not inherit A's exhausted bucket.
    assert _login('203.0.113.20').status_code != 429
