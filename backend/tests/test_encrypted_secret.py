"""Plan 77 C1 — the EncryptedSecret descriptor is the one crypto path for
model-owned ``*_encrypted`` columns.

Contracts proven here:
- round-trip: assignment encrypts (ciphertext lands in the backing column,
  not plaintext), read decrypts.
- an ENCRYPT failure raises — never swallowed, never silently stored as
  nothing (the historical server.py accessor printed and dropped the secret).
- a DECRYPT failure (wrong key / corrupt ciphertext) returns None so auth
  paths degrade instead of 500ing.
- ``is_set`` provides the has_secret masking flag without decrypting.
"""
import pytest

import app.utils.crypto as crypto
from app.models.mixins import EncryptedSecret
from app.models.server import Server


class _Box:
    """Plain object with a backing attribute — descriptor works on any class."""
    secret_encrypted = None
    secret = EncryptedSecret('secret_encrypted')


def test_round_trip_encrypts_backing_column(app):
    box = _Box()
    box.secret = 'hunter2'
    assert box.secret_encrypted, 'ciphertext must be stored'
    assert box.secret_encrypted != 'hunter2', 'plaintext must never be stored'
    assert box.secret == 'hunter2'


def test_assigning_none_clears_column(app):
    box = _Box()
    box.secret = 'hunter2'
    box.secret = None
    assert box.secret_encrypted is None
    assert box.secret is None


def test_encrypt_failure_raises(app, monkeypatch):
    def boom(_):
        raise RuntimeError('no key material')
    monkeypatch.setattr(crypto, 'encrypt_secret', boom)
    box = _Box()
    with pytest.raises(RuntimeError):
        box.secret = 'hunter2'
    assert box.secret_encrypted is None, 'a failed encrypt must not store anything'


def test_decrypt_failure_returns_none(app):
    box = _Box()
    box.secret_encrypted = 'not-real-fernet-ciphertext'
    assert box.secret is None


def test_is_set_masks_without_decrypting(app):
    box = _Box()
    assert _Box.secret.is_set(box) is False
    box.secret = 'hunter2'
    assert _Box.secret.is_set(box) is True


def test_server_accessors_ride_the_descriptor(app, monkeypatch):
    """server.py's legacy method names delegate to the descriptor: encrypt
    failures now RAISE out of set_api_secret_encrypted (regression: they were
    print()-swallowed, silently leaving the server secretless)."""
    server = Server(name='c1', agent_id='agent-c1')
    server.set_api_secret_encrypted('s3cret')
    assert server.api_secret_encrypted != 's3cret'
    assert server.get_api_secret() == 's3cret'

    def boom(_):
        raise RuntimeError('no key material')
    monkeypatch.setattr(crypto, 'encrypt_secret', boom)
    with pytest.raises(RuntimeError):
        server.set_api_secret_encrypted('other')


def test_server_key_rotation_round_trip(app):
    server = Server(name='c1-rot', agent_id='agent-c1-rot')
    key, secret, rotation_id = server.start_key_rotation()
    assert server.get_pending_api_secret() == secret
    assert server.complete_key_rotation(rotation_id) is True
    assert server.get_api_secret() == secret
    assert server.get_pending_api_secret() is None
