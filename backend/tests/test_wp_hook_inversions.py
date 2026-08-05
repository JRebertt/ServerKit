"""Plan 52 Phase 3 — the WordPress hook inversions (tasks 13/15/16/17/18).

Core keeps each engine and a registration seam; the WordPress extension fills
the seams at load via its manifest ``core_hooks`` entry (run at install and on
every boot by ``extension_lifecycle.register_capabilities``).

Every hook is exercised twice:

* WP present — the flagship seeds on every test boot, so ``app`` boots with
  the seams filled; behavior must be identical to the pre-inversion core.
* WP absent — the extension's seam registrations are dropped (simulating an
  uninstalled/disabled extension); the feature must be absent *gracefully*:
  clear "provider missing" errors, hidden cards/types, no crashes.
"""
import contextlib
import importlib

import pytest

from app import db
from app.models import Application
from app.models.backup_policy import BackupPolicy
from app.models.wordpress_site import WordPressSite
from app.services import backup_kind_registry, event_service
from app.services.event_service import EventService
from app.services.backup_policy_service import BackupPolicyError, BackupPolicyService
from app.services.template_service import TemplateService

SLUG = 'serverkit-wordpress'


@contextlib.contextmanager
def wp_hooks_absent():
    """Drop every WP seam registration (simulating the extension being gone),
    then restore by re-running the extension's idempotent register() — which
    also proves per-boot re-registration refills a cleared seam."""
    backup_kind_registry._KINDS.pop('wordpress_site', None)
    event_service.clear_registered_event_types()
    TemplateService.unregister_template_provider(SLUG)
    try:
        yield
    finally:
        _core_hooks().register()


def _core_hooks():
    return importlib.import_module(f'app.plugins.{SLUG}.core_hooks')


def _wp_site(name='hook-site'):
    app_row = Application(name=name, app_type='wordpress', status='running',
                          root_path='/srv/hook-site', user_id=1)
    db.session.add(app_row)
    db.session.flush()
    site = WordPressSite(application_id=app_row.id)
    db.session.add(site)
    db.session.commit()
    return site


# --------------------------------------------------------------------------- #
# The seam itself: manifest core_hooks → registrations at boot
# --------------------------------------------------------------------------- #

def test_core_hooks_registered_at_boot(app):
    """A stock boot (flagship seeded) fills all three seams via the manifest
    core_hooks entry — this is what makes 'WP present' behavior identical to
    the pre-inversion core."""
    plugin_manifest_hooks = 'core_hooks:register'
    assert backup_kind_registry.get('wordpress_site') is not None
    assert any(e['type'] == 'wordpress.created'
               for e in EventService.get_available_events())
    assert TemplateService.template_available('wordpress')
    # The manifest really declares the seam (not an import side effect).
    from app.models.plugin import InstalledPlugin
    plugin = InstalledPlugin.query.filter_by(slug=SLUG).first()
    assert plugin.manifest.get('core_hooks') == plugin_manifest_hooks


def test_core_hooks_registration_is_idempotent(app):
    hooks = _core_hooks()
    hooks.register()
    hooks.register()
    events = [e['type'] for e in EventService.get_available_events()]
    assert events.count('wordpress.created') == 1


# --------------------------------------------------------------------------- #
# Task 13 — backup target type 'wordpress_site'
# --------------------------------------------------------------------------- #

def test_backup_kind_present_resolves_like_before(app):
    site = _wp_site()
    policy = BackupPolicyService.get_or_create_policy('wordpress_site', site.id)
    target = BackupPolicyService._resolve_target(policy)
    assert target['target_type'] == 'wordpress_site'
    assert target['name'] == 'hook-site'
    assert target['root_path'] == '/srv/hook-site'
    assert target['site'].id == site.id
    # Restore is offered (the provider ships a restore handler + scopes).
    assert backup_kind_registry.supports_restore('wordpress_site') is True


