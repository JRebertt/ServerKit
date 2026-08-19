"""Plan 77 C1 ratchet — services do not hand-roll crypto for model-owned
``*_encrypted`` columns.

Models that own an encrypted column expose it through the EncryptedSecret
descriptor (app/models/mixins.py); service code assigns/reads the plaintext
attribute and never calls encrypt_secret/decrypt_secret for those columns.

The allowlist below is the frozen 2026-08-19 population of service/api files
that import app.utils.crypto for NON-model-column material (settings-store
values, credentials_json maps, the vault service itself). Shrinking it is
progress; adding to it needs a reason that is not "the model has no
accessor" — give the model a descriptor instead.
"""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'app'

ALLOWED = {
    'services/ai_service.py',           # settings-store ai_api_key_encrypted
    'services/chat_webhook_service.py', # per-field maps inside credentials_json
    'services/connection_registry.py',
    'services/dns_provider_service.py',
    'services/dns_zone_service.py',
    'services/email_relay_service.py',
    'services/manifest_apply_service.py',
    'services/secret_vault_service.py', # owns SecretVault writes by design
    'services/settings_service.py',
    'services/sso_service.py',    # C2 fold-in: token crypto with legacy dual-read lives here
    'services/storage_provider_service.py',
    'services/source_connection_service.py',  # SettingsService-held PEM/webhook secret
    'api/ai.py',
    'api/system.py',
}

IMPORT_RE = re.compile(r'^\s*(from\s+app\.utils\.crypto\s+import|from\s+app\.utils\s+import\s+crypto|import\s+app\.utils\.crypto)', re.M)


def _importers():
    found = set()
    for sub in ('services', 'api'):
        for f in sorted((APP / sub).glob('*.py')):
            if IMPORT_RE.search(f.read_text(encoding='utf-8', errors='replace')):
                found.add(f'{sub}/{f.name}')
    return found


def test_no_new_service_level_crypto_callers():
    found = _importers()
    new = found - ALLOWED
    assert not new, (
        f"New app.utils.crypto importers in services/api: {sorted(new)}. "
        "If this is for a model-owned *_encrypted column, add an "
        "EncryptedSecret descriptor to the model instead (plan 77 C1)."
    )


def test_allowlist_does_not_go_stale():
    """A file leaving the list should be removed so the ratchet stays tight."""
    found = _importers()
    stale = ALLOWED - found
    assert not stale, f"Allowlist entries no longer importing crypto: {sorted(stale)} — delete them."
