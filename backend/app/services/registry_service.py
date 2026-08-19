"""Remote extension registry (Phase 2).

The registry is a single curated `index.json` (hosted in a `serverkit-extensions`
repo, submitted via PR). It lists third-party + first-party extensions that aren't
bundled with the panel, so the Marketplace Browse tab has real content without any
DB seeding.

Design rules:
  - Read-only discovery. NOTHING here ever auto-installs; installs are explicit.
  - Offline-tolerant. A failed/absent fetch falls back to the last good cache, then
    to a bundled copy (app/data/registry_index.json) — the Marketplace never blanks.
  - Configurable. SERVERKIT_REGISTRY_URL points at the live index. Unset ⇒ the
    public serverkit-extensions registry; set-but-EMPTY ⇒ explicitly disabled
    (bundled copy only — also how the test suite stays offline).
"""
import json
import logging
import os
import re
import time
from urllib.parse import urljoin

import requests

from app.models.plugin import InstalledPlugin
from app.utils.remote_index import CachedRemoteIndex

logger = logging.getLogger(__name__)

_BUNDLED_INDEX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'registry_index.json'
)

# The curated public index (one JSON file, PR-reviewed, checksum-verified
# installs). Panels fall back to cache → bundled copy when unreachable.
#
# The default goes through serverkit.ai, which proxies the raw-GitHub index
# with caching, serves logo art locally, and rewrites relative logo paths to
# absolute serverkit.ai URLs. The raw-GitHub index stays available as a
# manual fallback via SERVERKIT_REGISTRY_URL.
DEFAULT_REGISTRY_URL = (
    'https://serverkit.ai/ext/index.json'
)



# Fields we surface for a registry entry, with defaults. Index v2 adds
# `repo`, `logo`, and `bundled` (see the serverkit-extensions schema); any
# field not listed here is stripped before it reaches the UI, so new index
# fields must be registered below to survive normalization.
_FIELDS = {
    'slug': '',
    'display_name': '',
    'description': '',
    'version': '0.0.0',
    'category': 'utility',
    'author': '',
    'first_party': False,
    'bundled': False,
    'permissions': [],
    'min_panel_version': None,
    'max_panel_version': None,
    'source': '',
    'sha256': None,
    # Index schema v3 (plan 55 D3): optional ed25519 detached signature over
    # the release zip + the publisher key id that must verify it. Absent in
    # v1/v2 indexes → the entry is treated as unsigned (consent, not a block).
    'signature': None,
    'publisher_key_id': None,
    'review': None,
    'repo': '',
    'logo': None,
    'homepage': '',
    'icon': None,
    'screenshots': [],
    'featured': False,
    'feature_score': 0,
}


def _resolve_logo(logo, base_url):
    """Turn a repo-relative logo path (``assets/<slug>/<file>``) into an
    absolute URL against the index we fetched it from. Absolute https logos
    pass through unchanged; ``urljoin`` resolves both the raw-GitHub index
    (→ raw asset URL) and the serverkit.ai ``/ext/index.json`` (→ proxy URL)."""
    if not logo or not isinstance(logo, str):
        return logo
    if logo.startswith('http://') or logo.startswith('https://'):
        return logo
    if base_url:
        return urljoin(base_url, logo)
    return logo


# A review stamp counts only when it pins a full lowercase sha256 digest —
# anything else is treated as absent (never trusted by shape alone).
_REVIEW_SHA_RE = re.compile(r'^[0-9a-f]{64}$')


def _validate_review(review):
    """Keep a `review` stamp only if it is a dict whose `sha256` is a 64-char
    lowercase hex digest of the exact artifact the reviewer inspected."""
    if not isinstance(review, dict):
        return None
    sha = review.get('sha256')
    if not isinstance(sha, str) or not _REVIEW_SHA_RE.match(sha):
        return None
    return review


def _derive_trust(entry):
    """first_party > reviewed (review stamp hash-bound to the entry's sha256)
    > unreviewed. A stale stamp (artifact changed → sha256 moved on) never
    counts: the reviewer vouched for exact bytes, not a slug."""
    if entry['first_party']:
        return 'first_party'
    review = entry['review']
    if review and entry['sha256'] and review['sha256'] == entry['sha256']:
        return 'reviewed'
    return 'unreviewed'


def _normalize(raw, base_url=None):
    if not isinstance(raw, dict) or not raw.get('slug'):
        return None
    out = {}
    for key, default in _FIELDS.items():
        out[key] = raw.get(key, default)
    if not isinstance(out['permissions'], list):
        out['permissions'] = []
    if not isinstance(out['screenshots'], list):
        out['screenshots'] = []
    out['bundled'] = bool(out['bundled'])
    out['logo'] = _resolve_logo(out['logo'], base_url)
    out['review'] = _validate_review(out['review'])
    # Signature fields only count as well-formed strings; a signature without
    # a key id (or vice versa) is meaningless and collapses to unsigned.
    if not isinstance(out['signature'], str) or not out['signature'].strip():
        out['signature'] = None
    if not isinstance(out['publisher_key_id'], str) or not out['publisher_key_id'].strip():
        out['publisher_key_id'] = None
    if not out['signature'] or not out['publisher_key_id']:
        out['signature'] = None
        out['publisher_key_id'] = None
    # Whether the named publisher key is pinned by this panel — drives the
    # catalog badge / 409 consent distinction between "signed" and "signed by
    # someone we don't know". The crypto check itself happens at install.
    from app.services import signing_service
    out['publisher_trusted'] = signing_service.is_trusted_key(out['publisher_key_id'])
    out['trust'] = _derive_trust(out)
    return out


