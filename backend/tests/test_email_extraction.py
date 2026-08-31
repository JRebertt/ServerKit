"""Prove the Email extraction (Phase 4, #35; standalone repo since plan 52 Ph2).

A core panel no longer carries the mail-server API; installing serverkit-email
(now a standalone repo — mounted from the sibling checkout, skip when absent)
registers `/api/v1/email` and its routes respond (which also exercises the
extension's relative-import rewiring). Uninstall removes it again.
"""
import sys

import pytest

import app as app_pkg
from app.models.plugin import InstalledPlugin
from tests.conftest import sibling_extension_dir
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


def _install_email_from_sibling(monkeypatch):
    src = sibling_extension_dir(SLUG)
    if not src:
        pytest.skip('serverkit-email checkout not available '
                    '(set SERVERKIT_EMAIL_DIR to its checkout)')
    # The sibling repo pins min_panel_version to the first SDK-1.4.0 release;
    # the working tree may still carry the previous version string.
    from app.utils import version as version_mod
    monkeypatch.setattr(version_mod, 'get_panel_version', lambda: '1.9.11')
    monkeypatch.setattr(plugin_service, 'get_panel_version',
                        lambda: '1.9.11', raising=False)
    return plugin_service.install_from_path(src, force=True)


def test_email_is_no_longer_a_builtin(app):
    available = {e['slug'] for e in plugin_service.list_builtin_extensions()}
    assert SLUG not in available, 'serverkit-email left the tree (plan 52 Ph2)'


def test_install_email_extension_registers_routes(app, client, auth_headers, install_dirs, monkeypatch):
    plugin = _install_email_from_sibling(monkeypatch)
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.has_backend is True
    assert plugin.url_prefix == '/api/v1/email'

    # The blueprint hot-loaded: /api/v1/email/status now exists (not 404) and the
    # status guard passes for an active plugin (not 503). Its handler may 200 or
    # 500 depending on host mail state — we only assert the route is wired.
    resp = client.get('/api/v1/email/status', headers=auth_headers)
    assert resp.status_code not in (404, 503), resp.status_code


def test_uninstall_removes_email_plugin(app, install_dirs, monkeypatch):
    plugin = _install_email_from_sibling(monkeypatch)
    assert plugin_service.uninstall_plugin(plugin.id) is True
    assert InstalledPlugin.query.filter_by(slug=SLUG).first() is None
