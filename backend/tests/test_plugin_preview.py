"""GitHub-native install: shorthand normalization, preview endpoint,
token header injection, and preview -> install checksum continuity."""
import hashlib
import io
import json
import zipfile

import pytest

from app.models.plugin import InstalledPlugin
from app.services import plugin_service


@pytest.fixture
def plugin_dirs(tmp_path, monkeypatch):
    backend = tmp_path / 'b'
    frontend = tmp_path / 'f'
    for d in (backend, frontend):
        d.mkdir()
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))
    return {'backend': backend, 'frontend': frontend}


def _make_zip(slug='prevext', version='1.0.0', permissions=None,
              min_panel_version=None, with_manifest=True):
    manifest = {
        'name': slug, 'display_name': 'Preview Ext', 'version': version,
        'category': 'utility', 'description': 'A preview extension.',
        'author': 'Tester',
        'contributions': {'nav': [{'id': slug, 'label': 'Prev', 'route': '/prev'}]},
    }
    if permissions is not None:
        manifest['permissions'] = permissions
    if min_panel_version is not None:
        manifest['min_panel_version'] = min_panel_version
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        if with_manifest:
            zf.writestr('plugin.json', json.dumps(manifest))
        zf.writestr('frontend/index.jsx', 'export function P(){return null;}\n')
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Shorthand normalization
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('raw, expected', [
    ('jhd3197/serverkit-gui', 'https://github.com/jhd3197/serverkit-gui'),
    ('jhd3197/serverkit-gui@v1.2.0',
     'https://github.com/jhd3197/serverkit-gui/releases/tag/v1.2.0'),
    ('https://github.com/jhd3197/serverkit-gui',
     'https://github.com/jhd3197/serverkit-gui'),
    ('https://example.com/x.zip', 'https://example.com/x.zip'),
])
def test_normalize_source_url_shorthand(raw, expected):
    assert plugin_service._normalize_source_url(raw) == expected


# --------------------------------------------------------------------------- #
# Preview endpoint / service
# --------------------------------------------------------------------------- #

def _patch_resolve(monkeypatch, zip_bytes, resolved='https://x/prevext.zip',
                   zipball_fallback=False):
    def fake_resolve(url, strict=False):
        plugin_service._LAST_RESOLUTION['zipball_fallback'] = zipball_fallback
        return resolved
    monkeypatch.setattr(plugin_service, '_resolve_github_url', fake_resolve)
    monkeypatch.setattr(plugin_service, '_download_resolved',
                        lambda r: io.BytesIO(zip_bytes))


def test_preview_happy_path(app, monkeypatch):
    zip_bytes = _make_zip(permissions=['network', 'docker'])
    _patch_resolve(monkeypatch, zip_bytes)

    result = plugin_service.preview_from_url('owner/prevext')
    assert result['slug'] == 'prevext'
    assert result['version'] == '1.0.0'
    assert result['permissions'] == ['network', 'docker']
    assert result['resolved_url'] == 'https://x/prevext.zip'
    assert result['sha256'] == hashlib.sha256(zip_bytes).hexdigest()
    assert result['warnings'] == []


def test_preview_warns_on_zipball_fallback(app, monkeypatch):
    zip_bytes = _make_zip()
    _patch_resolve(monkeypatch, zip_bytes, zipball_fallback=True)
    result = plugin_service.preview_from_url('owner/prevext')
    assert any('release asset' in w.lower() or 'default-branch' in w.lower()
               for w in result['warnings'])


def test_preview_warns_on_panel_gate(app, monkeypatch):
    zip_bytes = _make_zip(min_panel_version='999.0.0')
    _patch_resolve(monkeypatch, zip_bytes)
    result = plugin_service.preview_from_url('owner/prevext')
    assert any('999.0.0' in w for w in result['warnings'])


def test_preview_warns_on_slug_collision(app, plugin_dirs, monkeypatch):
    # Install prevext first.
    zip_bytes = _make_zip()
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))
    plugin_service.install_from_url('https://x/prevext.zip')
    assert InstalledPlugin.query.filter_by(slug='prevext').first() is not None

    _patch_resolve(monkeypatch, zip_bytes)
    result = plugin_service.preview_from_url('owner/prevext')
    assert any('already installed' in w.lower() for w in result['warnings'])


