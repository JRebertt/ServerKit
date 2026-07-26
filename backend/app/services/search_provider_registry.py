"""Registry of searchable entity types contributed outside the core.

``SearchService.search`` fans a term out across a hardcoded sequence of core
entity blocks — fine while everything searchable lived in core, but it meant an
extension's objects were absent from the one place users are told to look. A
registered provider is fanned out alongside the core types, and the command
palette already renders unknown types (they bucket under "Results" with the
generic icon), so contributing rows takes no frontend work.

A provider is ``fn(query) -> [row, ...]`` where *query* is a :class:`SearchQuery`
and each row is ``{'label', 'path'}`` plus an optional ``'sublabel'``. The
service normalises what comes back through :func:`clean_rows`, which is also the
security seam: a provider cannot exceed the per-type cap, cannot claim to be a
core type, and cannot return a path that navigates off-site.

**Scoping is the provider's job.** Core applies no post-filter — every core
block scopes its own query (``WorkspaceService.scope_query``, an owner column,
an admin gate) and a provider must do the same with the ``user`` and
``workspace_id`` on the query it is handed. Search invents no ACL; it must not
become the place one leaks.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# entity type -> provider(query) -> rows
_PROVIDERS = {}

# The core entity types, reserved so a plugin cannot impersonate one — rows
# tagged 'service' or 'vault' are trusted to have been scoped by core.
CORE_TYPES = ('service', 'server', 'domain', 'database', 'site', 'cron',
              'extension', 'vault')


@dataclass(frozen=True)
class SearchQuery:
    """What a provider is asked for, and who is asking.

    Passed as one object rather than keyword arguments so later additions
    (result kinds, an explicit tier) don't break every installed provider's
    signature.
    """

    term: str
    user: Any = None
    workspace_id: Optional[int] = None
    limit: int = 5


def register(entity_type: str, provider, replace: bool = False):
    """Register *provider* for *entity_type*.

    Namespace the type after your plugin (``wordpress.site``); the bare words
    in ``CORE_TYPES`` belong to core.
    """
    if not entity_type or not callable(provider):
        raise ValueError('search provider requires an entity type and a callable')
    if entity_type in CORE_TYPES:
        raise ValueError(f'"{entity_type}" is a core search type and cannot be overridden')
    if entity_type in _PROVIDERS and not replace:
        raise ValueError(f'search provider for "{entity_type}" is already registered')
    _PROVIDERS[entity_type] = provider
    logger.info('Registered search provider: %s', entity_type)
    return provider


def get(entity_type: str):
    """Return the provider for *entity_type*, or None."""
    return _PROVIDERS.get(entity_type)


def types():
    """All registered non-core entity types."""
    return sorted(_PROVIDERS)


def providers():
    """``(entity_type, provider)`` pairs, in a stable order."""
    return [(t, _PROVIDERS[t]) for t in sorted(_PROVIDERS)]


def clean_rows(entity_type: str, rows, limit: int):
    """Normalise a provider's rows into the shape the palette renders.

    Enforced here rather than trusted from the provider:

    * the per-type cap, so one contributed type can't drown the core ones even
      if it ignored ``query.limit``;
    * ``type``, which is always the registered one — a plugin cannot dress its
      rows up as a core entity;
    * ``path``, which must be an in-app router path. It is handed to
      ``navigate()`` unmodified, so a protocol-relative ``//host`` value would
      send the user off the panel entirely.

    Malformed rows are dropped individually — a provider with one bad row still
    contributes its good ones.
    """
    cleaned = []
    for row in (rows or []):
        if len(cleaned) >= limit:
            break
        if not isinstance(row, dict):
            continue
        label = str(row.get('label') or '').strip()
        path = str(row.get('path') or '').strip()
        if not label or not path:
            continue
        if not path.startswith('/') or path.startswith('//'):
            logger.warning('search: %s dropped a row with off-site path %r',
                           entity_type, path)
            continue
        cleaned.append({
            'type': entity_type,
            'label': label,
            'sublabel': str(row.get('sublabel') or ''),
            'path': path,
        })
    return cleaned


def clear():
    """Drop every registration. Tests only."""
    _PROVIDERS.clear()
