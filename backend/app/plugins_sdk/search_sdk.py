"""Plugin-facing SDK for global search.

    from app.plugins_sdk import search

    def find_worlds(query):
        rows = World.query.filter(World.owner_id == query.user.id,
                                  World.name.ilike(f'%{query.term}%'))
        return [{'label': w.name, 'sublabel': 'Minecraft world',
                 'path': f'/minecraft/worlds/{w.id}'} for w in rows]

    search.register('minecraft.world', find_worlds)

Registering makes a plugin's objects reachable from the command palette with no
frontend work: an unrecognised type renders under "Results" with the generic
icon rather than being dropped.

Your provider is handed a ``search.Query`` — ``term``, ``user``, ``workspace_id``
and ``limit`` — and **must scope its own rows to that user and workspace**. The
panel applies no post-filter; every core block scopes itself, and search exists
to surface what someone can already reach, never to widen it.
"""

from app.services import search_provider_registry
from app.services.search_provider_registry import SearchQuery


class SearchSdk:
    """Stable search surface for plugins."""

    #: The object a provider receives. Exposed so plugins can build one in
    #: their own tests without importing a host service path.
    Query = SearchQuery

    def register(self, entity_type, provider, replace=False):
        """Register ``provider(query) -> [{'label', 'path', 'sublabel'}, ...]``.

        Namespace the type after your plugin (``minecraft.world``); bare names
        are reserved for core entities. Rows are capped and normalised by the
        host, and are always tagged with the type you registered.
        """
        return search_provider_registry.register(entity_type, provider, replace=replace)

    def types(self):
        """Entity types registered by plugins."""
        return search_provider_registry.types()


search = SearchSdk()
