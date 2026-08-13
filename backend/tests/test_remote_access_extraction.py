"""Prove the Remote Access (WireGuard tunnels) extraction (plan 47 Phase 2).

The tunnels blueprint + broker/publish/netutil services move out of core into
serverkit-remote-access; the Tunnel/ExposedService models stay core (G2). This
also re-homes the former test_tunnel_netutil.py (pure subnet/port helpers) and
test_tunnel_reconcile.py (panel-authoritative reconcile) against the extension.
"""
import importlib
import sys
from types import SimpleNamespace

import pytest

from app import db
from app.models.server import Server
from app.models.tunnel import Tunnel
from app.models.exposed_service import ExposedService
from app.models.plugin import InstalledPlugin
from app.services import agent_registry as ar_mod
from app.services import plugin_service

# Installs plugins, and plugin_service hot-loads their blueprints onto the
# live app. Flask refuses register_blueprint once an app has served a
# request, so these need a private app (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app

SLUG = 'serverkit-remote-access'
_PKG = f'app.plugins.{SLUG}'


# ── extraction shape ─────────────────────────────────────────────────────────

def test_core_has_no_tunnel_routes(app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert [r for r in rules if r.startswith('/api/v1/tunnels')] == []


def test_core_import_of_tunnel_services_gone():
    for mod in ('tunnel_broker_service', 'tunnel_publish_service', 'tunnel_netutil'):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f'app.services.{mod}')


def test_remote_access_in_converted_builtin_slugs():
    from app.services.extension_migration import CONVERTED_BUILTIN_SLUGS
    assert SLUG in CONVERTED_BUILTIN_SLUGS


def test_tunnel_models_stay_core():
    from app.models.tunnel import Tunnel  # noqa: F401
    from app.models.exposed_service import ExposedService  # noqa: F401


@pytest.fixture
def install_dirs(tmp_path, monkeypatch):
    backend = tmp_path / 'plugins_backend'
    frontend = tmp_path / 'plugins_frontend'
    backend.mkdir()
    frontend.mkdir()
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))

    added = str(backend)
    app_pkg_plugins = importlib.import_module('app.plugins')
    if added not in app_pkg_plugins.__path__:
        app_pkg_plugins.__path__.append(added)

    yield {'backend': backend, 'frontend': frontend}

    if added in app_pkg_plugins.__path__:
        app_pkg_plugins.__path__.remove(added)
    for name in list(sys.modules):
        if name == _PKG or name.startswith(_PKG + '.'):
            del sys.modules[name]


@pytest.fixture
def ext(app, install_dirs):
    plugin_service.install_builtin_extension(SLUG)
    tn = importlib.import_module(f'{_PKG}.tunnel_netutil')
    broker = importlib.import_module(f'{_PKG}.tunnel_broker_service')
    return SimpleNamespace(tn=tn, TunnelBrokerService=broker.TunnelBrokerService)


def test_install_registers_tunnel_routes(app, client, auth_headers, install_dirs):
    plugin = plugin_service.install_builtin_extension(SLUG)
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.has_backend is True
    assert plugin.url_prefix == '/api/v1/tunnels'
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert any(r.startswith('/api/v1/tunnels') for r in rules)


# ── re-homed: tunnel_netutil pure helpers ────────────────────────────────────

def test_pick_subnet_first_free(ext):
    cidr, edge, priv = ext.tn.pick_subnet([])
    assert (cidr, edge, priv) == ('10.88.0.0/24', '10.88.0.1', '10.88.0.2')


def test_pick_subnet_skips_used(ext):
    cidr, edge, priv = ext.tn.pick_subnet(['10.88.0.0/24', '10.88.1.0/24'])
    assert (cidr, edge, priv) == ('10.88.2.0/24', '10.88.2.1', '10.88.2.2')


def test_pick_subnet_exhausted(ext):
    used = ['10.88.%d.0/24' % i for i in range(256)]
    with pytest.raises(RuntimeError):
        ext.tn.pick_subnet(used)


def test_interface_name_is_stable_and_kernel_valid(ext):
    name = ext.tn.interface_name_for('3fa9c2b1-dead-beef-0000-111122223333')
    assert name == 'skwg3fa9c2b1'
    assert len(name) <= 15
    assert name.replace('skwg', '').isalnum()


def test_derive_status(ext):
    now = 1_000_000
    assert ext.tn.derive_status(now - 10, now) == 'up'
    assert ext.tn.derive_status(now - 10_000, now) == 'degraded'
    assert ext.tn.derive_status(0, now) == 'pending'
    assert ext.tn.derive_status(now, now, interface_up=False) == 'down'


