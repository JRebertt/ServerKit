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
