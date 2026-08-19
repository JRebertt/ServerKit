"""Proving tests for repo-kind deploy templates (plan 43, Phase 1).

Deploy templates used to be a hardcoded frontend constant; they now live in the
backend catalog as ``kind: repo`` YAML entries that blend with the 105 compose
templates. These tests cover: kind parsing + backward compat, the agentsite
entry, repo-kind validation, the declared-hints fallback, public-repo manifest
inspection (with a mocked raw fetch), and the ``/manifest`` endpoint's two paths
(live inspection vs. hint fallback). Additions only — ratchet-safe.
"""
import pytest

from app.services.template_service import TemplateService
from app.services.repository_manifest_service import RepositoryManifestService


# --------------------------------------------------------------------------- #
# Kind parsing + backward compatibility
# --------------------------------------------------------------------------- #
def test_compose_templates_default_to_compose_kind():
    """Every bundled compose template lists as kind 'compose' (no YAML change)."""
    entries = TemplateService.list_local_templates()
    portainer = next((e for e in entries if e['id'] == 'portainer'), None)
    assert portainer is not None
    assert portainer['kind'] == 'compose'
    assert 'repo' not in portainer


def test_validate_template_backward_compat_no_kind():
    """A template with no `kind` and a compose block still validates."""
    tmpl = {'name': 'X', 'version': '1', 'description': 'd', 'compose': {'services': {}}}
    assert TemplateService.validate_template(tmpl)['valid'] is True


def test_validate_repo_template_requires_url():
    ok = {'name': 'X', 'version': '1', 'description': 'd', 'kind': 'repo',
          'repo': {'url': 'https://github.com/a/b.git'}}
    assert TemplateService.validate_template(ok)['valid'] is True

    missing = {'name': 'X', 'version': '1', 'description': 'd', 'kind': 'repo', 'repo': {}}
    result = TemplateService.validate_template(missing)
    assert result['valid'] is False
    assert any('repo' in e.lower() for e in result['errors'])


def test_unknown_kind_is_rejected():
    tmpl = {'name': 'X', 'version': '1', 'description': 'd', 'kind': 'bogus'}
    result = TemplateService.validate_template(tmpl)
    assert result['valid'] is False


# --------------------------------------------------------------------------- #
# agentsite.yaml — the migrated deploy template
# --------------------------------------------------------------------------- #
def test_agentsite_served_as_repo_kind():
    result = TemplateService.get_template('agentsite')
    assert result['success'] is True
    tmpl = result['template']
    assert tmpl['kind'] == 'repo'
    assert tmpl['repo']['url'].startswith('https://github.com/')
    assert tmpl['repo']['app_type'] == 'docker'
    assert tmpl.get('icon')


def test_agentsite_in_list_with_repo_summary():
    entries = TemplateService.list_local_templates()
    agent = next((e for e in entries if e['id'] == 'agentsite'), None)
    assert agent is not None
    assert agent['kind'] == 'repo'
    assert agent['repo']['url']
    assert agent['repo']['branch'] == 'main'


# --------------------------------------------------------------------------- #
# Declared-hints fallback
# --------------------------------------------------------------------------- #
def test_build_template_hints_shape():
    tmpl = TemplateService.get_template('agentsite')['template']
    hints = TemplateService.build_template_hints(tmpl)
    assert hints['strategy'] == 'serverkit'
    assert hints['recommended']['app_type'] == 'docker'
    assert hints['recommended']['port'] == 6391
    keys = {e['key'] for e in hints['env']}
    assert 'OPENAI_API_KEY' in keys
    # Secret env values are never leaked in hints.
    assert all(e['value'] is None for e in hints['env'] if e['secret'])
    assert {m['file'] for m in hints['manifests']} >= {
        'serverkit.yaml', 'docker-compose.yml', 'render.yaml'}


# --------------------------------------------------------------------------- #
# Public-repo manifest inspection (mocked raw fetch)
# --------------------------------------------------------------------------- #
def test_raw_base_url_mapping():
    gh = RepositoryManifestService._raw_base_url('https://github.com/a/b.git', 'main')
    assert gh == 'https://raw.githubusercontent.com/a/b/main'
    gl = RepositoryManifestService._raw_base_url('https://gitlab.com/a/b', 'dev')
    assert gl == 'https://gitlab.com/a/b/-/raw/dev'
    assert RepositoryManifestService._raw_base_url('https://example.com/a/b', 'main') is None


def test_analyze_public_repo_happy_path(monkeypatch):
    compose = 'services:\n  web:\n    build: .\n    ports:\n      - "6391:6391"\n'

    def fake_fetch(url):
        if url.endswith('/docker-compose.yml'):
            return compose
        return None

    monkeypatch.setattr(RepositoryManifestService, '_fetch_raw', staticmethod(fake_fetch))
    result = RepositoryManifestService.analyze_public_repo('https://github.com/a/b.git', 'main')
    assert result['strategy'] == 'docker_compose'
    assert 6391 in result['ports']
    assert any(m['type'] == 'docker_compose' for m in result['manifests'])


def test_analyze_public_repo_no_files(monkeypatch):
    monkeypatch.setattr(RepositoryManifestService, '_fetch_raw', staticmethod(lambda url: None))
    result = RepositoryManifestService.analyze_public_repo('https://github.com/a/b.git', 'main')
    assert result['strategy'] is None
    assert result['warnings']


# --------------------------------------------------------------------------- #
# /manifest endpoint — live inspection and hint fallback
# --------------------------------------------------------------------------- #
def test_manifest_endpoint_live_inspection(client, auth_headers, monkeypatch):
    compose = 'services:\n  web:\n    build: .\n    ports:\n      - "6391:6391"\n'
    monkeypatch.setattr(
        RepositoryManifestService, '_fetch_raw',
        staticmethod(lambda url: compose if url.endswith('/docker-compose.yml') else None),
    )
    resp = client.get('/api/v1/templates/agentsite/manifest', headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['source'] == 'repo'
    assert body['manifest']['strategy'] == 'docker_compose'


def test_manifest_endpoint_falls_back_to_hints(client, auth_headers, monkeypatch):
    # No supported files reachable -> honest declared-hints fallback.
    monkeypatch.setattr(
        RepositoryManifestService, '_fetch_raw', staticmethod(lambda url: None))
    resp = client.get('/api/v1/templates/agentsite/manifest', headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['source'] == 'template-hints'
    assert body['manifest']['recommended']['port'] == 6391


def test_manifest_endpoint_rejects_compose_template(client, auth_headers):
    resp = client.get('/api/v1/templates/portainer/manifest', headers=auth_headers)
    assert resp.status_code == 400
