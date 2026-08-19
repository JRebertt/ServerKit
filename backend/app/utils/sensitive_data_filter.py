"""Centralized sensitive-data masking for API responses.

This is a *defense-in-depth* response filter that walks an arbitrary
dict/list payload and redacts values whose key looks sensitive (password,
secret, token, private key, key hash, etc.) to ``'••••••••'``.

It is intentionally dependency-light (no Flask import at module top level beyond
a lazy ``g`` lookup) so it is trivially unit-testable in isolation.

Scope awareness: if the caller's effective scopes include ``secrets:read`` (or
full access ``'*'``), masking is skipped — those callers explicitly opted in to
seeing secret material. JWT/session users default to full access (the UI already
gates secret reveal in its own surfaces).
"""
import re

# The literal mask shown in place of a redacted value. Matches the per-model
# masking convention already used in env_variable.py / secret_vault.py.
MASK = '••••••••'

# The scope that, when present, disables masking.
REVEAL_SCOPE = 'secrets:read'

# Substrings that mark a dict key as sensitive. Matched case-insensitively
# against the key name. THE union of every sink's former private list
# (plan 77 F3): response filter, audit_service, middleware/audit (the only
# one that covered totp/otp/csrf/session), telemetry. A keyword added here
# is redacted by ALL sinks; adding one to a single sink again is ratcheted
# by tests/test_redaction_one_door.py.
SENSITIVE_KEY_PARTS = (
    'password',
    'passwd',
    'secret',        # subsumes secret_key / client_secret
    'token',
    'credential',
    'private',       # subsumes private_key / privatekey
    'certificate',
    'api_key',
    'apikey',
    'key_hash',
    'access_key',
    'auth',          # subsumes authorization
    'passphrase',
    'cookie',
    'session',       # subsumes session_key
    'totp',
    'otp',
    'csrf',
)

# Backwards-compat alias (older callers/tests import the list name).
SENSITIVE_KEY_PATTERNS = list(SENSITIVE_KEY_PARTS)

# Keys that *contain* a sensitive substring but are safe to keep (false
# positives we explicitly allow through). e.g. "is_secret" is a boolean flag,
# not a secret value; "token_expires_at" is metadata.
_SAFE_KEY_EXCEPTIONS = {
    'is_secret',
    'has_secret',
    'secret_count',
    'token_expires_at',
    'token_type',
    'auth_method',
    'auth_type',
    'authenticated',
    'authorized',
    'authentication',
    'authorization_url',
    # identifier/metadata keys the union parts would otherwise swallow:
    'sessions',
    'session_count',
    'totp_enabled',
    'otp_enabled',
    'certificate',        # public cert material/metadata, not a secret
    'certificates',
    'total_certificates',
    'private_slug',
    'private_url',
    'private_url_enabled',
    'private_wg_ip',
    'private_server_name',
    'private_server_id',
    'private_pubkey',     # a PUBLIC key
}

_PATTERN_RE = re.compile('|'.join(re.escape(p) for p in SENSITIVE_KEY_PARTS), re.IGNORECASE)


def is_sensitive_key(key):
    """Return True if a dict key name should be masked."""
    if not isinstance(key, str):
        return False
    low = key.lower()
    if low in _SAFE_KEY_EXCEPTIONS:
        return False
    return bool(_PATTERN_RE.search(low))


def _scopes_allow_reveal(allowed_scopes):
    """True if the given scope list permits seeing unmasked secrets."""
    if not allowed_scopes:
        return False
    if '*' in allowed_scopes or REVEAL_SCOPE in allowed_scopes:
        return True
    # honor a resource wildcard like 'secrets:*'
    if 'secrets:*' in allowed_scopes:
        return True
    return False


def scopes_for_request():
    """Return the current request's effective scopes.

    * API-key requests → the key's own scopes (``g.api_key.get_scopes()``).
    * JWT/session requests (or outside a request) → ``['*']`` (full access),
      because those callers are governed by RBAC, not key scopes.
    """
    try:
        from flask import g
        api_key = getattr(g, 'api_key', None)
        if api_key is not None:
            return api_key.get_scopes() or []
    except Exception:
        # No app/request context — treat as full access for non-keyed callers.
        pass
    return ['*']


def mask_sensitive(data, allowed_scopes=None):
    """Recursively redact sensitive values in ``data``.

    Args:
        data: Any JSON-serializable structure (dict / list / scalar).
        allowed_scopes: Optional explicit scope list. When ``None``, the
            current request's scopes are resolved via :func:`scopes_for_request`.

    Returns:
        A new structure with sensitive *values* replaced by :data:`MASK`.
        ``None`` values are left as ``None`` (nothing to hide). If the caller's
        scopes permit reveal, ``data`` is returned unchanged.
    """
    if allowed_scopes is None:
        allowed_scopes = scopes_for_request()

    if _scopes_allow_reveal(allowed_scopes):
        return data

    return _mask(data, sensitive=False)


def _mask(value, sensitive):
    """Walk the structure. ``sensitive`` marks that the current value sits under
    a sensitive key and (if scalar) must be redacted."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k] = _mask(v, sensitive=is_sensitive_key(k))
        return out
    if isinstance(value, (list, tuple)):
        masked = [_mask(item, sensitive=sensitive) for item in value]
        return type(value)(masked) if isinstance(value, tuple) else masked
    # Scalar
    if sensitive and value is not None:
        return MASK
    return value


# Mask used by the LOG sinks (audit middleware / audit_service / telemetry).
REDACTED = '[redacted]'


def mask_payload(data, mask=REDACTED, max_depth=6):
    """Unconditionally redact sensitive values in ``data`` (no scope logic).

    The log-sink twin of :func:`mask_sensitive`: audit and telemetry writers
    must never reveal secrets regardless of the caller's scopes. Depth-capped
    against pathological nesting; scalars pass through.
    """
    if max_depth < 0:
        return mask
    if isinstance(data, dict):
        return {
            k: (mask if is_sensitive_key(k)
                else mask_payload(v, mask, max_depth - 1))
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [mask_payload(v, mask, max_depth - 1) for v in data]
    return data
