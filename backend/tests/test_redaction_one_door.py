"""Plan 77 F3 — ONE sensitive-keyword list, four sinks.

utils/sensitive_data_filter.py owns SENSITIVE_KEY_PARTS and
is_sensitive_key(); the response filter, audit_service, middleware/audit and
telemetry all consume it. The ratchet asserts no sink re-grows a private
list, so a keyword added to the union is redacted everywhere at once.
"""
import re
from pathlib import Path

from app.utils import sensitive_data_filter as sdf

APP = Path(__file__).resolve().parents[1] / 'app'


def test_union_covers_every_sinks_former_keywords():
    formerly_split = {
        # utils' originals
        'password', 'passwd', 'secret', 'token', 'credential',
        'api_key', 'apikey', 'key_hash', 'access_key', 'auth', 'passphrase',
        # middleware-only additions the other sinks used to miss
        'private', 'certificate', 'cookie', 'session', 'totp', 'otp', 'csrf',
    }
    for part in formerly_split:
        assert any(part.find(u) != -1 or u.find(part) != -1
                   for u in sdf.SENSITIVE_KEY_PARTS), part
        # every former keyword must actually trigger the shared predicate
        assert sdf.is_sensitive_key(f'x_{part}_value'), part


def test_sinks_delegate_to_shared_predicate():
    from app.services import audit_service, telemetry_service
    from app.middleware import audit as audit_mw
    # csrf/totp were middleware-only; session_key was utils-only — every sink
    # must now agree on both.
    for key in ('csrf_token', 'totp_secret', 'session_key', 'x_cookie'):
        assert audit_service.AuditService.is_sensitive_key(key), key
        assert telemetry_service._is_sensitive_key(key), key
        assert audit_mw._is_sensitive_key(key), key
        assert sdf.is_sensitive_key(key), key


def test_safe_exceptions_pass_through_everywhere():
    for key in ('totp_enabled', 'private_url', 'certificates', 'has_secret'):
        assert not sdf.is_sensitive_key(key), key


def test_mask_payload_masks_recursively():
    data = {'name': 'ok', 'password': 'x', 'nested': [{'api_key': 'k'}],
            'totp_enabled': True}
    out = sdf.mask_payload(data)
    assert out['name'] == 'ok'
    assert out['password'] == sdf.REDACTED
    assert out['nested'][0]['api_key'] == sdf.REDACTED
    assert out['totp_enabled'] is True


def test_no_private_sensitive_lists_regrow():
    """Ratchet: no literal SENSITIVE list definitions outside the one door."""
    pattern = re.compile(r'^SENSITIVE\w*\s*=\s*[\(\[]', re.M)
    offenders = []
    for f in APP.rglob('*.py'):
        if f.name == 'sensitive_data_filter.py' or '__pycache__' in str(f):
            continue
        if pattern.search(f.read_text(encoding='utf-8', errors='replace')):
            offenders.append(str(f.relative_to(APP)))
    assert not offenders, (
        f"Private sensitive-keyword lists re-grown in {offenders} — extend "
        "utils/sensitive_data_filter.SENSITIVE_KEY_PARTS instead (plan 77 F3)."
    )
