"""Prove the one-shot auto-install of converted builtin extensions (D3).

An *upgraded* panel (has users) auto-installs a converted builtin once; a *fresh*
panel (no users yet) does not — it sees the extension in the Marketplace. Either
way the pass is idempotent and recorded so it never repeats.
"""
import json

import pytest
from werkzeug.security import generate_password_hash

from app import db
from app.models.plugin import InstalledPlugin
from app.models.user import User
from app.services import plugin_service, extension_migration

# Installs plugins, and plugin_service hot-loads their blueprints onto the
# live app. Flask refuses register_blueprint once an app has served a
# request, so these need a private app (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


@pytest.fixture
def demo_builtin(tmp_path, monkeypatch):
    """Redirect plugin dirs to temp, ship one converted builtin ('serverkit-demo')."""
    backend = tmp_path / 'backend_plugins'
    frontend = tmp_path / 'frontend_plugins'
    builtin = tmp_path / 'builtin_extensions'
    for d in (backend, frontend, builtin):
        d.mkdir()
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))
    monkeypatch.setattr(plugin_service, 'BUILTIN_EXTENSIONS_DIR', str(builtin))
    monkeypatch.setattr(extension_migration, 'CONVERTED_BUILTIN_SLUGS', ['serverkit-demo'])

    folder = builtin / 'serverkit-demo'
    (folder / 'frontend').mkdir(parents=True)
    manifest = {
        'name': 'serverkit-demo', 'display_name': 'Demo', 'version': '1.0.0',
        'category': 'utility',
        'contributions': {'nav': [{'id': 'demo', 'label': 'Demo', 'route': '/demo'}]},
    }
    (folder / 'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
    (folder / 'frontend' / 'index.jsx').write_text('export function P(){return null;}\n')
    return builtin


def _make_user():
    u = User(email='u@test.local', username='someuser',
             password_hash=generate_password_hash('x'),
             role=User.ROLE_ADMIN, is_active=True)
    db.session.add(u)
    db.session.commit()


def test_upgrade_auto_installs_converted_builtin(app, demo_builtin):
    _make_user()  # existing install
    extension_migration.run_auto_install()

    p = InstalledPlugin.query.filter_by(slug='serverkit-demo').first()
    assert p is not None
    assert p.status == InstalledPlugin.STATUS_ACTIVE

    # Marker recorded → second run is a no-op (no error, still one row).
    extension_migration.run_auto_install()
    assert InstalledPlugin.query.filter_by(slug='serverkit-demo').count() == 1


def test_fresh_install_does_not_auto_install(app, demo_builtin):
    # No users → brand-new panel.
    extension_migration.run_auto_install()
    assert InstalledPlugin.query.filter_by(slug='serverkit-demo').first() is None
    # But it was marked processed, so a later boot (even once users exist) won't
    # retroactively install it.
    assert 'serverkit-demo' in extension_migration._processed_slugs()


def test_user_uninstall_is_not_undone(app, demo_builtin):
    _make_user()
    extension_migration.run_auto_install()
    p = InstalledPlugin.query.filter_by(slug='serverkit-demo').first()
    plugin_service.uninstall_plugin(p.id)
    assert InstalledPlugin.query.filter_by(slug='serverkit-demo').first() is None

    # Re-running must NOT reinstall — the one-shot already happened.
    extension_migration.run_auto_install()
    assert InstalledPlugin.query.filter_by(slug='serverkit-demo').first() is None


@pytest.fixture
def gated_gpu_builtin(tmp_path, monkeypatch):
    """Ship 'serverkit-gpu' as a gated builtin (no ungated converted slugs)."""
    backend = tmp_path / 'backend_plugins'
    frontend = tmp_path / 'frontend_plugins'
    builtin = tmp_path / 'builtin_extensions'
    for d in (backend, frontend, builtin):
        d.mkdir()
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))
    monkeypatch.setattr(plugin_service, 'BUILTIN_EXTENSIONS_DIR', str(builtin))
    monkeypatch.setattr(extension_migration, 'CONVERTED_BUILTIN_SLUGS', [])

    folder = builtin / 'serverkit-gpu'
    (folder / 'frontend').mkdir(parents=True)
    manifest = {
        'name': 'serverkit-gpu', 'display_name': 'GPU Monitor', 'version': '1.0.0',
        'category': 'monitoring',
        'contributions': {'nav': [{'id': 'gpu', 'label': 'GPU', 'route': '/gpu'}]},
    }
    (folder / 'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
    (folder / 'frontend' / 'index.jsx').write_text('export function P(){return null;}\n')
    return builtin


def test_upgrade_without_gpu_does_not_install_but_marks(app, gated_gpu_builtin, monkeypatch):
    _make_user()  # existing install (upgrade path)
    # App boot already ran a fresh-install pass that marked converted/gated slugs;
    # clear the marker so this test genuinely exercises the gate.
    extension_migration._save_processed(set())
    monkeypatch.setitem(extension_migration.GATED_BUILTIN_SLUGS, 'serverkit-gpu',
                        lambda: False)
    extension_migration.run_auto_install()

    # Gate false → not installed, but recorded so it never retries.
    assert InstalledPlugin.query.filter_by(slug='serverkit-gpu').first() is None
    assert 'serverkit-gpu' in extension_migration._processed_slugs()


def test_upgrade_with_gpu_installs(app, gated_gpu_builtin, monkeypatch):
    _make_user()  # existing install (upgrade path)
    # Clear the boot-time processed marker (see note above) so the gate decides.
    extension_migration._save_processed(set())
    monkeypatch.setitem(extension_migration.GATED_BUILTIN_SLUGS, 'serverkit-gpu',
                        lambda: True)
    extension_migration.run_auto_install()

    p = InstalledPlugin.query.filter_by(slug='serverkit-gpu').first()
    assert p is not None
    assert p.status == InstalledPlugin.STATUS_ACTIVE


@pytest.fixture
def retired_leftovers(tmp_path, monkeypatch):
    """Plant leftover files for a retired extension slug in both plugin dirs."""
    backend = tmp_path / 'backend_plugins'
    frontend = tmp_path / 'frontend_plugins'
    for d in (backend, frontend):
        (d / 'serverkit-oldthing').mkdir(parents=True)
    (backend / 'serverkit-oldthing' / '__init__.py').write_text('')
    (frontend / 'serverkit-oldthing' / 'index.jsx').write_text("import 'gone';\n")
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))
    monkeypatch.setattr(extension_migration, 'RETIRED_EXTENSION_SLUGS',
                        ['serverkit-oldthing'])
    return backend, frontend


def test_retired_extension_sweep(app, retired_leftovers):
    """Retired leftovers (files + row) are swept at boot; the sweep is idempotent.

    This is the serverkit-workflows scenario: a stale dir in the live tree was
    carried into every update by the plugin preservation step, where its dead
    imports broke the frontend build.
    """
    backend, frontend = retired_leftovers
    db.session.add(InstalledPlugin(
        name='serverkit-oldthing', display_name='Old Thing',
        slug='serverkit-oldthing', version='1.0.0'))
    db.session.commit()

    extension_migration.remove_retired_extensions()

    assert not (backend / 'serverkit-oldthing').exists()
    assert not (frontend / 'serverkit-oldthing').exists()
    assert InstalledPlugin.query.filter_by(slug='serverkit-oldthing').first() is None

    # Second sweep on an already-clean tree is a quiet no-op.
    extension_migration.remove_retired_extensions()
