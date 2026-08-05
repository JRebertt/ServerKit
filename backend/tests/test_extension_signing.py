"""Extension release signing (plan 55 Phase 2 / D3).

Covers: sign/verify round-trip, tamper detection, untrusted keys, key-id
substitution, the unsigned consent policy (registry 409 gate), install-time
verification + stamping, preview verdicts, and schema round-trip with old
(v1/v2) registry indexes that carry no signature fields.
"""
import base64
import hashlib
import io
import json
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app import db
from app.models.plugin import InstalledPlugin
from app.services import plugin_service, registry_service, signing_service


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _reset_registry_cache():
    registry_service._cache.update({'ts': 0.0, 'entries': None, 'source': None})
    yield
    registry_service._cache.update({'ts': 0.0, 'entries': None, 'source': None})


@pytest.fixture
def plugin_dirs(tmp_path, monkeypatch):
    backend = tmp_path / 'b'
    frontend = tmp_path / 'f'
    for d in (backend, frontend):
        d.mkdir()
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))
    return {'backend': backend, 'frontend': frontend}


def _make_plugin_zip(slug='signed-ext', version='1.0.0'):
    manifest = {
        'name': slug, 'display_name': 'Signed Ext', 'version': version,
        'category': 'utility',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('plugin.json', json.dumps(manifest))
        zf.writestr('frontend/index.jsx', 'export function P(){return null;}\n')
    return buf.getvalue()


def _public_b64(private_key):
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode('ascii')


def _pin_keys(tmp_path, monkeypatch, keys):
    """Write a trusted-keys file pinning the given [(key_id, priv, publisher)]
    and point the signing service at it via the operator env var."""
    payload = {'keys': [
        {
            'key_id': key_id,
            'publisher': publisher,
            'algorithm': 'ed25519',
            'public_key': _public_b64(priv),
        }
        for key_id, priv, publisher in keys
    ]}
    keys_file = tmp_path / 'trusted_keys.json'
    keys_file.write_text(json.dumps(payload))
    monkeypatch.setenv('SERVERKIT_TRUSTED_EXTENSION_KEYS', str(keys_file))


# --------------------------------------------------------------------------- #
# sign / verify round-trip + failure modes
# --------------------------------------------------------------------------- #

def test_sign_verify_round_trip(tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    data = _make_plugin_zip()

    sig = signing_service.sign_bytes(data, priv)
    result = signing_service.verify_detached(data, sig, 'test-pub')
    assert result['status'] == 'verified'
    assert result['key_id'] == 'test-pub'
    assert result['publisher'] == 'Test Publisher'

    # Without a key_id (the .minisig flow) the key is found by envelope key_num.
    result = signing_service.verify_detached(data, sig)
    assert result['status'] == 'verified'
    assert result['key_id'] == 'test-pub'


def test_tamper_detection(tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    data = bytearray(_make_plugin_zip())
    sig = signing_service.sign_bytes(bytes(data), priv)

    data[len(data) // 2] ^= 0xFF  # flip a byte mid-archive
    result = signing_service.verify_detached(bytes(data), sig, 'test-pub')
    assert result['status'] == 'invalid'
    assert 'does not match' in result['error']

    with pytest.raises(ValueError, match='Signature verification failed'):
        signing_service.verify_for_install(bytes(data), sig, 'test-pub')


def test_malformed_signatures_are_invalid(tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    data = _make_plugin_zip()

    assert signing_service.verify_detached(data, '!!!not-base64!!!', 'test-pub')['status'] == 'invalid'
    # Valid base64 but wrong envelope length / marker.
    short = base64.b64encode(b'ED' + b'\x00' * 10).decode()
    assert signing_service.verify_detached(data, short, 'test-pub')['status'] == 'invalid'
    wrong_marker = base64.b64encode(b'XX' + b'\x00' * 72).decode()
    assert signing_service.verify_detached(data, wrong_marker, 'test-pub')['status'] == 'invalid'


def test_untrusted_key(tmp_path, monkeypatch):
    pinned = Ed25519PrivateKey.generate()
    stranger = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', pinned, 'Test Publisher')])
    data = _make_plugin_zip()

    sig = signing_service.sign_bytes(data, stranger)
    # Named key id the panel doesn't pin…
    assert signing_service.verify_detached(data, sig, 'stranger')['status'] == 'untrusted_key'
    # …and anonymous lookup finds no pinned key with that key_num either.
    assert signing_service.verify_detached(data, sig)['status'] == 'untrusted_key'
    # An untrusted key is not a hard failure — the caller's consent policy decides.
    assert signing_service.verify_for_install(data, sig, 'stranger')['status'] == 'untrusted_key'


def test_key_id_substitution_rejected(tmp_path, monkeypatch):
    """A signature made by key A presented under key B's id must not verify."""
    priv_a = Ed25519PrivateKey.generate()
    priv_b = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [
        ('key-a', priv_a, 'Publisher A'),
        ('key-b', priv_b, 'Publisher B'),
    ])
    data = _make_plugin_zip()
    sig = signing_service.sign_bytes(data, priv_a)

    result = signing_service.verify_detached(data, sig, 'key-b')
    assert result['status'] == 'invalid'
    assert 'different key' in result['error']


def test_unsigned_verdict():
    assert signing_service.verify_detached(b'data', None)['status'] == 'unsigned'
    assert signing_service.verify_detached(b'data', '')['status'] == 'unsigned'


def test_shipped_first_party_key_is_pinned():
    """The panel ships its first-party public key (plan 55: pinned key in
    backend/app/data). Guards against the keys file being emptied/broken."""
    keys = signing_service.load_trusted_keys()
    assert 'serverkit-official' in keys
    assert len(keys['serverkit-official']['public_key']) == 32


# --------------------------------------------------------------------------- #
# Registry schema round-trip (v3 fields; old indexes stay valid)
# --------------------------------------------------------------------------- #

def test_normalize_old_index_entry_is_unsigned():
    """v1/v2 index entries carry no signature fields → unsigned, not broken."""
    entry = registry_service._normalize({
        'slug': 'old-ext', 'version': '1.0.0', 'source': 'https://x/o.zip',
        'sha256': 'a' * 64, 'first_party': True,
    })
    assert entry['signature'] is None
    assert entry['publisher_key_id'] is None
    assert entry['publisher_trusted'] is False
    assert entry['trust'] == 'first_party'  # existing derivation untouched


def test_normalize_v3_signature_fields(tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    sig = signing_service.sign_bytes(_make_plugin_zip(), priv)

    entry = registry_service._normalize({
        'slug': 'signed-ext', 'version': '1.0.0', 'source': 'https://x/s.zip',
        'sha256': 'b' * 64, 'signature': sig, 'publisher_key_id': 'test-pub',
    })
    assert entry['signature'] == sig
    assert entry['publisher_key_id'] == 'test-pub'
    assert entry['publisher_trusted'] is True

    # Unknown publisher key → fields survive but are flagged untrusted.
    entry = registry_service._normalize({
        'slug': 'signed-ext', 'version': '1.0.0', 'source': 'https://x/s.zip',
        'signature': sig, 'publisher_key_id': 'stranger',
    })
    assert entry['publisher_trusted'] is False

    # A signature without a key id (or vice versa) collapses to unsigned.
    entry = registry_service._normalize({
        'slug': 'half', 'version': '1.0.0', 'source': 'https://x/h.zip',
        'signature': sig,
    })
    assert entry['signature'] is None
    assert entry['publisher_key_id'] is None


# --------------------------------------------------------------------------- #
# Install-time verification + stamping
# --------------------------------------------------------------------------- #

def test_signed_install_verifies_and_stamps(app, plugin_dirs, tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    sig = signing_service.sign_bytes(zip_bytes, priv)
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))

    plugin = plugin_service.install_from_url(
        'https://x/signed-ext.zip',
        expected_sha256=hashlib.sha256(zip_bytes).hexdigest(),
        expected_signature=sig, expected_key_id='test-pub',
    )
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    stamped = plugin.config['_signature']
    assert stamped['status'] == 'verified'
    assert stamped['key_id'] == 'test-pub'
    assert stamped['publisher'] == 'Test Publisher'
    # Surfaced on the API dict for the extension detail page.
    assert plugin.to_dict()['signature']['status'] == 'verified'


def test_bad_signature_hard_fails_install(app, plugin_dirs, tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    sig = signing_service.sign_bytes(b'different bytes entirely', priv)
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))

    with pytest.raises(ValueError, match='Signature verification failed'):
        plugin_service.install_from_url(
            'https://x/signed-ext.zip',
            expected_signature=sig, expected_key_id='test-pub',
        )
    assert InstalledPlugin.query.filter_by(slug='signed-ext').first() is None


def test_unsigned_install_stamps_unsigned(app, plugin_dirs, monkeypatch):
    zip_bytes = _make_plugin_zip()
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))

    plugin = plugin_service.install_from_url('https://x/signed-ext.zip')
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.config['_signature'] == {'status': 'unsigned'}


def test_untrusted_key_install_proceeds_but_is_recorded(
        app, plugin_dirs, tmp_path, monkeypatch):
    stranger = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [])  # panel pins nothing extra
    zip_bytes = _make_plugin_zip()
    sig = signing_service.sign_bytes(zip_bytes, stranger)
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))

    plugin = plugin_service.install_from_url(
        'https://x/signed-ext.zip',
        expected_signature=sig, expected_key_id='stranger',
    )
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.config['_signature']['status'] == 'untrusted_key'
    assert plugin.config['_signature']['key_id'] == 'stranger'


