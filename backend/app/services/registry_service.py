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


def _registry_url():
    """Resolve the live index URL per request (env changes apply without a
    restart). Unset ⇒ the public registry; set-but-empty ⇒ disabled."""
    value = os.environ.get('SERVERKIT_REGISTRY_URL')
    if value is None:
        return DEFAULT_REGISTRY_URL
    return value.strip()
try:
    _TTL = int(os.environ.get('SERVERKIT_REGISTRY_TTL', '3600'))
except ValueError:
    _TTL = 3600

# Module-level cache: last successfully-parsed entry list + when we fetched it.
_cache = {'ts': 0.0, 'entries': None, 'source': None}

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


def _load_bundled():
    try:
        with open(_BUNDLED_INDEX, 'r', encoding='utf-8') as f:
            # Bundled copy mirrors the public index; resolve its relative logos
            # against the default (raw-GitHub) index base.
            return _read_index_payload(json.load(f), base_url=DEFAULT_REGISTRY_URL)
    except Exception as e:
        logger.warning(f'Could not read bundled registry index: {e}')
        return []


def _fetch_remote():
    url = _registry_url()
    if not url:
        return None
    resp = requests.get(url, timeout=15, headers={
        'Accept': 'application/json',
        'User-Agent': 'ServerKit-Registry/1.0',
    })
    resp.raise_for_status()
    return _read_index_payload(resp.json(), base_url=url)


def refresh(force=False):
    """Return the registry entries, refreshing from the remote index when the
    cache is stale. Never raises — falls back to cache, then bundled copy."""
    now = time.time()
    if not force and _cache['entries'] is not None and (now - _cache['ts']) < _TTL:
        return _cache['entries']

    entries = None
    source = None
    try:
        entries = _fetch_remote()
        if entries is not None:
            source = 'remote'
    except Exception as e:
        logger.warning(f'Registry fetch failed ({_registry_url()}): {e}')

    if entries is None:
        # Keep the last good remote cache if we have one; else bundled.
        if _cache['entries'] is not None:
            return _cache['entries']
        entries = _load_bundled()
        source = 'bundled'

    _cache['entries'] = entries
    _cache['ts'] = now
    _cache['source'] = source
    return entries


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
