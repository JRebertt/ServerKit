"""Plan 77 C2 — the parallel Fernet stacks fold into utils/crypto.

New writes use the ONE key path (SERVERKIT_ENCRYPTION_KEY); reads dual-read
so rows/tokens written under the legacy SECRET_KEY-derived Fernet decrypt
forever — never a bulk decrypt-all -> re-encrypt-all pass (the PR #94
postmortem records that exact approach double-wrapping credentials).
"""
import base64
import hashlib

from cryptography.fernet import Fernet

from app.models.env_variable import EnvironmentVariable
from app.utils.crypto import decrypt_secret, is_encrypted


def _legacy_ciphertext(plaintext, secret_key='dev-secret-key-change-in-production'):
    key = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key)).encrypt(plaintext.encode()).decode()


def test_env_variable_new_writes_use_the_one_path(app):
    ciphertext = EnvironmentVariable.encrypt_value('hunter2')
    # decryptable by the ONE path directly — proof it is not the legacy key
    assert decrypt_secret(ciphertext) == 'hunter2'
    assert EnvironmentVariable.decrypt_value(ciphertext) == 'hunter2'


def test_env_variable_legacy_rows_still_decrypt(app, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    EnvironmentVariable._legacy_fernet = None  # re-derive under the known key
    legacy = _legacy_ciphertext('old-value')
    assert not is_encrypted(legacy), 'sanity: legacy ciphertext is not one-path'
    assert EnvironmentVariable.decrypt_value(legacy) == 'old-value'


def test_env_variable_corrupt_value_keeps_sentinel(app):
    assert EnvironmentVariable.decrypt_value('garbage') == '[DECRYPTION_ERROR]'
    assert EnvironmentVariable.decrypt_value('') == ''


def test_env_variable_property_round_trip(app):
    var = EnvironmentVariable(key='K')
    var.value = 'plain'
    assert var.encrypted_value != 'plain'
    assert var.value == 'plain'


def test_sso_tokens_fold_in(app, monkeypatch):
    from app.services import sso_service
    ciphertext = sso_service.encrypt_token('tok-123')
    assert decrypt_secret(ciphertext) == 'tok-123'
    assert sso_service.decrypt_token(ciphertext) == 'tok-123'

    with app.app_context():
        secret = app.config['SECRET_KEY']
    legacy = _legacy_ciphertext('tok-legacy', secret_key=secret)
    assert sso_service.decrypt_token(legacy) == 'tok-legacy'
    assert sso_service.decrypt_token('garbage') is None
    assert sso_service.decrypt_token(None) is None


def test_shared_resources_ride_the_same_path(app):
    """shared_resource reuses EnvironmentVariable.encrypt/decrypt_value, so
    the fold-in covers it automatically — pin that indirection."""
    from app.models.shared_resource import SharedVariable
    sv = SharedVariable.__new__(SharedVariable)
    ciphertext = EnvironmentVariable.encrypt_value('shared-secret')
    assert decrypt_secret(ciphertext) == 'shared-secret'