def test_signature_config_key_is_reserved(app, plugin_dirs, tmp_path, monkeypatch):
    """A config PUT can neither drop nor forge the signature verdict."""
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    sig = signing_service.sign_bytes(zip_bytes, priv)
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))
    plugin = plugin_service.install_from_url(
        'https://x/signed-ext.zip', expected_signature=sig, expected_key_id='test-pub')

    plugin_service.update_plugin_config(plugin.slug, {
        'some_setting': 'x',
        '_signature': {'status': 'verified', 'publisher': 'Forged'},
        '_frontend_hashes': {},
    })
    db.session.refresh(plugin)
    assert plugin.config['some_setting'] == 'x'
    assert plugin.config['_signature']['publisher'] == 'Test Publisher'


def test_registry_install_passes_signature_through(
        app, plugin_dirs, tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    sig = signing_service.sign_bytes(zip_bytes, priv)
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))
    monkeypatch.setattr(registry_service, '_cache', {
        'ts': 9e18, 'source': 'test',
        'entries': [registry_service._normalize({
            'slug': 'signed-ext', 'display_name': 'Signed Ext', 'version': '1.0.0',
            'source': 'https://x/signed-ext.zip',
            'sha256': hashlib.sha256(zip_bytes).hexdigest(),
            'signature': sig, 'publisher_key_id': 'test-pub',
            'min_panel_version': '0.0.1',
        })],
    })

    plugin = plugin_service.install_registry_extension('signed-ext')
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.source_type == 'registry'
    assert plugin.config['_signature']['status'] == 'verified'


