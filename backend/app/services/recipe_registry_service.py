"""Remote Recipe registry.

Mirrors the theme_registry_service pattern (a recipe is data, not code — no
zips, no sha256, no permissions): the registry is a curated ``index.json`` in
the ``serverkit-recipes`` repo, submitted via PR, published on merge. Each
entry points at an executable ``serverkit.yaml`` manifest that
``RecipeExecutionService`` runs as a normal deployment job.

Design rules (same as the other registries):
  - Read-only discovery. Nothing here auto-installs; runs are explicit.
  - Offline-tolerant. A failed fetch falls back to the last good cache, then to
    the bundled index (``app/data/recipes_index.json``) — the catalog never
    blanks.
  - Configurable. ``SERVERKIT_RECIPES_REGISTRY_URL`` points at the live index.
    Unset ⇒ the public registry; set-but-EMPTY ⇒ disabled (bundled only — also
    how the test suite stays offline).
"""
import logging
import os
from urllib.parse import urljoin

import requests

from app.utils.remote_index import CachedRemoteIndex

from app.exceptions import (
    DependencyUnavailableError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

_BUNDLED_INDEX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'recipes_index.json'
)

# The curated public index. Default goes through serverkit.ai, which proxies
# the raw-GitHub index and rewrites each entry's manifest path to an absolute
# /recipes/file URL. Operators can also point SERVERKIT_RECIPES_REGISTRY_URL
# straight at the raw index:
#   https://raw.githubusercontent.com/jhd3197/serverkit-recipes/main/index.json
DEFAULT_REGISTRY_URL = 'https://serverkit.ai/recipes/index.json'

_FIELDS = {
    'slug': '',
    'name': '',
    'version': '1.0.0',
    'category': '',
    'icon': '',
    'description': '',
    'author': '',
    'minutes': None,
    'featured': False,
    'requirements': {},
    'capabilities': [],
    'inputs': [],
    'handoffs': [],
    'steps': 0,
    'manifest': '',   # relative path to the executable recipe.yaml
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
    out = {k: raw.get(k, d) if raw.get(k, d) is not None else d for k, d in _FIELDS.items()}
    for list_field in ('capabilities', 'inputs', 'handoffs'):
        if not isinstance(out[list_field], list):
            out[list_field] = []
    if not isinstance(out['requirements'], dict):
        out['requirements'] = {}
    # Keep the resolved absolute URL to the executable manifest for runs.
    out['_manifest_url'] = _resolve_url(out['manifest'], base_url)
    return out


def _read_index_payload(payload, base_url=None):
    recipes = payload.get('recipes') if isinstance(payload, dict) else None
    if not isinstance(recipes, list):
        return []
    return [r for r in (_normalize(x, base_url) for x in recipes) if r]


_index = CachedRemoteIndex(
    name='Recipes',
    env_var='SERVERKIT_RECIPES_REGISTRY_URL',
    default_url=DEFAULT_REGISTRY_URL,
    normalize_fn=_read_index_payload,
    bundled_path=_BUNDLED_INDEX,
    bundled_base_url='https://raw.githubusercontent.com/jhd3197/serverkit-recipes/main/',
    ttl=3600,
    ttl_env_var='SERVERKIT_RECIPES_REGISTRY_TTL',
    error_ttl=60,
)

# Test seams, matching the convention the other registry services use.
_cache = _index._cache


def refresh(force=False):
    """Return registry entries, refreshing when the cache is stale. Never
    raises — falls back to last-good cache, then the bundled index."""
    return _index.get(force=force)


def list_catalog():
    """Registry entries for the catalog grid (display fields only)."""
    return [{k: e[k] for k in _FIELDS} for e in refresh()]


def get_entry(slug):
    for e in refresh():
        if e['slug'] == slug:
            return e
    return None


def registry_source_label():
    return _cache.get('source')


def get_manifest_text(slug):
    """Fetch a registry recipe's full serverkit.yaml text. Raises typed
    application errors; normalization happens at the call site so parse errors
    surface where the run is started."""
    entry = get_entry(slug)
    if entry is None:
        raise NotFoundError('Recipe not found in the registry')
    manifest_url = entry.get('_manifest_url')
    if not manifest_url:
        raise NotFoundError('Registry entry has no manifest file')
    try:
        resp = requests.get(manifest_url, timeout=15, headers={
            'Accept': 'text/plain',
            'User-Agent': 'ServerKit-Recipes/1.0',
        })
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning('Fetching recipe %s failed (%s): %s', slug, manifest_url, e)
        raise DependencyUnavailableError(
            'Could not download the recipe from the registry') from e
