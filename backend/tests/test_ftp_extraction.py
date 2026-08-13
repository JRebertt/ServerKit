"""Prove the FTP extraction (plan 47 Phase 2).

A fresh panel no longer carries the FTP API in core; installing the
serverkit-ftp builtin registers `/api/v1/ftp` and its routes respond (which also
exercises the extension's relative-import rewiring). Uninstall removes it again.
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

SLUG = 'serverkit-ftp'
_PKG = f'app.plugins.{SLUG}'


def test_core_has_no_ftp_routes(app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert [r for r in rules if r.startswith('/api/v1/ftp')] == []


def test_core_import_of_ftp_service_is_gone():
    """The FTP service left core — importing it from app.services must fail."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('app.services.ftp_service')


def test_ftp_in_converted_builtin_slugs():
    from app.services.extension_migration import CONVERTED_BUILTIN_SLUGS
    assert SLUG in CONVERTED_BUILTIN_SLUGS


@pytest.fixture
def install_dirs(tmp_path, monkeypatch):
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

    if added in app_pkg_plugins.__path__:
        app_pkg_plugins.__path__.remove(added)
    for name in list(sys.modules):
        if name == _PKG or name.startswith(_PKG + '.'):
            del sys.modules[name]


def test_install_ftp_extension_registers_routes(app, client, auth_headers, install_dirs):
    available = {e['slug'] for e in plugin_service.list_builtin_extensions()}
    assert SLUG in available, 'serverkit-ftp builtin folder should exist'

    plugin = plugin_service.install_builtin_extension(SLUG)
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.has_backend is True
    assert plugin.url_prefix == '/api/v1/ftp'

    resp = client.get('/api/v1/ftp/status', headers=auth_headers)
    assert resp.status_code not in (404, 503), resp.status_code


def test_uninstall_removes_ftp_plugin(app, install_dirs):
    plugin = plugin_service.install_builtin_extension(SLUG)
    assert plugin_service.uninstall_plugin(plugin.id) is True
    assert InstalledPlugin.query.filter_by(slug=SLUG).first() is None
