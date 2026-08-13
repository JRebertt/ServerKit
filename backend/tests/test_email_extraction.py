"""Prove the Email extraction (Phase 4, #35).

A core panel no longer carries the mail-server API; installing the serverkit-email
builtin registers `/api/v1/email` and its routes respond (which also exercises the
extension's relative-import rewiring). Uninstall removes it again.
"""
import sys

import pytest

import app as app_pkg
from app.models.plugin import InstalledPlugin
from app.services import plugin_service

# Installs plugins, and plugin_service hot-loads their blueprints onto the
# live app. Flask refuses register_blueprint once an app has served a
# request, so these need a private app (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app

SLUG = 'serverkit-email'
_PKG = f'app.plugins.{SLUG}'


def test_core_has_no_email_routes(app):
    """The mail-server API is gone from core after extraction.

    Exception: /api/v1/email/dns-providers* stayed core (moved back after the
    extraction broke the Connections DNS tiles on panels without the email
    extension) — it keeps the historical path but is not mail-server API.
    """
    rules = [r.rule for r in app.url_map.iter_rules()]
    email_rules = [r for r in rules if r.startswith('/api/v1/email')]
    assert all(r.startswith('/api/v1/email/dns-providers') for r in email_rules)
    assert email_rules  # the core DNS-provider routes themselves exist


@pytest.fixture
def install_dirs(tmp_path, monkeypatch):
    """Point the install targets at temp dirs AND make app.plugins resolve the
    temp backend dir so the hot-loaded blueprint imports from there (not the repo).
    """
    backend = tmp_path / 'plugins_backend'
    frontend = tmp_path / 'plugins_frontend'
    backend.mkdir()
    frontend.mkdir()
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))

    added = str(backend)
    import importlib
    app_pkg_plugins = importlib.import_module('app.plugins')
    if added not in app_pkg_plugins.__path__:
        app_pkg_plugins.__path__.append(added)

    yield {'backend': backend, 'frontend': frontend}

    # Clean the import side effects so other tests see a pristine module graph.
    if added in app_pkg_plugins.__path__:
        app_pkg_plugins.__path__.remove(added)
    for name in list(sys.modules):
        if name == _PKG or name.startswith(_PKG + '.'):
            del sys.modules[name]


def test_install_email_extension_registers_routes(app, client, auth_headers, install_dirs):
    # The real builtin folder is discovered from the repo's builtin-extensions/.
    available = {e['slug'] for e in plugin_service.list_builtin_extensions()}
    assert SLUG in available, 'serverkit-email builtin folder should exist'

    plugin = plugin_service.install_builtin_extension('serverkit-email')
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.has_backend is True
    assert plugin.url_prefix == '/api/v1/email'

    # The blueprint hot-loaded: /api/v1/email/status now exists (not 404) and the
    # status guard passes for an active plugin (not 503). Its handler may 200 or
    # 500 depending on host mail state — we only assert the route is wired.
    resp = client.get('/api/v1/email/status', headers=auth_headers)
    assert resp.status_code not in (404, 503), resp.status_code


def test_uninstall_removes_email_plugin(app, install_dirs):
    plugin = plugin_service.install_builtin_extension('serverkit-email')
    assert plugin_service.uninstall_plugin(plugin.id) is True
    assert InstalledPlugin.query.filter_by(slug=SLUG).first() is None