def test_registry_install_bad_signature_hard_fails(
        app, plugin_dirs, tmp_path, monkeypatch):
    """Tamper case: index sha256 matches (attacker updated both fields) but the
    signature doesn't — the pinned key, not the index, decides."""
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    bad_sig = signing_service.sign_bytes(b'other bytes', priv)
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))
    monkeypatch.setattr(registry_service, '_cache', {
        'ts': 9e18, 'source': 'test',
        'entries': [registry_service._normalize({
            'slug': 'signed-ext', 'display_name': 'Signed Ext', 'version': '1.0.0',
            'source': 'https://x/signed-ext.zip',
            'sha256': hashlib.sha256(zip_bytes).hexdigest(),
            'signature': bad_sig, 'publisher_key_id': 'test-pub',
            'min_panel_version': '0.0.1',
        })],
    })

    with pytest.raises(ValueError, match='Signature verification failed'):
        plugin_service.install_registry_extension('signed-ext')
    assert InstalledPlugin.query.filter_by(slug='signed-ext').first() is None


# --------------------------------------------------------------------------- #
# Preview verdicts (GitHub consent flow)
# --------------------------------------------------------------------------- #

def _stub_preview_downloads(monkeypatch, zip_bytes, sig_b64):
    monkeypatch.setattr(
        plugin_service, '_download_resolved', lambda resolved: io.BytesIO(zip_bytes))
    monkeypatch.setattr(
        plugin_service, '_fetch_detached_signature', lambda resolved: sig_b64)


