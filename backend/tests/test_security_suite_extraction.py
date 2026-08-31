"""Prove the security-suite split (plan 47 Ph3b-4 / plan 55 Phase 3).

The install-gated security tools left core for standalone extensions
(serverkit-clamav, serverkit-fail2ban, serverkit-lynis, serverkit-auto-updates,
serverkit-image-scan). A core panel keeps only the zero-host-package baseline:
status/config, legacy integrity, suspicious activity, events, SSH keys, IP
lists, the audit and scoped FIM. These tests pin the absent-extension shape —
the moved prefixes 404 (blueprint never registered, so routing wins before
auth), the core surfaces still answer, and the probes core kept (fail2ban
status on Fail2banJailService) still drive Setup Health and the audit.
"""
import pytest

from app.services.security_service import SecurityService
from app.services.fail2ban_jail_service import Fail2banJailService


# Route paths that moved to security extensions, one representative per
# extension surface. On a lean panel every one of them is unrouted (404).
MOVED_ROUTE_PREFIXES = [
    '/api/v1/security/clamav/status',        # serverkit-clamav
    '/api/v1/security/scan/status',          # serverkit-clamav
    '/api/v1/security/quarantine',           # serverkit-clamav
    '/api/v1/security/yara/rules',           # serverkit-clamav
    '/api/v1/security/fail2ban/status',      # serverkit-fail2ban
    '/api/v1/security/lynis/status',         # serverkit-lynis
    '/api/v1/security/auto-updates/status',  # serverkit-auto-updates
    '/api/v1/security/image-scans/install',  # serverkit-image-scan
    '/api/v1/security/sboms/1',              # serverkit-image-scan
]


