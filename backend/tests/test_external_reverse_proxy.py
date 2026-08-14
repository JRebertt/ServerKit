"""Proving tests — the panel is safe to run behind someone else's reverse proxy.

Issue #96: an operator fronted ServerKit with their own Caddy + a smallstep
private CA and got an infinite redirect loop. The loop came from the *nginx*
site we install (it 301s :80 -> https), not from the app — but nothing pinned
that, so "the app never redirects to HTTPS" was a property we relied on in the
docs without a test to keep it true.

These tests pin the three app-level properties an external TLS-terminating
proxy depends on (plan 71):

1. No route and no ``before_request`` handler redirects to https. A proxy
   speaks plain HTTP upstream; one redirect here is an infinite loop in the
   browser, and it survives even the topology that bypasses nginx entirely.
2. ``SERVERKIT_PUBLIC_URL`` is auto-allowed as an origin, and reaches
   Socket.IO. Without it the engine.io handshake 400s and the UI loads but
   never live-updates — the single most common symptom behind a proxy.
3. That origin allowance is a real allowlist, not ``*``.

Two neighbouring properties are already covered elsewhere and are deliberately
not duplicated here: ProxyFix / client-IP derivation in
``test_trusted_client_ip.py`` (plan 48) and HSTS gating in
``test_security_headers.py``.
"""

import importlib.util
import pathlib

import pytest


PUBLIC_URL = 'https://serverkit.example.com'

CONFIG_PATH = pathlib.Path(__file__).resolve().parents[1] / 'config.py'


# ── 1. Nothing in the app redirects to HTTPS ────────────────────────────────
#
# Probed over plain HTTP, which is exactly how an external proxy talks upstream.

# Routes an unauthenticated proxy request realistically lands on first.
_ENTRY_ROUTES = [
    '/',
    '/login',
    '/dashboard',
    '/api/v1/system/health',
    '/api/v1/auth/setup-status',
]


@pytest.mark.parametrize('path', _ENTRY_ROUTES)
def test_entry_routes_never_redirect_to_https(client, path):
    r = client.get(path)
    location = r.headers.get('Location', '')
    assert not location.startswith('https://'), (
        f'{path} -> {r.status_code} Location: {location}. An external reverse '
        'proxy speaks plain HTTP upstream, so an app-side redirect to https is '
        'an infinite loop in the browser.'
    )


@pytest.mark.parametrize('path', _ENTRY_ROUTES)
def test_forwarded_proto_https_does_not_trigger_a_redirect(client, path):
    """The header a TLS-terminating proxy adds must not become a redirect trigger.

    ``X-Forwarded-Proto: https`` is what any "force HTTPS" middleware keys on.
    Asserting the *negative* here is what would catch someone later adding a
    well-meaning scheme-based redirect.
    """
    r = client.get(path, headers={
        'X-Forwarded-Proto': 'https',
        'X-Forwarded-Host': 'serverkit.example.com',
        'Host': 'serverkit.example.com',
    })
    assert not r.headers.get('Location', '').startswith('https://')


def test_no_registered_route_redirects_to_https(client, app):
    """Sweep every no-argument GET rule, not just the curated entry points.

    A redirect anywhere in the app is enough to trap a proxied browser, and new
    blueprints land here regularly, so the guarantee has to be checked across
    the whole URL map rather than a hand-picked list.
    """
    offenders = []
    for rule in app.url_map.iter_rules():
        if 'GET' not in (rule.methods or set()) or rule.arguments:
            continue
        if rule.rule.startswith('/socket.io'):
            continue  # long-polling transport, exercised separately below
        r = client.get(rule.rule, headers={'X-Forwarded-Proto': 'https'})
        location = r.headers.get('Location', '')
        if location.startswith('https://'):
            offenders.append(f'{rule.rule} -> {r.status_code} {location}')

    assert not offenders, 'Routes redirecting to https:\n' + '\n'.join(offenders)


# ── 2. SERVERKIT_PUBLIC_URL becomes an allowed origin ───────────────────────