def test_preview_reports_verified_signature(app, tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    sig = signing_service.sign_bytes(zip_bytes, priv)
    _stub_preview_downloads(monkeypatch, zip_bytes, sig)

    preview = plugin_service.preview_from_url('https://x/signed-ext.zip')
    assert preview['signature']['status'] == 'verified'
    assert preview['signature']['publisher'] == 'Test Publisher'
    assert preview['signature']['signature'] == sig


def test_preview_reports_unsigned_when_no_minisig(app, monkeypatch):
    zip_bytes = _make_plugin_zip()
    _stub_preview_downloads(monkeypatch, zip_bytes, None)

    preview = plugin_service.preview_from_url('https://x/signed-ext.zip')
    assert preview['signature']['status'] == 'unsigned'
    assert preview['signature']['signature'] is None


def test_preview_reports_invalid_signature(app, tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    _stub_preview_downloads(
        monkeypatch, zip_bytes, signing_service.sign_bytes(b'other', priv))

    preview = plugin_service.preview_from_url('https://x/signed-ext.zip')
    assert preview['signature']['status'] == 'invalid'
    assert preview['signature']['error']


# --------------------------------------------------------------------------- #
# Registry consent gate (unsigned / untrusted-key policy)
# --------------------------------------------------------------------------- #

class _FakePlugin:
    id = 1
    name = 'gated-ext'
    slug = 'gated-ext'
    version = '1.0.0'

    def to_dict(self):
        return {'name': self.name, 'version': self.version}


@pytest.fixture
def fake_install(monkeypatch):
    monkeypatch.setattr(
        plugin_service, 'install_registry_extension',
        lambda slug, user_id=None: _FakePlugin())


def _seed_entry(monkeypatch, entry):
    monkeypatch.setattr(registry_service, '_cache', {
        'ts': 9e18, 'source': 'test', 'entries': [entry],
    })


def _gate_entry(tmp_path, monkeypatch, **overrides):
    """A reviewed third-party entry (so the unreviewed/unverified gates stay
    out of the way) with a pinned checksum; signature fields per overrides."""
    base = {
        'slug': 'gated-ext', 'display_name': 'Gated', 'version': '1.0.0',
        'source': 'https://x/g.zip', 'sha256': 'c' * 64,
        'review': {'reviewer': 'jhd3197', 'sha256': 'c' * 64},
    }
    base.update(overrides)
    return registry_service._normalize(base)


def test_gate_signed_trusted_key_installs_without_ack(
        app, client, auth_headers, fake_install, tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    sig = signing_service.sign_bytes(b'zip', priv)
    _seed_entry(monkeypatch, _gate_entry(
        tmp_path, monkeypatch, signature=sig, publisher_key_id='test-pub'))

    resp = client.post('/api/v1/marketplace/registry/gated-ext/install',
                       headers=auth_headers)
    assert resp.status_code == 201


def test_gate_untrusted_key_requires_ack(
        app, client, auth_headers, fake_install, tmp_path, monkeypatch):
    stranger = Ed25519PrivateKey.generate()
    sig = signing_service.sign_bytes(b'zip', stranger)
    _seed_entry(monkeypatch, _gate_entry(
        tmp_path, monkeypatch, signature=sig, publisher_key_id='stranger'))

    resp = client.post('/api/v1/marketplace/registry/gated-ext/install',
                       headers=auth_headers)
    assert resp.status_code == 409
    data = resp.get_json()
    assert data['requires_acknowledgment'] is True
    assert data['reason'] == 'untrusted_key'
    assert 'stranger' in data['error']

    resp = client.post('/api/v1/marketplace/registry/gated-ext/install',
                       headers=auth_headers, json={'acknowledge_risk': True})
    assert resp.status_code == 201


def test_gate_unsigned_is_not_blocked_beyond_existing_gates(
        app, client, auth_headers, fake_install, tmp_path, monkeypatch):
    """Unsigned = honest badge + the existing gates, never a hard block (D3):
    a reviewed (or first-party) entry without a signature installs as before."""
    _seed_entry(monkeypatch, _gate_entry(tmp_path, monkeypatch))
    resp = client.post('/api/v1/marketplace/registry/gated-ext/install',
                       headers=auth_headers)
    assert resp.status_code == 201


def test_gate_existing_reasons_unchanged(
        app, client, auth_headers, fake_install, tmp_path, monkeypatch):
    """The new signature reasons don't disturb the pre-existing gate order:
    unreviewed still wins, then missing-checksum."""
    e = _gate_entry(tmp_path, monkeypatch, review=None)  # → unreviewed
    assert e['trust'] == 'unreviewed'
    _seed_entry(monkeypatch, e)
    resp = client.post('/api/v1/marketplace/registry/gated-ext/install',
                       headers=auth_headers)
    assert resp.status_code == 409
    assert resp.get_json()['reason'] == 'unreviewed'

    e = _gate_entry(tmp_path, monkeypatch, sha256=None, review=None,
                    first_party=True)  # trusted publisher, no pinned checksum
    assert e['trust'] == 'first_party'
    _seed_entry(monkeypatch, e)
    resp = client.post('/api/v1/marketplace/registry/gated-ext/install',
                       headers=auth_headers)
    assert resp.status_code == 409
    assert resp.get_json()['reason'] == 'unverified'


# --------------------------------------------------------------------------- #
# /plugins/install signature passthrough
# --------------------------------------------------------------------------- #

def test_install_endpoint_rejects_bad_signature(
        app, client, auth_headers, plugin_dirs, tmp_path, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _pin_keys(tmp_path, monkeypatch, [('test-pub', priv, 'Test Publisher')])
    zip_bytes = _make_plugin_zip()
    bad_sig = signing_service.sign_bytes(b'other bytes', priv)
    monkeypatch.setattr(plugin_service, '_download_zip', lambda url: io.BytesIO(zip_bytes))

    resp = client.post('/api/v1/plugins/install', headers=auth_headers, json={
        'url': 'https://x/signed-ext.zip',
        'signature': bad_sig,
        'publisher_key_id': 'test-pub',
    })
    assert resp.status_code == 400
    assert 'Signature verification failed' in resp.get_json()['error']
    assert InstalledPlugin.query.filter_by(slug='signed-ext').first() is None
