"""Remote theme registry (plan 60, Phase 3).

Mirrors the extension registry_service pattern, minus the trust machinery: a
theme is data, not code, so there are no zips, no sha256, no permissions — the
registry is a curated ``index.json`` (in the ``serverkit-themes`` repo, submitted
via PR, published on merge) and installing is fetching + validating + storing a
color map.

Design rules (same as the extension registry):
  - Read-only discovery. Nothing here auto-installs; installs are explicit.
  - Offline-tolerant. A failed fetch falls back to the last good cache, then to
    the bundled index (``app/data/themes_index.json``) — the gallery never blanks.
  - Configurable. ``SERVERKIT_THEMES_REGISTRY_URL`` points at the live index.
    Unset ⇒ the public registry; set-but-EMPTY ⇒ disabled (bundled only — also
    how the test suite stays offline).
"""
import json
import logging
import os
from urllib.parse import urljoin

import requests

from app.utils.remote_index import CachedRemoteIndex

from app.exceptions import (
    DependencyUnavailableError,
    NotFoundError,
    ValidationError,
)
from app.models.theme import Theme
from app.services import theme_service

logger = logging.getLogger(__name__)

_BUNDLED_INDEX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'themes_index.json'
)

# The curated public index. Default goes through serverkit.ai, which proxies the
# raw-GitHub index (operator-gated route). Operators can also point
# SERVERKIT_THEMES_REGISTRY_URL straight at the raw index:
#   https://raw.githubusercontent.com/jhd3197/serverkit-themes/main/index.json
DEFAULT_REGISTRY_URL = 'https://serverkit.ai/themes/index.json'

_FIELDS = {
    'slug': '',
    'name': '',
    'author': '',
    'version': '1.0.0',
    'description': '',
    'base': 'dark',
    'accent': None,
    'preview': [],
    'modes': [],
    'theme': '',   # relative path to the full theme.json
    'image': None,
}




def _resolve_url(path, base_url):
    if not path or not isinstance(path, str):
        return path
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return urljoin(base_url, path) if base_url else path


def _normalize(raw, base_url=None):
    if not isinstance(raw, dict) or not raw.get('slug'):
        return None
    out = {k: raw.get(k, d) for k, d in _FIELDS.items()}
    if not isinstance(out['preview'], list):
        out['preview'] = []
    if not isinstance(out['modes'], list):
        out['modes'] = []
    out['image'] = _resolve_url(out['image'], base_url)
    # Keep the resolved absolute URL to the full theme.json for install.
    out['_theme_url'] = _resolve_url(out['theme'], base_url)
    return out


def _read_index_payload(payload, base_url=None):
    themes = payload.get('themes') if isinstance(payload, dict) else None
    if not isinstance(themes, list):
        return []
    return [t for t in (_normalize(x, base_url) for x in themes) if t]


# One remote-catalog engine (plan 77 F1); this module stays a thin
# normalizer. The failure-retry semantics this service pioneered
# (last-good served under full TTL, bundled held only error_ttl) now live
# in CachedRemoteIndex for every catalog.
_index = CachedRemoteIndex(
    name='Themes',
    env_var='SERVERKIT_THEMES_REGISTRY_URL',
    default_url=DEFAULT_REGISTRY_URL,
    normalize_fn=_read_index_payload,
    bundled_path=_BUNDLED_INDEX,
    bundled_base_url=None,
    ttl=3600,
    ttl_env_var='SERVERKIT_THEMES_REGISTRY_TTL',
    error_ttl=60,
)

# Test seams: the shared cache dict + the failure-retry window name the
# theme tests already use.
_cache = _index._cache
_FAILURE_TTL = _index.error_ttl
_TTL = _index.ttl


def refresh(force=False):
    """Return registry entries, refreshing when the cache is stale. Never
    raises — falls back to last-good cache, then the bundled index."""
    return _index.get(force=force)


def _installed_slugs():
    return {row.slug for row in Theme.query.with_entities(Theme.slug).all()}


def list_catalog():
    """Registry entries + live install state, for the Browse gallery. Bundled
    seed slugs are dropped — those already show as always-present gallery cards,
    so a registry entry for them would duplicate."""
    installed = _installed_slugs()
    bundled = {t['slug'] for t in theme_service.list_bundled()}
    out = []
    for e in refresh():
        if e['slug'] in bundled:
            continue
        d = {k: e[k] for k in _FIELDS if k != 'theme'}
        d['installed'] = e['slug'] in installed
        out.append(d)
    return out


def get_entry(slug):
    for e in refresh():
        if e['slug'] == slug:
            return e
    return None


def registry_source_label():
    return _cache.get('source')


def install(slug):
    """Fetch a registry theme's full theme.json, validate it, and store it.
    Returns the theme dict; raises typed application errors."""
    entry = get_entry(slug)
    if entry is None:
        raise NotFoundError('Theme not found in the registry')
    theme_url = entry.get('_theme_url')
    if not theme_url:
        raise ValidationError('Registry entry has no theme file')
    try:
        resp = requests.get(theme_url, timeout=15, headers={
            'Accept': 'application/json',
            'User-Agent': 'ServerKit-Themes/1.0',
        })
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        logger.warning('Fetching theme %s failed (%s): %s', slug, theme_url, e)
        raise DependencyUnavailableError(
            'Could not download the theme from the registry') from e
    # The registry index and the theme file must agree on the slug.
    if isinstance(raw, dict) and raw.get('slug') and raw['slug'] != slug:
        raise ValidationError('Registry theme slug mismatch')
    theme, err = theme_service.import_theme(raw, source='registry')
    if err:
        raise ValidationError(err)
    return theme