def test_moved_security_routes_are_unrouted(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    for path in MOVED_ROUTE_PREFIXES:
        static_prefix = path.replace('/1', '')
        offenders = [r for r in rules if r.startswith(static_prefix)]
        assert not offenders, f'{path}: still routed in core: {offenders}'


def test_moved_route_404s_before_auth(client):
    """No blueprint => plain 404, no auth prompt, no 500."""
    for path in MOVED_ROUTE_PREFIXES:
        resp = client.get(path)
        assert resp.status_code == 404, f'{path} -> {resp.status_code}'


def test_core_security_routes_survive(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    for path in [
        '/api/v1/security/status',
        '/api/v1/security/config',
        '/api/v1/security/audit',
        '/api/v1/security/events',
        '/api/v1/security/failed-logins',
        '/api/v1/security/ssh-keys',
        '/api/v1/security/ip-lists',
        '/api/v1/security/integrity/check',
        '/api/v1/security/fim',
    ]:
        assert path in rules, f'{path} missing from the lean core surface'


def test_security_summary_is_core_only(app):
    """The summary no longer reaches for scanner state the core doesn't own."""
    with app.app_context():
        summary = SecurityService.get_security_summary()
    assert 'clamav' not in summary
    assert 'scan_status' not in summary
    # Core-owned fields stay.
    assert 'file_integrity' in summary
    assert 'recent_alerts' in summary
    assert 'notifications_enabled' in summary


def test_security_service_shed_the_moved_buckets():
    """The moved tool methods are gone from the core service (no zombies)."""
    for gone in [
        'get_clamav_status', 'install_clamav', 'scan_directory',
        'quarantine_file', 'get_fail2ban_status', 'install_fail2ban',
        'ban_ip', 'get_lynis_status', 'run_lynis_scan',
        'get_auto_updates_status', 'register_jobs',
    ]:
        assert not hasattr(SecurityService, gone), f'SecurityService.{gone} still exists'


def test_jail_service_owns_the_fail2ban_probes():
    """Core seam: probes + unban live on the jail write-half service."""
    for kept in ['get_fail2ban_status', 'get_fail2ban_jail_status', 'unban_ip']:
        assert hasattr(Fail2banJailService, kept), f'Fail2banJailService.{kept} missing'


def test_moved_services_left_the_tree():
    for module in [
        'app.services.malware_scan_service',
        'app.services.yara_scan_service',
        'app.services.image_scanner_service',
    ]:
        with pytest.raises(ImportError):
            __import__(module)


def test_no_core_registration_of_extension_job_kinds(app):
    """The three scanner job kinds register via the extensions' manifest
    `jobs` key — a lean core must not have them (a queued job on a panel
    whose extension was removed fails loudly instead of running stale code).
    """
    from app.jobs import registry
    for kind in ('security.malware_scan', 'security.lynis_scan', 'security.image_scan'):
        assert not registry.is_registered(kind), f'{kind} registered in lean core'


def test_image_scan_models_stay_core():
    """Core data seam (plan 52 D1): the extension reads/writes core tables."""
    from app.models import ImageVulnerabilityScan, SbomArtifact
    assert ImageVulnerabilityScan.__tablename__ == 'image_vulnerability_scans'
    assert SbomArtifact.__tablename__ == 'sbom_artifacts'


# ---------------------------------------------------------------------------
# Upgrade parity: run_registry_auto_install (the GATED_BUILTIN_SLUGS analogue
# for registry-only security extensions).
# ---------------------------------------------------------------------------

def _reset_registry_marker(app):
    from app.services.settings_service import SettingsService
    with app.app_context():
        SettingsService.set('extensions.registry_auto_installed_slugs', '')


def test_registry_auto_install_defers_until_entry_published(app, monkeypatch):
    """Host tool present + entry unpublished => no burn, retried next boot."""
    from app.services import extension_migration as em

    _reset_registry_marker(app)
    monkeypatch.setattr(em, '_looks_like_existing_install', lambda: True)
    monkeypatch.setattr(em, 'REGISTRY_GATED_SLUGS',
                        {'serverkit-fail2ban': lambda: True})
    from app.services import registry_service
    monkeypatch.setattr(registry_service, 'get_entry', lambda slug: None)

    with app.app_context():
        em.run_registry_auto_install()
        assert 'serverkit-fail2ban' not in em._registry_processed_slugs()


def test_registry_auto_install_installs_once_when_published(app, monkeypatch):
    from app.services import extension_migration as em

    _reset_registry_marker(app)
    monkeypatch.setattr(em, '_looks_like_existing_install', lambda: True)
    monkeypatch.setattr(em, 'REGISTRY_GATED_SLUGS',
                        {'serverkit-fail2ban': lambda: True})
    from app.services import registry_service
    monkeypatch.setattr(registry_service, 'get_entry',
                        lambda slug: {'slug': slug, 'source': 'https://x/z.zip'})

    calls = []
    from app.services import plugin_service
    monkeypatch.setattr(plugin_service, 'install_registry_extension',
                        lambda slug, user_id=None: calls.append(slug))

    with app.app_context():
        em.run_registry_auto_install()
        assert calls == ['serverkit-fail2ban']
        assert 'serverkit-fail2ban' in em._registry_processed_slugs()
        # Second run: marked, nothing reinstalls.
        em.run_registry_auto_install()
        assert calls == ['serverkit-fail2ban']


def test_registry_auto_install_skips_fresh_installs(app, monkeypatch):
    from app.services import extension_migration as em

    _reset_registry_marker(app)
    monkeypatch.setattr(em, '_looks_like_existing_install', lambda: False)
    monkeypatch.setattr(em, 'REGISTRY_GATED_SLUGS',
                        {'serverkit-clamav': lambda: True})

    with app.app_context():
        em.run_registry_auto_install()
        # Marked done without installing — fresh installs use the wizard.
        assert 'serverkit-clamav' in em._registry_processed_slugs()


def test_registry_auto_install_tool_absent_marks_done(app, monkeypatch):
    from app.services import extension_migration as em

    _reset_registry_marker(app)
    monkeypatch.setattr(em, '_looks_like_existing_install', lambda: True)
    monkeypatch.setattr(em, 'REGISTRY_GATED_SLUGS',
                        {'serverkit-lynis': lambda: False})

    with app.app_context():
        em.run_registry_auto_install()
        assert 'serverkit-lynis' in em._registry_processed_slugs()


# ---------------------------------------------------------------------------
# Wizard round 2 (plan 47 Ph5): security posture.
# ---------------------------------------------------------------------------

def test_security_posture_levels_shape():
    from app.services.plugin_service import SECURITY_POSTURE_LEVELS
    assert set(SECURITY_POSTURE_LEVELS) == {'minimal', 'recommended', 'hardened'}
    assert SECURITY_POSTURE_LEVELS['minimal'] == []
    # hardened is a superset of recommended
    assert set(SECURITY_POSTURE_LEVELS['recommended']) <= set(
        SECURITY_POSTURE_LEVELS['hardened'])


def test_recommend_security_extensions_drops_unpublished(app):
    """With the bundled index (no security extensions published yet) every
    level resolves to only what the catalog can install — no dead buttons."""
    from app.services.plugin_service import (
        SECURITY_POSTURE_LEVELS, recommend_security_extensions)
    with app.app_context():
        for level in SECURITY_POSTURE_LEVELS:
            resolved = recommend_security_extensions(level)
            slugs = {e['slug'] for e in resolved}
            assert slugs <= set(SECURITY_POSTURE_LEVELS[level])
            for entry in resolved:
                assert entry.get('display_name')


def test_recommendations_endpoint_carries_postures(client, auth_headers):
    resp = client.get('/api/v1/plugins/recommendations', headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.get('security_postures', {})) == {
        'minimal', 'recommended', 'hardened'}


def test_complete_onboarding_persists_posture(client, auth_headers, app):
    resp = client.post('/api/v1/auth/complete-onboarding', headers=auth_headers,
                       json={'use_cases': [], 'security_posture': 'hardened'})
    assert resp.status_code == 200
    from app.services.settings_service import SettingsService
    with app.app_context():
        assert SettingsService.get('onboarding_security_posture') == 'hardened'


def test_complete_onboarding_invalid_posture_falls_back(client, auth_headers, app):
    resp = client.post('/api/v1/auth/complete-onboarding', headers=auth_headers,
                       json={'use_cases': [], 'security_posture': 'yolo'})
    assert resp.status_code == 200
    from app.services.settings_service import SettingsService
    with app.app_context():
        assert SettingsService.get('onboarding_security_posture') == 'minimal'
