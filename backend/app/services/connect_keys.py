"""Device keypair for ServerKit Cloud connect pairing.

The panel holds one Ed25519 keypair that identifies it as a device to the
ServerKit Cloud control plane. The private key lives next to the panel config
(``paths.SERVERKIT_CONFIG_DIR``) with mode 0600, mirroring how the agent
stores its pairing key (``/etc/serverkit-agent/pairing.key``).

Fingerprint contract (verified server-side by ServerKit Cloud): the first 16 hex chars
of sha256 over the RAW 32-byte public key, displayed in groups of four
(``a1b2 c3d4 e5f6 7890``).
"""
import hashlib
import logging
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import paths

logger = logging.getLogger(__name__)

KEY_FILENAME = 'connect_device_key.pem'
# The second keypair: X25519, used only to unseal command
# payloads. Separate from the identity key on purpose — an encryption key and
# a signing key have different lifetimes and different blast radii.
E2E_KEY_FILENAME = 'connect_e2e_key.bin'
# What the identity key signs so ServerKit Cloud knows this X25519 key is really ours.
E2E_BINDING = 'x25519'


def default_key_path() -> str:
    return os.path.join(paths.SERVERKIT_CONFIG_DIR, KEY_FILENAME)


def fingerprint_of(pubkey_bytes: bytes) -> str:
    """First 16 hex chars of sha256(raw pubkey bytes) — ServerKit Cloud's contract."""
    return hashlib.sha256(pubkey_bytes).hexdigest()[:16]


def format_fingerprint(fingerprint: str) -> str:
    """``a1b2c3d4e5f67890`` -> ``a1b2 c3d4 e5f6 7890`` (the agent's format)."""
    return ' '.join(fingerprint[i:i + 4] for i in range(0, len(fingerprint), 4))


def _public_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )


def _load_existing(path: str) -> Ed25519PrivateKey:
    with open(path, 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError(f'{path} is not an Ed25519 private key')
    if os.name != 'nt':
        os.chmod(path, 0o600)
    return private_key


def load_keypair(path: str = None):
    """Strictly load the device keypair; raises FileNotFoundError if absent.

    Returns (private_key, pubkey_hex, fingerprint). Used by the relay
    transport: generating a fresh key here would silently change the device
    identity and fail every hello signature.
    """
    path = path or default_key_path()
    private_key = _load_existing(path)
    pubkey_bytes = _public_bytes(private_key)
    return private_key, pubkey_bytes.hex(), fingerprint_of(pubkey_bytes)


def load_or_create_keypair(path: str = None):
    """Load the device keypair from ``path``, generating + persisting one if absent.

    Returns (private_key, pubkey_hex, fingerprint). The file is written with
    mode 0600; on POSIX an existing file with looser permissions is tightened.
    """
    path = path or default_key_path()
    if os.path.exists(path):
        private_key = _load_existing(path)
    else:
        private_key = Ed25519PrivateKey.generate()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        # O_EXCL so a lost race regenerates instead of clobbering a live key.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(pem)
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        if os.name != 'nt':
            os.chmod(path, 0o600)
        logger.info('Generated ServerKit Cloud device key at %s', path)

    pubkey_bytes = _public_bytes(private_key)
    return private_key, pubkey_bytes.hex(), fingerprint_of(pubkey_bytes)


# ==================== end-to-end key ====================


def default_e2e_key_path() -> str:
    return os.path.join(paths.SERVERKIT_CONFIG_DIR, E2E_KEY_FILENAME)


def load_or_create_e2e_key(path: str = None):
    """The X25519 private key this panel unseals commands with.

    Raw 32 bytes on disk at 0600, not PEM: it is a symmetric-shaped secret
    with no certificate story around it, and a file that is exactly the key is
    a file nobody misreads.

    Returns (private_key, pubkey_hex).
    """
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    path = path or default_e2e_key_path()
    if os.path.exists(path):
        with open(path, 'rb') as f:
            raw = f.read()
        if len(raw) != 32:
            raise ValueError(f'{path} is not a 32-byte X25519 private key')
        private_key = X25519PrivateKey.from_private_bytes(raw)
        if os.name != 'nt':
            os.chmod(path, 0o600)
    else:
        private_key = X25519PrivateKey.generate()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(private_key.private_bytes_raw())
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        if os.name != 'nt':
            os.chmod(path, 0o600)
        logger.info('Generated ServerKit Cloud end-to-end key at %s', path)
    return private_key, private_key.public_key().public_bytes_raw().hex()


def e2e_binding_message(device_id: str, pubkey_hex: str) -> bytes:
    """The bytes the identity key signs to publish an X25519 key. Must match
    the control plane's binding message exactly, or it will not seal."""
    return f'{device_id}|{E2E_BINDING}|{pubkey_hex}'.encode()


def e2e_hello_fields(identity_key, device_id: str, path: str = None) -> dict:
    """The two hello fields that publish this panel's end-to-end key.

    Signed with the identity key, so a relay that wanted to read command
    payloads cannot substitute a key of its own — it does not have this
    signature and cannot make one.
    """
    _private, pubkey_hex = load_or_create_e2e_key(path)
    sig = identity_key.sign(e2e_binding_message(device_id, pubkey_hex)).hex()
    return {'x25519_pubkey': pubkey_hex, 'x25519_sig': sig}


def open_sealed(device_id: str, sealed: dict, path: str = None) -> dict:
    """Unseal a command payload. Raises if the algorithm is not one we know:
    a command we cannot read is refused, never guessed at."""
    import base64
    import json

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    alg = (sealed or {}).get('alg')
    if alg != 'x25519-hkdf-aesgcm/v1':
        raise ValueError(f'unknown sealing algorithm {alg!r}')
    private_key, _ = load_or_create_e2e_key(path)
    shared = private_key.exchange(
        X25519PublicKey.from_public_bytes(bytes.fromhex(sealed['epk'])))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b'serverkit/cmd/v1|' + device_id.encode()).derive(shared)
    plaintext = AESGCM(key).decrypt(base64.b64decode(sealed['nonce']),
                                    base64.b64decode(sealed['ct']), device_id.encode())
    return json.loads(plaintext.decode())