def test_backup_kind_absent_is_a_clear_provider_missing(app):
    site = _wp_site()
    # Row created directly — with the provider gone, validation alone refuses.
    policy = BackupPolicy(target_type='wordpress_site', target_id=site.id)
    db.session.add(policy)
    db.session.commit()

    with wp_hooks_absent():
        with pytest.raises(BackupPolicyError, match='target_type must be one of'):
            BackupPolicyService.validate_target_type('wordpress_site')
        with pytest.raises(BackupPolicyError, match='no provider'):
            BackupPolicyService._resolve_target(policy)


def test_backup_target_types_endpoint_reflects_provider(app, client, auth_headers):
    resp = client.get('/api/v1/backups/target-types', headers=auth_headers)
    assert resp.status_code == 200
    types = {t['target_type']: t for t in resp.get_json()['target_types']}
    # Core set always present; the WP kind comes from the extension.
    assert {'application', 'database', 'files', 'server'} <= set(types)
    assert 'wordpress_site' in types
    assert types['wordpress_site']['source'] == 'extension'
    assert 'database' in types['wordpress_site']['restore_scopes']

    with wp_hooks_absent():
        resp = client.get('/api/v1/backups/target-types', headers=auth_headers)
        gone = {t['target_type'] for t in resp.get_json()['target_types']}
        assert 'wordpress_site' not in gone


def test_policy_list_flags_provider_missing(app, client, auth_headers):
    site = _wp_site()
    BackupPolicyService.get_or_create_policy('wordpress_site', site.id)

    resp = client.get('/api/v1/backups/policies', headers=auth_headers)
    flagged = {p['target_type']: p['provider_missing']
               for p in resp.get_json()['policies']}
    assert flagged['wordpress_site'] is False

    with wp_hooks_absent():
        resp = client.get('/api/v1/backups/policies', headers=auth_headers)
        flagged = {p['target_type']: p['provider_missing']
                   for p in resp.get_json()['policies']}
        assert flagged['wordpress_site'] is True


# --------------------------------------------------------------------------- #
# Task 15 — event catalog
# --------------------------------------------------------------------------- #

def test_wp_event_types_present(app):
    types = {e['type'] for e in EventService.get_available_events()}
    assert {'wordpress.created', 'wordpress.site_down', 'wordpress.deployed',
            'wordpress.update_rolled_back'} <= types
    # Core constant keeps only core events now.
    core_types = {e['type'] for e in event_service.EVENT_CATALOG}
    assert not {t for t in core_types if t.startswith('wordpress.')}


def test_wp_event_types_absent_graceful(app, client, auth_headers):
    with wp_hooks_absent():
        types = {e['type'] for e in EventService.get_available_events()}
        assert not {t for t in types if t.startswith('wordpress.')}
        # The catalog endpoint keeps working — WP types simply don't exist.
        resp = client.get('/api/v1/event-subscriptions/events', headers=auth_headers)
        assert resp.status_code == 200
        assert not [e for e in resp.get_json()['events']
                    if e['type'].startswith('wordpress.')]


# --------------------------------------------------------------------------- #
# Task 16 — templates
# --------------------------------------------------------------------------- #

def test_wp_templates_listed_when_present(app):
    ids = {t['id'] for t in TemplateService.list_local_templates()}
    assert {'wordpress', 'wordpress-external-db'} <= ids
    assert TemplateService.get_template('wordpress')['success'] is True


def test_wp_templates_hidden_when_absent(app):
    with wp_hooks_absent():
        ids = {t['id'] for t in TemplateService.list_local_templates()}
        assert 'wordpress' not in ids
        assert 'wordpress-external-db' not in ids
        all_ids = {t['id'] for t in TemplateService.list_all_templates()}
        assert 'wordpress' not in all_ids
        result = TemplateService.get_template('wordpress')
        assert result['success'] is False
        assert 'serverkit-wordpress' in result['error']


def test_wp_template_install_refused_when_absent(app):
    with wp_hooks_absent():
        result = TemplateService.install_template('wordpress', 'wp-x')
        assert result['success'] is False
        assert 'serverkit-wordpress' in result['error']


