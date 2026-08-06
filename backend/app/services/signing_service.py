"""Extension release signing — ed25519 detached signatures (plan 55, D3).

Signature format (minisign-style envelope, base64 of 74 bytes)::

    "ED" (2 bytes) || key_num (8 bytes) || ed25519 signature (64 bytes)

- ``ED`` is the minisign legacy/pure marker: the 64-byte ed25519 signature is
  over the *raw* release-zip bytes (no prehash, no trusted comment).
- ``key_num`` is ``sha256(public_key)[:8]`` — it binds the envelope to the
  exact key that made it, so a ``publisher_key_id`` cannot be pointed at a
  different pinned key than the one that signed.

Key model (D3 — minimal and boring): no PKI, no key servers. The panel pins
publisher public keys in ``backend/app/data/extension_signing_keys.json``
(first-party key ships there). Operators can trust additional publisher keys
by pointing ``SERVERKIT_TRUSTED_EXTENSION_KEYS`` at a second JSON file with
the same shape — that is also the rotation story: pin the new key, sign new
releases with it, drop the old entry once nothing references it.

Verification outcomes are a status dict, never exceptions:

- ``verified``      — signature valid under a pinned key
- ``unsigned``      — no signature supplied
- ``untrusted_key`` — signature present, but its key is not pinned
- ``invalid``       — malformed envelope, key_id/key_num mismatch, or the
                      ed25519 verify failed (tamper) — the only hard failure
"""
import base64
import binascii
import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

_MARKER = b'ED'  # pure ed25519 over raw bytes (minisign legacy marker)
_ENVELOPE_LEN = 2 + 8 + 64
_RAW_KEY_LEN = 32

_PINNED_KEYS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'extension_signing_keys.json',
)


def key_num_for(public_key_raw):
    """The 8-byte envelope key id: sha256(raw public key) truncated."""
    return hashlib.sha256(public_key_raw).digest()[:8]


def _load_keys_file(path, merged):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except Exception as e:
        logger.warning(f'Could not read extension signing keys {path}: {e}')
        return
    for entry in payload.get('keys') or []:
        key_id = entry.get('key_id')
        if not key_id or entry.get('algorithm') != 'ed25519':
            logger.warning(f'Skipping malformed signing key entry in {path}: {entry!r}')
            continue
        try:
            raw = base64.b64decode(entry.get('public_key') or '', validate=True)
        except (binascii.Error, ValueError):
            logger.warning(f'Signing key {key_id} in {path}: bad base64 public key')
            continue
        if len(raw) != _RAW_KEY_LEN:
            logger.warning(f'Signing key {key_id} in {path}: public key must be 32 bytes')
            continue
        merged[key_id] = {
            'public_key': raw,
            'publisher': entry.get('publisher') or key_id,
            'key_num': key_num_for(raw),
        }


def load_trusted_keys():
    """Return ``{key_id: {public_key, publisher, key_num}}`` — the pinned
    first-party keys plus any operator-added file (rotation/extra publishers).
    Read fresh each call: files are tiny and this keeps key rotation a
    file-edit with no restart dependency beyond the next verify."""
    merged = {}
    _load_keys_file(_PINNED_KEYS_FILE, merged)
    extra = (os.environ.get('SERVERKIT_TRUSTED_EXTENSION_KEYS') or '').strip()
    if extra:
        _load_keys_file(extra, merged)
    return merged


def is_trusted_key(key_id):
    """True when ``key_id`` names a pinned/operator-trusted publisher key."""
    if not key_id:
        return False
    return key_id in load_trusted_keys()


def sign_bytes(data, private_key, _key_id=None):
    """Build the base64 signature envelope for ``data``.

    ``private_key`` is a ``cryptography`` Ed25519PrivateKey. Lives here (not
    just in the author-facing scripts/sign-extension.mjs) so tests prove the
    panel verifies exactly what the tooling produces. ``_key_id`` is accepted
    for call-site symmetry and ignored — the envelope binds the key by its
    derived key_num, not by a claimed name.
    """
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat,
    )
    pub_raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw,
    )
    envelope = _MARKER + key_num_for(pub_raw) + private_key.sign(data)
    return base64.b64encode(envelope).decode('ascii')


def _result(status, key_id=None, publisher=None, error=None):
    out = {'status': status, 'key_id': key_id, 'publisher': publisher}
    if error:
        out['error'] = error
    return out


def verify_detached(data, signature_b64, key_id=None):
    """Verify a base64 signature envelope over ``data`` against trusted keys.

    ``key_id`` (the registry index's ``publisher_key_id``) selects the pinned
    key; when omitted (the GitHub ``.minisig`` flow has no index) the pinned
    key is located by the envelope's embedded key_num. Returns the status
    dicts documented at the top of this module — never raises.
    """
    if not signature_b64:
        return _result('unsigned')

    try:
        blob = base64.b64decode(str(signature_b64).strip(), validate=True)
    except (binascii.Error, ValueError):
        return _result('invalid', key_id=key_id,
                       error='signature is not valid base64')
    if len(blob) != _ENVELOPE_LEN or blob[:2] != _MARKER:
        return _result(
            'invalid', key_id=key_id,
            error='signature is not a ServerKit ed25519 envelope '
                  '(expected base64 of "ED" || key_num || 64-byte signature)')

    key_num, sig = blob[2:10], blob[10:]
    keys = load_trusted_keys()

    if key_id:
        entry = keys.get(key_id)
        if not entry:
            return _result('untrusted_key', key_id=key_id)
        if key_num != entry['key_num']:
            return _result(
                'invalid', key_id=key_id,
                error=f"signature was made by a different key than "
                      f"publisher_key_id '{key_id}' names")
        candidates = [(key_id, entry)]
    else:
        candidates = [(k, e) for k, e in keys.items() if e['key_num'] == key_num]
        if not candidates:
            return _result('untrusted_key')

    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )
    from cryptography.exceptions import InvalidSignature

    for candidate_id, entry in candidates:
        try:
            Ed25519PublicKey.from_public_bytes(entry['public_key']).verify(sig, data)
            return _result('verified', key_id=candidate_id,
                           publisher=entry['publisher'])
        except InvalidSignature:
            continue
        except Exception as e:  # defensive: a corrupt pinned key file
            logger.warning(f'Signature verify with key {candidate_id} errored: {e}')
            continue

    return _result(
        'invalid', key_id=key_id,
        error='ed25519 signature does not match the archive bytes '
              '(the download may have been tampered with)')


def verify_for_install(data, signature_b64, key_id=None):
    """Install-time gate: verify and raise ValueError on 'invalid' only.

    'verified' and 'untrusted_key' both return their status dict (the caller
    decides whether an untrusted publisher needed consent first); 'unsigned'
    is returned when no signature was supplied. A bad signature is NEVER
    consent-overridable — tamper evidence is the whole point.
    """
    result = verify_detached(data, signature_b64, key_id)
    if result['status'] == 'invalid':
        raise ValueError(
            f"Signature verification failed — refusing to install. "
            f"{result.get('error')}. If you published this extension, re-sign "
            f"the exact zip you released (scripts/sign-extension.mjs); if you "
            f"are installing it, do not proceed — fetch it again from the "
            f"original source."
        )
    if result['status'] == 'untrusted_key':
        logger.warning(
            f"Extension signature references unpinned publisher key "
            f"{result.get('key_id') or '(unknown)'} — installing as unsigned-equivalent"
        )
    return result
