"""Proving tests for the template repository default and sync verification.

Two things land here together on purpose. The default repo URL pointed at
`serverkit/templates`, an org that does not exist, so it 404'd for its whole
life and no panel ever fetched a template through it. Correcting it turns on
a download path that has therefore never actually run in production -- and
that path wrote whatever came back straight to disk without checking the
sha256 the index pins for every entry. Fixing the URL without the checksum
would be switching on an unverified fetch.
"""
import hashlib
import json
import os
from unittest.mock import patch

import pytest

from app.services.template_service import TemplateService


TEMPLATE_BODY = b"name: Demo\nversion: '1.0'\nservices:\n  web:\n    image: demo:1\n"
TEMPLATE_SHA = hashlib.sha256(TEMPLATE_BODY).hexdigest()


class FakeResponse:
    def __init__(self, content=b"", payload=None, status_code=200):
        self.content = content
        self._payload = payload
        self.status_code = status_code

    @property
    def text(self):
        return self.content.decode("utf-8")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# --------------------------------------------------------------------------
# Default repo + healing
# --------------------------------------------------------------------------

def test_default_repo_points_at_a_reachable_host():
    """The org `serverkit` does not exist; the registry is under jhd3197 and is
    proxied by serverkit.ai. Guard against the old value coming back."""
    url = TemplateService.DEFAULT_REPOS[0]['url']
    assert 'raw.githubusercontent.com/serverkit/' not in url
    assert url == 'https://serverkit.ai/templates'


def test_derived_urls_match_what_the_proxy_serves():
    """This class builds <repo_url>/index.json and
    <repo_url>/templates/<id>.yaml. serverkit.ai exposes both shapes; if this
    ever drifts, every sync 404s silently."""
    base = TemplateService.DEFAULT_REPOS[0]['url']
    assert f"{base}/index.json" == 'https://serverkit.ai/templates/index.json'
    assert f"{base}/templates/n8n.yaml" == 'https://serverkit.ai/templates/templates/n8n.yaml'


def test_dead_repo_url_is_healed_on_read(tmp_path):
    """A panel that already saved templates.json keeps its repos, so fixing the
    default alone would strand every existing install on the dead URL."""
    config_path = tmp_path / 'templates.json'
    config_path.write_text(json.dumps({
        'repos': [{
            'name': 'serverkit-official',
            'url': 'https://raw.githubusercontent.com/serverkit/templates/main',
            'enabled': True,
        }],
        'installed': {},
        'last_sync': None,
    }))

    with patch.object(TemplateService, 'TEMPLATE_CONFIG', str(config_path)):
        config = TemplateService.get_config()

    assert config['repos'][0]['url'] == 'https://serverkit.ai/templates'
    assert config['repos'][0]['name'] == 'serverkit-official'  # nothing else touched


def test_healing_leaves_operator_repos_alone(tmp_path):
    """Only the known-dead URLs are rewritten -- a custom repo is untouched."""
    config_path = tmp_path / 'templates.json'
    config_path.write_text(json.dumps({
        'repos': [
            {'name': 'mine', 'url': 'https://templates.example.com/sk', 'enabled': True},
            {'name': 'dead', 'url': 'https://raw.githubusercontent.com/serverkit/templates/main',
             'enabled': False},
        ],
    }))

    with patch.object(TemplateService, 'TEMPLATE_CONFIG', str(config_path)):
        repos = TemplateService.get_config()['repos']

    assert repos[0]['url'] == 'https://templates.example.com/sk'
    assert repos[1]['url'] == 'https://serverkit.ai/templates'
    assert repos[1]['enabled'] is False  # healing must not re-enable anything


def test_healing_survives_a_malformed_config(tmp_path):
    """Garbage in the repos key must not take the whole panel's config down."""
    config_path = tmp_path / 'templates.json'
    config_path.write_text(json.dumps({'repos': 'not-a-list'}))

    with patch.object(TemplateService, 'TEMPLATE_CONFIG', str(config_path)):
        config = TemplateService.get_config()

    assert config['repos'] == 'not-a-list'  # returned as-is, no crash