def test_validate_endpoint_host(ext):
    assert ext.tn.validate_endpoint_host('203.0.113.5') is True
    assert ext.tn.validate_endpoint_host('10.0.0.5') is True
    assert ext.tn.validate_endpoint_host('127.0.0.1') is False
    assert ext.tn.validate_endpoint_host('0.0.0.0') is False
    assert ext.tn.validate_endpoint_host('') is False
    assert ext.tn.validate_endpoint_host('not-an-ip') is False


def test_pick_listen_port(ext):
    assert ext.tn.pick_listen_port([]) == 51820
    assert ext.tn.pick_listen_port([51820]) == 51821
    assert ext.tn.pick_listen_port([51820, 51821, 51823]) == 51822


def test_pick_listen_port_exhausted(ext):
    used = list(range(ext.tn.DEFAULT_LISTEN_PORT,
                       ext.tn.DEFAULT_LISTEN_PORT + ext.tn.LISTEN_PORT_RANGE))
    with pytest.raises(RuntimeError):
        ext.tn.pick_listen_port(used)


def test_diagnose_reachability(ext):
    assert ext.tn.diagnose_reachability(0, None, False)['state'] == 'interface_down'
    assert ext.tn.diagnose_reachability(1_700_000_000, 999, True)['state'] == 'ok'
    assert ext.tn.diagnose_reachability(0, 5, True)['state'] == 'connecting'
    d = ext.tn.diagnose_reachability(0, 600, True)
    assert d['state'] == 'no_handshake'
    assert 'blocked' in d['hint'].lower()


# ── re-homed: panel-authoritative reconcile ──────────────────────────────────

def _server(name, ip=None):
    s = Server(name=name, ip_address=ip, status='online')
    db.session.add(s)
    db.session.commit()
    return s


def _record_send(monkeypatch):
    calls = []

    def fake_send(server_id, action, params=None, user_id=None, timeout=30.0):
        calls.append({'server_id': server_id, 'action': action, 'params': params or {}})
        return {'success': True, 'data': {}}

    monkeypatch.setattr(ar_mod.agent_registry, 'send_command', fake_send)
    return calls


def _tunnel(edge, priv, iface, third):
    t = Tunnel(
        edge_server_id=edge.id, private_server_id=priv.id,
        interface_name=iface, subnet='10.88.%d.0/24' % third,
        edge_wg_ip='10.88.%d.1' % third, private_wg_ip='10.88.%d.2' % third,
        listen_port=51820, edge_pubkey='EDGEPUB', private_pubkey='PRIVPUB',
        status='up',
    )
    db.session.add(t)
    db.session.commit()
    return t


def test_reconcile_private_side(ext, monkeypatch):
    calls = _record_send(monkeypatch)
    edge = _server('edge', ip='203.0.113.9')
    priv = _server('home')
    t = _tunnel(edge, priv, 'skwgrec01', 7)
    db.session.add(ExposedService(tunnel_id=t.id, hostname='jelly.example.com',
                                  port=8096, status='published'))
    db.session.commit()

    res = ext.TunnelBrokerService.reconcile_server(priv.id)
    assert res and res[0]['ok']
    actions = [c['action'] for c in calls]
    assert 'wireguard:interface:up' in actions
    assert 'wireguard:peer:set' in actions
    assert 'wireguard:forward' in actions
    peer = next(c['params'] for c in calls if c['action'] == 'wireguard:peer:set')
    assert peer['public_key'] == 'EDGEPUB'
    assert peer['endpoint'] == '203.0.113.9:51820'
    assert peer['persistent_keepalive'] == 25
    fwd = next(c['params'] for c in calls if c['action'] == 'wireguard:forward')
    assert fwd['listen_port'] == 8096 and fwd['target_port'] == 8096
    assert fwd['listen_ip'] == '10.88.7.2'


def test_reconcile_edge_side(ext, monkeypatch):
    calls = _record_send(monkeypatch)
    edge = _server('edge2', ip='198.51.100.4')
    priv = _server('home2')
    _tunnel(edge, priv, 'skwgrec02', 8)

    ext.TunnelBrokerService.reconcile_server(edge.id)
    actions = [c['action'] for c in calls]
    assert 'wireguard:interface:up' in actions
    assert 'wireguard:peer:set' in actions
    assert 'firewall:allow_port' in actions
    peer = next(c['params'] for c in calls if c['action'] == 'wireguard:peer:set')
    assert peer['public_key'] == 'PRIVPUB'
    assert 'endpoint' not in peer


def test_reconcile_skips_errored_tunnels(ext, monkeypatch):
    calls = _record_send(monkeypatch)
    edge = _server('edge3', ip='192.0.2.7')
    priv = _server('home3')
    t = _tunnel(edge, priv, 'skwgrec03', 9)
    t.status = 'error'
    db.session.commit()

    res = ext.TunnelBrokerService.reconcile_server(priv.id)
    assert res == []
    assert calls == []