def _read_index_payload(payload, base_url=None):
    exts = payload.get('extensions') if isinstance(payload, dict) else None
    if not isinstance(exts, list):
        return []
    return [e for e in (_normalize(x, base_url) for x in exts) if e]


# One remote-catalog engine (plan 77 F1): fetch -> TTL -> last-good ->
# bundled, with the failure-retry throttling theme_registry had already
# hardened to. This module stays a thin normalizer (_read_index_payload).
_index = CachedRemoteIndex(
    name='Registry',
    env_var='SERVERKIT_REGISTRY_URL',
    default_url=DEFAULT_REGISTRY_URL,
    normalize_fn=_read_index_payload,
    bundled_path=_BUNDLED_INDEX,
    # Bundled copy mirrors the public index; resolve its relative logos
    # against the default index base.
    bundled_base_url=DEFAULT_REGISTRY_URL,
    ttl=3600,
    ttl_env_var='SERVERKIT_REGISTRY_TTL',
)

# Test seam: the shared cache dict (tests reset/seed it in place).
_cache = _index._cache


def refresh(force=False):
    """Return the registry entries, refreshing from the remote index when the
    cache is stale. Never raises — falls back to cache, then bundled copy."""
    return _index.get(force=force)


def _show_unreviewed():
    """Unreviewed community entries are developer-stage content.

    They list in the Marketplace (and install, behind the 409 risk
    acknowledgment) only when the panel runs in a development context:
    Flask debug mode (development/testing config) or the ``dev_mode``
    setting toggled on in Settings. Production panels with dev_mode off
    never see them — a hidden extension is not installable either.
    """
    try:
        from flask import current_app
        if current_app.debug or current_app.config.get('TESTING'):
            return True
    except RuntimeError:
        return False  # no app context (CLI/scripts): hide by default
    try:
        from app.services.settings_service import SettingsService
        return bool(SettingsService.get('dev_mode'))
    except Exception:
        return False


def list_extensions():
    return refresh()


def get_entry(slug):
    for e in refresh():
        if e['slug'] == slug:
            return e
    return None


def _install_state(slug):
    p = InstalledPlugin.query.filter_by(slug=slug).first()
    if not p:
        return {'installed': False, 'status': 'not_installed', 'installed_version': None}
    return {
        'installed': True,
        'status': p.status,
        'installed_version': p.version,
    }


def to_catalog_dict(entry):
    """Registry entry + live install state, for the Marketplace Browse merge."""
    d = dict(entry)
    d.update(_install_state(entry['slug']))
    d['source_kind'] = 'registry'
    return d


def list_catalog(include_bundled=False):
    """Registry entries + live install state for the Marketplace Browse merge.

    Bundled entries (``bundled: true``) are catalog listings for extensions
    that ship inside the panel — the Browse tab already renders those from
    ``list_builtin_extensions()``, so a bundled index entry would duplicate
    the card. They are excluded by default; pass ``include_bundled=True`` to
    get the complete catalog (e.g. for the public gallery API)."""
    entries = refresh()
    if not include_bundled:
        entries = [e for e in entries if not e.get('bundled')]
    if not _show_unreviewed():
        entries = [e for e in entries if e.get('trust') != 'unreviewed']
    return [to_catalog_dict(e) for e in entries]


def registry_source_label():
    return _cache.get('source')


def signature_consent_reason(entry):
    """The signature-side consent reason for an index entry, or None.

    Shared by the registry install gate and the update gate (audits M2/M3):

    - a signature pinned to a panel-trusted publisher key → no consent needed
      (install verifies it cryptographically; a bad one hard-fails there).
    - signed by an unpinned key → 'untrusted_key'.
    - a FIRST-PARTY entry without a verifiable signature → 'unsigned':
      first-party releases are expected to be signed, so anything less is a
      possible downgrade and requires explicit consent.
    - community REVIEWED entries stay exempt: the review stamp already binds
      a maintainer's verdict to the exact sha256 of the artifact, which is
      the pre-signature trust mechanism (see docs/EXTENSIONS.md).
    """
    if entry.get('signature'):
        if entry.get('publisher_trusted'):
            return None
        return 'untrusted_key'
    if entry.get('first_party'):
        return 'unsigned'
    return None


_GATE_MESSAGES = {
    'unreviewed': (
        'This community extension has not been reviewed by the ServerKit '
        'maintainers; installing it runs unreviewed code with full panel '
        'privileges.'),
    'unverified': (
        'This extension has no pinned checksum, so the panel cannot '
        'verify the artifact it would install.'),
    # 'untrusted_key' is formatted inline (interpolates the key id).
    'unsigned': (
        'This first-party release is not signed with a publisher key '
        'pinned by this panel, so the panel cannot verify its origin. It '
        'may be a legitimate older release — or a downgrade attempt.'),
}


def consent_gate(entry, acknowledged):
    """The shared install/update consent decision (audits M2/M3).

    Returns ``(reason, message)`` — reason is None when the action may
    proceed without explicit acknowledgment. Order: unreviewed (dev-stage)
    > unverified (no checksum) > signature gate (untrusted key / unsigned
    first-party)."""
    if not entry or acknowledged:
        return None, None
    trust = entry.get('trust', 'unreviewed')
    if trust == 'unreviewed':
        reason = 'unreviewed'
    elif not entry.get('sha256'):
        reason = 'unverified'
    else:
        reason = signature_consent_reason(entry)
    if reason == 'untrusted_key':
        return reason, (
            f"This extension is signed, but its publisher key "
            f"'{entry.get('publisher_key_id')}' is not pinned by this panel, "
            f"so the signature cannot be verified. Install only if you trust "
            f"the source.")
    return reason, _GATE_MESSAGES.get(reason)
