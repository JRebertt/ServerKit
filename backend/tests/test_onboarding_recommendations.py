"""Plan 47 Phase 1 — the setup wizard installs what it recommends.

Proves the use-case → extension-slug map has no dead slugs, the recommendation
resolver/endpoint returns real extension metadata, complete-onboarding persists
what the wizard installed, and the flagship seeding machinery still works.

WordPress note (plan 52 Phase 5): WP left the tree into the standalone
serverkit-wordpress repo and now distributes through the registry (the
k8s/tramo model) — the wizard offers it via the use-case map, but nothing
auto-seeds it. The wizard-optional flagship list is empty until a future
in-tree flagship needs it; the gating machinery is proven here with a
monkeypatched member.
"""
import pytest

from app import db
from app.models.plugin import InstalledPlugin
from app.models.user import User
from app.services import plugin_service as ps
from app.services.settings_service import SettingsService
from werkzeug.security import generate_password_hash
from flask_jwt_extended import create_access_token


# ── map integrity ────────────────────────────────────────────────────────────

def test_recommendation_map_has_no_dead_slugs(app):
    """Every slug in the use-case map resolves to a builtin or registry entry."""
    with app.app_context():
        index = ps._recommendation_index()
        dead = [
            slug
            for slugs in ps.RECOMMENDED_EXTENSIONS_BY_USE_CASE.values()
            for slug in slugs
            if slug not in index
        ]
        assert dead == [], f'recommendation map points at dead slugs: {dead}'


def test_recommend_resolves_and_dedupes(app):
    with app.app_context():
        recs = ps.recommend_extensions_for_use_cases(['web-apps', 'devops'])
        slugs = [r['slug'] for r in recs]
        # git appears in both use cases — must be de-duped, first-seen order kept
        assert slugs.count('serverkit-git') == 1
        assert 'serverkit-status' in slugs
        assert 'serverkit-k8s' in slugs
        assert 'serverkit-tramo' in slugs
        # every entry carries real metadata (not just a display string)
        for r in recs:
            assert r['display_name']
            assert r['source'] in ('builtin', 'registry')
            assert 'installed' in r


def test_recommend_empty_use_cases(app):
    with app.app_context():
        assert ps.recommend_extensions_for_use_cases([]) == []
        assert ps.recommend_extensions_for_use_cases(None) == []


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_recommendations_endpoint(client, auth_headers):
    resp = client.get('/api/v1/plugins/recommendations?use_cases=wordpress',
                       headers=auth_headers)
    assert resp.status_code == 200
    slugs = [r['slug'] for r in resp.get_json()['recommendations']]
    assert 'serverkit-wordpress' in slugs


def test_recommendations_endpoint_requires_auth(client):
    resp = client.get('/api/v1/plugins/recommendations?use_cases=wordpress')
    assert resp.status_code == 401


# ── complete-onboarding persists installed slugs ─────────────────────────────

def test_complete_onboarding_persists_installed_extensions(client, auth_headers):
    resp = client.post('/api/v1/auth/complete-onboarding',
                       json={'use_cases': ['devops'],
                             'installed_extensions': ['serverkit-k8s', 'serverkit-git']},
                       headers=auth_headers)
    assert resp.status_code == 200
    assert SettingsService.get('onboarding_installed_extensions') == [
        'serverkit-k8s', 'serverkit-git']
    assert SettingsService.get('onboarding_use_cases') == ['devops']


def test_complete_onboarding_rejects_bad_installed_extensions(client, auth_headers):
    resp = client.post('/api/v1/auth/complete-onboarding',
                       json={'use_cases': [], 'installed_extensions': 'nope'},
                       headers=auth_headers)
    assert resp.status_code == 400


def test_complete_onboarding_still_completes_without_installs(client, auth_headers):
    """A wizard run that installs nothing (the lean outcome) still finishes."""
    resp = client.post('/api/v1/auth/complete-onboarding',
                       json={'use_cases': []},
                       headers=auth_headers)
    assert resp.status_code == 200
    assert SettingsService.get('setup_completed') is True


# ── wizard-optional flagship gating ──────────────────────────────────────────

def test_finalize_setup_flagships_marks_uninstalled_when_absent(app, monkeypatch):
    """The wizard-optional gating machinery: an uninstalled member gets the
    uninstall marker so the boot seeder never re-adds it. (The list is empty
    post-Phase-5 — WordPress graduated to the registry — so the machinery is
    proven with a monkeypatched member.)"""
    monkeypatch.setattr(ps, 'WIZARD_OPTIONAL_FLAGSHIP_SLUGS', ['serverkit-demo-opt'])
    with app.app_context():
        ps.finalize_setup_flagships()
        assert 'serverkit-demo-opt' in ps._flagship_uninstalled_set()


def test_finalize_setup_flagships_keeps_installed(app, monkeypatch):
    """An INSTALLED wizard-optional flagship is never marked uninstalled.

    FLAGSHIP_SLUGS is empty since the cloudflare-ops cutover (plan 52 Ph2),
    so the machinery is proven with a fabricated installed row."""
    monkeypatch.setattr(ps, 'WIZARD_OPTIONAL_FLAGSHIP_SLUGS', ['serverkit-demo-opt'])
    with app.app_context():
        db.session.add(InstalledPlugin(
            name='serverkit-demo-opt', display_name='Demo', slug='serverkit-demo-opt',
            version='1.0.0', status=InstalledPlugin.STATUS_ACTIVE))
        db.session.commit()
        ps.finalize_setup_flagships()
        assert 'serverkit-demo-opt' not in ps._flagship_uninstalled_set()


def test_wordpress_not_seeded_post_extraction(app):
    """Plan 52 Phase 5 + Ph2 cutover: WordPress AND cloudflare-ops are
    registry extensions now — the boot-time flagship seeder (an empty list)
    installs neither. The wizard offers them through the catalog instead."""
    with app.app_context():
        InstalledPlugin.query.filter_by(slug='serverkit-wordpress').delete()
        db.session.commit()
        app.config['TESTING'] = False
        try:
            ps.seed_flagship_extensions()
            assert InstalledPlugin.query.filter_by(
                slug='serverkit-wordpress').first() is None
            assert InstalledPlugin.query.filter_by(
                slug='serverkit-cloudflare-ops').first() is None
        finally:
            app.config['TESTING'] = True


def test_wordpress_offered_via_registry_in_recommendations(app):
    """The wizard's WP path post-extraction: the bundled registry index
    carries the entry, so the use-case map resolves it as a registry install."""
    with app.app_context():
        recs = ps.recommend_extensions_for_use_cases(['wordpress'])
        wp = next((r for r in recs if r['slug'] == 'serverkit-wordpress'), None)
        assert wp is not None, 'WP must stay offered during onboarding'
        assert wp['source'] == 'registry'
        assert wp['installed'] is False