# --------------------------------------------------------------------------
# sync_templates checksum verification
# --------------------------------------------------------------------------

def _run_sync(tmp_path, index_entry, body):
    """Drive sync_templates against a one-entry fake repo."""
    index = {'templates': [index_entry]}

    def fake_get(url, timeout=None):
        if url.endswith('/index.json'):
            return FakeResponse(payload=index)
        return FakeResponse(content=body)

    templates_dir = tmp_path / 'templates'
    config_path = tmp_path / 'templates.json'
    config_path.write_text(json.dumps({
        'repos': [{'name': 'test', 'url': 'https://example.test/repo', 'enabled': True}],
    }))

    with patch.object(TemplateService, 'TEMPLATES_DIR', str(templates_dir)), \
            patch.object(TemplateService, 'TEMPLATE_CONFIG', str(config_path)), \
            patch.object(TemplateService, 'CONFIG_DIR', str(tmp_path)), \
            patch('app.services.template_service.requests.get', side_effect=fake_get):
        result = TemplateService.sync_templates()

    return result, templates_dir / 'demo.yaml'


def test_matching_checksum_is_saved(tmp_path):
    result, path = _run_sync(
        tmp_path, {'id': 'demo', 'sha256': TEMPLATE_SHA}, TEMPLATE_BODY)

    assert result['synced'] == 1
    assert result['unverified'] == 0
    assert not result['errors']
    assert path.exists()
    # Byte-identical to what was verified.
    assert hashlib.sha256(path.read_bytes()).hexdigest() == TEMPLATE_SHA


def test_mismatched_checksum_is_refused_and_not_written(tmp_path):
    """A template is a deploy definition -- images, ports, volumes, env. A
    swapped file is refused outright rather than saved with a warning."""
    result, path = _run_sync(
        tmp_path, {'id': 'demo', 'sha256': 'de' * 32}, TEMPLATE_BODY)

    assert result['synced'] == 0
    assert not path.exists(), 'refused content must never reach disk'
    assert result['errors'] and 'Checksum mismatch' in result['errors'][0]


def test_missing_checksum_is_allowed_but_counted(tmp_path):
    """Third-party repos may publish no hashes; absent is a caveat, not a
    hard stop -- mirroring unsigned-vs-invalid for extensions."""
    result, path = _run_sync(tmp_path, {'id': 'demo'}, TEMPLATE_BODY)

    assert result['synced'] == 1
    assert result['unverified'] == 1
    assert path.exists()


def test_checksum_comparison_ignores_case_and_padding(tmp_path):
    result, path = _run_sync(
        tmp_path, {'id': 'demo', 'sha256': f'  {TEMPLATE_SHA.upper()}  '}, TEMPLATE_BODY)

    assert result['synced'] == 1
    assert path.exists()


def test_one_bad_template_does_not_abort_the_rest(tmp_path):
    """A poisoned entry must not stop the good ones from syncing."""
    good = b"name: Good\n"
    index = {'templates': [
        {'id': 'bad', 'sha256': 'de' * 32},
        {'id': 'good', 'sha256': hashlib.sha256(good).hexdigest()},
    ]}

    def fake_get(url, timeout=None):
        if url.endswith('/index.json'):
            return FakeResponse(payload=index)
        return FakeResponse(content=TEMPLATE_BODY if '/bad.yaml' in url else good)

    templates_dir = tmp_path / 'templates'
    config_path = tmp_path / 'templates.json'
    config_path.write_text(json.dumps({
        'repos': [{'name': 'test', 'url': 'https://example.test/repo', 'enabled': True}],
    }))

    with patch.object(TemplateService, 'TEMPLATES_DIR', str(templates_dir)), \
            patch.object(TemplateService, 'TEMPLATE_CONFIG', str(config_path)), \
            patch.object(TemplateService, 'CONFIG_DIR', str(tmp_path)), \
            patch('app.services.template_service.requests.get', side_effect=fake_get):
        result = TemplateService.sync_templates()

    assert result['synced'] == 1
    assert (templates_dir / 'good.yaml').exists()
    assert not (templates_dir / 'bad.yaml').exists()
    assert len(result['errors']) == 1