def test_external_db_preflight_flows_through_provider(app, monkeypatch):
    """The wordpress-external-db connection preflight used to be a hardcoded
    core branch; now core dispatches to the provider's validate hook."""
    calls = []
    monkeypatch.setattr(
        TemplateService, 'validate_mysql_connection',
        lambda **kwargs: calls.append(kwargs) or {'success': False, 'error': 'nope'})
    template = TemplateService.get_template('wordpress-external-db')['template']
    result = TemplateService._prepare_install_variables(
        'wordpress-external-db', template, 'wp-ext', {
            'DB_HOST': 'db.example.test', 'DB_NAME': 'wp',
            'DB_USER': 'u', 'DB_PASSWORD': 'p',
        })
    assert result['success'] is False
    assert result['error'] == 'Database connection failed: nope'
    assert calls and calls[0]['host'] == 'db.example.test'

    # Provider absent → the hook never fires (no validate calls at all).
    with wp_hooks_absent():
        calls.clear()
        provider = TemplateService.provider_for_template('wordpress-external-db')
        assert provider is None


# --------------------------------------------------------------------------- #
# Task 17 — status pages / monitors
# --------------------------------------------------------------------------- #

def test_monitor_site_binding_requires_existing_site(app):
    from app.services.monitor_service import MonitorService
    # WP absent (no such site): binding fails loudly instead of orphaning.
    with pytest.raises(ValueError, match='WordPress extension'):
        MonitorService.create({
            'name': 'Orphan', 'wordpress_site_id': 9999, 'check_target': '',
        })
    # WP present (site exists): identical to today's behavior.
    site = _wp_site()
    monitor = MonitorService.create({
        'name': 'Bound', 'wordpress_site_id': site.id, 'check_target': '',
    })
    assert monitor.wordpress_site_id == site.id
    # Re-binding to a gone site via update is refused too.
    with pytest.raises(ValueError, match='WordPress extension'):
        MonitorService.update(monitor.id, {'wordpress_site_id': 9999})


def test_health_sweep_noops_with_no_wp_sites(app):
    """The core health sweep iterates managed WP sites; with none (extension
    absent) it is a no-op, not an error."""
    from app.jobs.builtin_handlers import run_health_checks
    assert WordPressSite.query.count() == 0
    run_health_checks()  # must not raise


# --------------------------------------------------------------------------- #
# Task 18 — analytics ↔ WordPress stays ext↔ext (no core middleman)
# --------------------------------------------------------------------------- #

def test_no_core_or_wp_module_references_analytics_extension():
    """Static guard: neither core's hook engines nor the WP extension backend
    may name serverkit-analytics. The mu-plugin integration lives entirely in
    the analytics extension (which uses only the D1 core models), and the WP
    side feature-detects it — there is nothing to route through core."""
    import os
    repo_root = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
    wp_backend = os.path.join(repo_root, 'builtin-extensions', SLUG, 'backend')
    core_files = [
        'app/services/event_service.py',
        'app/services/backup_policy_service.py',
        'app/services/backup_kind_registry.py',
        'app/services/template_service.py',
        'app/services/monitor_service.py',
    ]
    backend_root = os.path.join(repo_root, 'backend')
    targets = []
    for name in os.listdir(wp_backend):
        if name.endswith('.py'):
            targets.append(os.path.join(wp_backend, name))
    targets.extend(os.path.join(backend_root, f) for f in core_files)

    for path in targets:
        with open(path, 'r', encoding='utf-8') as fh:
            content = fh.read()
        assert 'serverkit-analytics' not in content, path
        assert 'serverkit_analytics' not in content, path


def test_ext_to_ext_seam_absent_side_returns_default(app):
    """get_installed_extension_attr — the seam an ext↔ext call goes through —
    returns the default when the callee extension is absent (analytics is not
    installed in this test panel), never raises."""
    from app.services.plugin_service import get_installed_extension_attr
    assert get_installed_extension_attr(
        'serverkit-analytics', 'wp_integration', 'inject', default=None) is None