@pytest.fixture
def probe_config(monkeypatch):
    """Evaluate config.py's class body again under a patched environment.

    ``CORS_ORIGINS`` is built at class-definition time, so ``monkeypatch.setenv``
    alone cannot move it — the module body has to run again.

    It is loaded as a *private, throwaway* module and deliberately NOT registered
    in ``sys.modules``. ``importlib.reload(config)`` would look equivalent and is
    a trap: it rebinds ``config.TestingConfig`` to a brand-new class object while
    ``app/__init__.py`` still holds the original ``config`` dict from its
    ``from config import config``. Tests that do
    ``monkeypatch.setattr(TestingConfig, 'TRUST_PROXY_HEADERS', True)`` would
    then patch the new class while ``create_app`` reads the old one, so ProxyFix
    silently never turns on — which broke 9 tests in test_trusted_client_ip.py
    and test_login_bruteforce.py, in a full run only, when this fixture used
    reload.
    """
    def _load(**env):
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        spec = importlib.util.spec_from_file_location('_sk_config_probe', CONFIG_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


def test_public_url_is_auto_allowed_as_an_origin(probe_config):
    probed = probe_config(SERVERKIT_PUBLIC_URL=PUBLIC_URL, CORS_ORIGINS=None)
    assert PUBLIC_URL in probed.Config.CORS_ORIGINS


def test_public_url_trailing_slash_is_normalised(probe_config):
    """A browser Origin header never carries a trailing slash.

    Operators copy the URL out of the address bar, which does. Storing it raw
    would silently never match.
    """
    probed = probe_config(SERVERKIT_PUBLIC_URL=PUBLIC_URL + '/', CORS_ORIGINS=None)
    assert PUBLIC_URL in probed.Config.CORS_ORIGINS
    assert PUBLIC_URL + '/' not in probed.Config.CORS_ORIGINS


def test_public_url_does_not_replace_explicit_cors_origins(probe_config):
    """It is additive: setting a public URL must not drop configured origins."""
    probed = probe_config(
        SERVERKIT_PUBLIC_URL=PUBLIC_URL,
        CORS_ORIGINS='https://other.example.com',
    )
    assert 'https://other.example.com' in probed.Config.CORS_ORIGINS
    assert PUBLIC_URL in probed.Config.CORS_ORIGINS


def test_origins_are_an_allowlist_not_a_wildcard(probe_config):
    probed = probe_config(SERVERKIT_PUBLIC_URL=PUBLIC_URL, CORS_ORIGINS=None)
    assert '*' not in probed.Config.CORS_ORIGINS


# ── 3. The allowlist actually reaches Socket.IO and is enforced ─────────────


def test_init_socketio_passes_cors_origins_through(monkeypatch):
    """The wiring, asserted without touching the shared SocketIO singleton."""
    from app import sockets

    captured = {}
    monkeypatch.setattr(
        sockets.socketio, 'init_app',
        lambda app, **kwargs: captured.update(kwargs),
    )

    class _FakeApp:
        config = {'CORS_ORIGINS': [PUBLIC_URL]}

    sockets.init_socketio(_FakeApp())

    assert captured['cors_allowed_origins'] == [PUBLIC_URL]
    # threading mode is load-bearing: the gevent-websocket worker would
    # double-answer the upgrade handshake behind a proxy.
    assert captured['async_mode'] == 'threading'


def _handshake_app():
    """A minimal Flask+SocketIO app wired the way init_socketio wires the real one.

    Built standalone rather than via ``create_app`` because ``socketio`` is a
    module-level singleton: re-initialising it against a throwaway app would
    leave the session-wide app pointing at this test's origin list.
    """
    from flask import Flask
    from flask_socketio import SocketIO

    app = Flask(__name__)
    SocketIO(app, cors_allowed_origins=[PUBLIC_URL], async_mode='threading')
    return app


HANDSHAKE = '/socket.io/?EIO=4&transport=polling'


def test_socketio_handshake_accepts_the_public_url_origin():
    r = _handshake_app().test_client().get(HANDSHAKE, headers={'Origin': PUBLIC_URL})
    assert r.status_code == 200


def test_socketio_handshake_rejects_an_unknown_origin():
    r = _handshake_app().test_client().get(
        HANDSHAKE, headers={'Origin': 'https://evil.example'})
    assert r.status_code == 400
