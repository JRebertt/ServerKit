"""Prove the Cloud Provisioning extraction (plan 47 Phase 2).

A fresh panel no longer carries the cloud-provider API in core; installing the
serverkit-cloud-provision builtin registers `/api/v1/cloud`. The CloudProvider
model stays core (G2). Also covers the one-shot backend re-acquisition that keeps
upgraded panels (which installed the extension frontend-only) from losing the API.
"""
import importlib
import sys

import pytest

from app import db
from app.models.plugin import InstalledPlugin
from app.services import plugin_service

# Installs plugins, and plugin_service hot-loads their blueprints onto the
# live app. Flask refuses register_blueprint once an app has served a
# request, so these need a private app (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app

SLUG = 'serverkit-cloud-provision'
_PKG = f'app.plugins.{SLUG}'


def test_core_has_no_cloud_routes(app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert [r for r in rules if r.startswith('/api/v1/cloud/')] == []


def test_core_import_of_cloud_service_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('app.services.cloud_provisioning_service')


def test_cloud_in_converted_builtin_slugs():
    from app.services.extension_migration import CONVERTED_BUILTIN_SLUGS
    assert SLUG in CONVERTED_BUILTIN_SLUGS


def test_cloud_model_stays_core():
    """G2: the CloudProvider/CloudServer models remain importable from core."""
    from app.models.cloud_server import CloudProvider, CloudServer  # noqa: F401


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


def test_install_cloud_extension_registers_routes(app, client, auth_headers, install_dirs):
    available = {e['slug'] for e in plugin_service.list_builtin_extensions()}
    assert SLUG in available

    plugin = plugin_service.install_builtin_extension(SLUG)
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.has_backend is True
    assert plugin.url_prefix == '/api/v1/cloud'

    resp = client.get('/api/v1/cloud/providers', headers=auth_headers)
    assert resp.status_code not in (404, 503), resp.status_code


def test_cloud_provider_secret_encrypted_at_rest(app, install_dirs):
    """The extracted service still encrypts provider secrets at rest (moved here
    from test_provider_secret_encryption.py)."""
    plugin_service.install_builtin_extension(SLUG)
    from app.models.cloud_server import CloudProvider
    from app.utils.crypto import is_encrypted, decrypt_secret_safe

    svc_mod = importlib.import_module(f'{_PKG}.cloud_provisioning_service')
    CloudProvisioningService = svc_mod.CloudProvisioningService

    p = CloudProvisioningService.create_provider(
        {'provider_type': 'digitalocean', 'name': 'do', 'api_key': 'do-token-xyz'})
    row = CloudProvider.query.get(p.id)
    assert row.api_key_encrypted != 'do-token-xyz'
    assert is_encrypted(row.api_key_encrypted) is True
    assert decrypt_secret_safe(row.api_key_encrypted) == 'do-token-xyz'
    assert CloudProvisioningService._auth_headers(row)['Authorization'] == 'Bearer do-token-xyz'


def test_backend_acquisition_upgrades_frontend_only_install(app, install_dirs):
    """An upgraded panel that installed the extension frontend-only re-acquires
    the now-extracted backend (plan 47 Phase 2 migration)."""
    from app.services import extension_migration

    # Simulate the pre-plan-47 state: a frontend-only install (API came from core)
    row = InstalledPlugin(
        name=SLUG, display_name='Cloud Provisioning', slug=SLUG, version='1.0.0',
        source_type='builtin', status=InstalledPlugin.STATUS_ACTIVE,
    )
    row.has_backend = False
    row.has_frontend = True
    db.session.add(row)
    db.session.commit()

    extension_migration.run_backend_acquisition()

    refreshed = InstalledPlugin.query.filter_by(slug=SLUG).first()
    assert refreshed.has_backend is True
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert any(r.startswith('/api/v1/cloud/') for r in rules)
