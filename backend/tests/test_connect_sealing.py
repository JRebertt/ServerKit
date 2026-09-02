"""The panel half of end-to-end sealed commands.

ServerKit Cloud seals a command's arguments to this panel's X25519 key so the relay
carries them without being able to read them. These tests re-implement ServerKit Cloud's
sealing here — the same scheme, written independently from the specification —
and check that this panel opens it. If the two ever drift apart, this fails
rather than a customer's backup silently stopping.
"""
import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.services import connect_commands, connect_keys

DEVICE = 'dev_abc123'


@pytest.fixture()
def key_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(connect_keys.paths, 'SERVERKIT_CONFIG_DIR', str(tmp_path))
    return tmp_path


def seal_like_cloud(device_pubkey_hex: str, device_id: str, payload: dict) -> dict:
    """The control plane's sealing routine, written from the specification rather
    than imported: this is the interop check."""
    peer = X25519PublicKey.from_public_bytes(bytes.fromhex(device_pubkey_hex))
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(peer)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b'serverkit/cmd/v1|' + device_id.encode()).derive(shared)
    nonce = os.urandom(12)
    body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
    return {
        'alg': 'x25519-hkdf-aesgcm/v1',
        'epk': ephemeral.public_key().public_bytes_raw().hex(),
        'nonce': base64.b64encode(nonce).decode(),
        'ct': base64.b64encode(AESGCM(key).encrypt(nonce, body, device_id.encode())).decode(),
    }


# ---------- the key ----------


def test_the_key_is_generated_once_and_reused(key_dir):
    _, first = connect_keys.load_or_create_e2e_key()
    _, second = connect_keys.load_or_create_e2e_key()
    assert first == second
    assert len(bytes.fromhex(first)) == 32


def test_the_key_file_is_exactly_the_key(key_dir):
    connect_keys.load_or_create_e2e_key()
    path = connect_keys.default_e2e_key_path()
    assert os.path.getsize(path) == 32


def test_a_truncated_key_file_is_refused_rather_than_used(key_dir):
    connect_keys.load_or_create_e2e_key()
    with open(connect_keys.default_e2e_key_path(), 'wb') as f:
        f.write(b'short')
    with pytest.raises(ValueError):
        connect_keys.load_or_create_e2e_key()


def test_the_hello_publishes_the_key_signed_with_the_identity_key(key_dir):
    identity = Ed25519PrivateKey.generate()
    fields = connect_keys.e2e_hello_fields(identity, DEVICE)
    assert set(fields) == {'x25519_pubkey', 'x25519_sig'}
    # ServerKit Cloud verifies exactly this, so this test is that check run locally.
    identity.public_key().verify(
        bytes.fromhex(fields['x25519_sig']),
        connect_keys.e2e_binding_message(DEVICE, fields['x25519_pubkey']))


def test_the_binding_message_is_the_one_cloud_expects(key_dir):
    assert connect_keys.e2e_binding_message('dev_x', 'ab') == b'dev_x|x25519|ab'


# ---------- opening what ServerKit Cloud sealed ----------


def test_this_panel_opens_what_cloud_sealed(key_dir):
    _, pubkey_hex = connect_keys.load_or_create_e2e_key()
    payload = {'secret': 's3cr3t-value', 'bucket': 'sk-backups', 'prefix': 'serverkit/x/'}
    sealed = seal_like_cloud(pubkey_hex, DEVICE, payload)
    assert 's3cr3t-value' not in json.dumps(sealed)
    assert connect_keys.open_sealed(DEVICE, sealed) == payload


def test_a_payload_sealed_for_another_server_will_not_open(key_dir):
    _, pubkey_hex = connect_keys.load_or_create_e2e_key()
    sealed = seal_like_cloud(pubkey_hex, 'dev_someone_else', {'secret': 'x'})
    with pytest.raises(Exception):
        connect_keys.open_sealed(DEVICE, sealed)


def test_a_payload_sealed_to_a_different_key_will_not_open(key_dir):
    stranger = X25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    connect_keys.load_or_create_e2e_key()
    sealed = seal_like_cloud(stranger, DEVICE, {'secret': 'x'})
    with pytest.raises(Exception):
        connect_keys.open_sealed(DEVICE, sealed)


def test_an_unknown_algorithm_is_refused(key_dir):
    _, pubkey_hex = connect_keys.load_or_create_e2e_key()
    sealed = seal_like_cloud(pubkey_hex, DEVICE, {'x': 1})
    sealed['alg'] = 'rot13'
    with pytest.raises(ValueError):
        connect_keys.open_sealed(DEVICE, sealed)


# ---------- the command runner ----------


def test_a_command_with_plain_arguments_still_runs(key_dir):
    assert connect_commands.unseal_args({'args': {'a': 1}}) == {'a': 1}
    assert connect_commands.unseal_args({}) == {}


def test_a_sealed_command_is_unsealed_before_the_handler_sees_it(key_dir):
    _, pubkey_hex = connect_keys.load_or_create_e2e_key()
    sealed = seal_like_cloud(pubkey_hex, DEVICE, {'bucket': 'sk-backups'})
    got = connect_commands.unseal_args({'device_id': DEVICE, 'sealed': sealed})
    assert got == {'bucket': 'sk-backups'}


def test_a_sealed_command_we_cannot_open_is_refused_not_guessed(key_dir):
    """Running a command with arguments we guessed at is worse than not
    running it, so the handler never sees a half-read payload."""
    seen = []

    @connect_commands.handler('test.sealed')
    def _handler(args, app=None):
        seen.append(args)
        return {'ok': True}

    try:
        stranger = X25519PrivateKey.generate().public_key().public_bytes_raw().hex()
        connect_keys.load_or_create_e2e_key()
        sealed = seal_like_cloud(stranger, DEVICE, {'do': 'something'})
        out = connect_commands.run({'action': 'test.sealed', 'device_id': DEVICE,
                                    'sealed': sealed})
        assert out['ok'] is False
        assert 'could not use' in out['summary']
        assert 'Nothing was changed' in out['summary']
        assert seen == [], 'the handler must not run on arguments we could not read'
    finally:
        connect_commands.HANDLERS.pop('test.sealed', None)


def test_a_sealed_command_reaches_its_handler_intact(key_dir):
    seen = []

    @connect_commands.handler('test.sealed_ok')
    def _handler(args, app=None):
        seen.append(args)
        return {'ok': True, 'summary': 'done'}

    try:
        _, pubkey_hex = connect_keys.load_or_create_e2e_key()
        sealed = seal_like_cloud(pubkey_hex, DEVICE, {'secret': 'shh'})
        out = connect_commands.run({'action': 'test.sealed_ok', 'device_id': DEVICE,
                                    'sealed': sealed})
        assert out['ok'] is True
        assert seen == [{'secret': 'shh'}]
    finally:
        connect_commands.HANDLERS.pop('test.sealed_ok', None)