def test_preview_no_manifest_is_actionable(app, monkeypatch):
    zip_bytes = _make_zip(with_manifest=False)
    _patch_resolve(monkeypatch, zip_bytes)
    with pytest.raises(ValueError, match='plugin.json'):
        plugin_service.preview_from_url('owner/prevext')


def test_preview_endpoint(app, client, auth_headers, monkeypatch):
    zip_bytes = _make_zip(permissions=['network'])
    _patch_resolve(monkeypatch, zip_bytes)
    resp = client.post('/api/v1/plugins/preview',
                       json={'url': 'owner/prevext'}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['slug'] == 'prevext'
    assert data['permissions'] == ['network']


# --------------------------------------------------------------------------- #
# preview -> install checksum continuity
# --------------------------------------------------------------------------- #

def test_preview_install_checksum_continuity(app, plugin_dirs, monkeypatch):
    zip_bytes = _make_zip()
    _patch_resolve(monkeypatch, zip_bytes)
    preview = plugin_service.preview_from_url('owner/prevext')

    # Install with the previewed resolved_url + sha256 → byte-identical, succeeds.
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))
    plugin = plugin_service.install_from_url(
        preview['resolved_url'], expected_sha256=preview['sha256'])
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.version == '1.0.0'


def test_preview_install_tamper_rejected(app, plugin_dirs, monkeypatch):
    zip_bytes = _make_zip()
    _patch_resolve(monkeypatch, zip_bytes)
    preview = plugin_service.preview_from_url('owner/prevext')

    # Serve DIFFERENT bytes at install time; the pinned sha256 must reject them.
    tampered = _make_zip(version='9.9.9')
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(tampered))
    with pytest.raises(ValueError, match='Checksum mismatch'):
        plugin_service.install_from_url(
            preview['resolved_url'], expected_sha256=preview['sha256'])
    assert InstalledPlugin.query.filter_by(slug='prevext').first() is None


# --------------------------------------------------------------------------- #
# GitHub token header injection (never leaked to non-GitHub hosts)
# --------------------------------------------------------------------------- #

def test_github_api_headers_include_token_when_set(monkeypatch):
    monkeypatch.setenv('SERVERKIT_GITHUB_TOKEN', 'ghp_secret')
    headers = plugin_service._github_api_headers()
    assert headers['Authorization'] == 'Bearer ghp_secret'


def test_github_api_headers_omit_token_when_unset(monkeypatch):
    monkeypatch.delenv('SERVERKIT_GITHUB_TOKEN', raising=False)
    assert 'Authorization' not in plugin_service._github_api_headers()


def test_download_token_only_for_github_hosts(monkeypatch):
    monkeypatch.setenv('SERVERKIT_GITHUB_TOKEN', 'ghp_secret')
    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def iter_content(self, chunk_size=8192): return [b'zipbytes']

    def fake_get(url, **kwargs):
        captured[url] = kwargs.get('headers', {})
        return FakeResp()

    monkeypatch.setattr(plugin_service.requests, 'get', fake_get)
    # The SSRF guard resolves hosts before fetching; stub DNS to a public IP
    # so this test stays offline (its subject is token scoping, not DNS).
    import socket as _socket
    monkeypatch.setattr(_socket, 'getaddrinfo',
                        lambda host, port, *a, **k: [(2, 1, 6, '', ('93.184.216.34', 0))])

    plugin_service._download_resolved('https://github.com/o/r/releases/download/v1/x.zip')
    plugin_service._download_resolved('https://evil.example.com/x.zip')

    gh_headers = captured['https://github.com/o/r/releases/download/v1/x.zip']
    other_headers = captured['https://evil.example.com/x.zip']
    assert gh_headers.get('Authorization') == 'Bearer ghp_secret'
    assert 'Authorization' not in other_headers  # never leak the token off-GitHub
