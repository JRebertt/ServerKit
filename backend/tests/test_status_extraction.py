"""Prove the Status Pages extraction (plan 47 Phase 2).

The status-pages blueprint (public + management routes) and its service move into
serverkit-status; the StatusPage/StatusComponent models stay core (G2). Core's
WordPress health-check job syncs status components only when the extension is
installed (no crash on a lean panel). Re-homes the status-page mutation authz
test from test_api_authz_hardening.py.
"""
import importlib
import sys

import pytest
from werkzeug.security import generate_password_hash
from flask_jwt_extended import create_access_token

from app import db
from app.models.user import User
from app.models.plugin import InstalledPlugin
from app.services import plugin_service

# Installs plugins, and plugin_service hot-loads their blueprints onto the
# live app. Flask refuses register_blueprint once an app has served a
# request, so these need a private app (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app

SLUG = 'serverkit-status'
_PKG = f'app.plugins.{SLUG}'


def test_core_has_no_status_page_routes(app):
    """The status-pages management/public routes are gone from core (the
    /api/v1/status/apps container-status aggregator is a different blueprint)."""
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert '/api/v1/status/public/<slug>' not in rules
    assert '/api/v1/status/' not in rules
    assert not any('observability/status-pages' in r for r in rules)


def test_core_import_of_status_service_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('app.services.status_page_service')


def test_status_in_converted_builtin_slugs():
    from app.services.extension_migration import CONVERTED_BUILTIN_SLUGS
    assert SLUG in CONVERTED_BUILTIN_SLUGS


def test_status_models_stay_core():
    from app.models.status_page import (  # noqa: F401
        StatusPage, StatusComponent)


def test_health_check_job_no_ops_without_extension(app):
    """run_health_checks must not crash on a lean panel (no serverkit-status)."""
    from app.jobs.builtin_handlers import run_health_checks
    run_health_checks()  # no production sites, no extension — clean no-op


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


def _mk_user(username, role):
    u = User(email=f'{username}@t.local', username=username, role=role,
             is_active=True, password_hash=generate_password_hash('x'))
    db.session.add(u)
    db.session.commit()
    return u


def _token(uid):
    return {'Authorization': f'Bearer {create_access_token(identity=uid)}'}


def test_install_registers_status_routes(app, client, auth_headers, install_dirs):
    plugin = plugin_service.install_builtin_extension(SLUG)
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.has_backend is True
    assert plugin.url_prefix == '/api/v1/status'
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert '/api/v1/status/public/<slug>' in rules


def test_status_page_mutations_admin_only(app, client, install_dirs):
    """Reads open to any authed user; every mutation is admin-only (relocated
    from test_api_authz_hardening.py — now runs against the installed extension)."""
    plugin_service.install_builtin_extension(SLUG)
    dev = _mk_user('sp_dev', 'developer')
    admin = _mk_user('sp_admin', 'admin')

    assert client.get('/api/v1/status/', headers=_token(dev.id)).status_code == 200

    r = client.post('/api/v1/status/', json={'name': 'Ops', 'slug': 'ops'},
                    headers=_token(admin.id))
    assert r.status_code == 201
    page_id = r.get_json()['id']

    assert client.post('/api/v1/status/', json={'name': 'X', 'slug': 'x'},
                       headers=_token(dev.id)).status_code == 403
    assert client.put(f'/api/v1/status/{page_id}', json={'name': 'Y'},
                      headers=_token(dev.id)).status_code == 403
    assert client.delete(f'/api/v1/status/{page_id}',
                         headers=_token(dev.id)).status_code == 403
    assert client.post(f'/api/v1/status/{page_id}/components',
                       json={'name': 'c', 'check_type': 'http'},
                       headers=_token(dev.id)).status_code == 403
    assert client.post(f'/api/v1/status/{page_id}/incidents', json={'title': 't'},
                       headers=_token(dev.id)).status_code == 403


@pytest.mark.parametrize('persona', ['viewer', 'member', 'foreign'])
def test_status_component_check_admin_only(app, client, scoping_rbac, install_dirs, persona):
    """POST /status/components/<id>/check is a write-ish mutation → admin-only
    (relocated from test_api_authz_hardening.py, now against the extension)."""
    plugin_service.install_builtin_extension(SLUG)
    url = '/api/v1/status/components/999999/check'
    assert client.post(url, headers=getattr(scoping_rbac, persona)).status_code == 403, persona
    assert client.post(url, headers=scoping_rbac.admin).status_code != 403
