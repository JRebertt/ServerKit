"""
Contribution Service - Aggregate active-plugin contributions for the UI.

A plugin manifest may declare a `contributions` block with any subset of:

    {
      "nav":            [{ id, label, route, category, icon, ... }],
      "routes":         [{ path, component, layout?, group? }],
      "page_titles":    { "/some-path": "Title" },
      "command_palette":[{ label, path, category, keywords }],
      "widgets":        [{ slot, component }],
      "dashboard_widgets": [{ id, name, component, icon?, category?,
                              description?, w?, h?, min?, default_cfg? }],
      "layouts":        [{ id, component }],
      "tabs":           [{ group, to, label, icon?, end?, order? }],
      "walkthroughs":   [{ id, title, description, steps, ... }]
    }

`widgets` and `dashboard_widgets` are different surfaces and are easy to
confuse. A `widgets` entry mounts a component at a FIXED host slot
(`<PluginSlot name="dashboard.top" />`) — the host decides where it goes and
the user cannot move it. A `dashboard_widgets` entry registers a placeable
widget TYPE: it appears in the dashboard's widget library, and the user adds,
positions, resizes and configures instances of it on a dashboard board. Use
`widgets` to enrich an existing page, `dashboard_widgets` to offer a new
building block.

A `tabs` entry adds a tab to a core-owned TabGroupLayout group; `group` is the
core group id (== the sidebar item id: files | servers | monitoring). Pair it
with a route contribution carrying the same `group` so the page renders INSIDE
that group's TabGroupLayout (shared PageTopbar chrome) instead of as a flat
dashboard route.

The `layout` field on a route may be one of:

    "padded" (default) — render inside DashboardLayout, normal padding
    "full"             — render inside DashboardLayout, no padding
                         (matches /workflow, /files, /docker shape)
    "bare"             — render OUTSIDE DashboardLayout (no sidebar)
                         under PrivateRoute, fullscreen authenticated
    "<custom-id>"      — wrap in a plugin-contributed layout component
                         declared via contributions.layouts

Each entry is tagged with the source plugin's slug so the frontend knows
which plugin a contribution came from (for error attribution + matching
the `component` string against modules discovered by import.meta.glob).

Only plugins with status == 'active' contribute. A plugin without a
contributions block is silently skipped.
"""
from app.models.plugin import InstalledPlugin
from app.utils.sdk import SDK_VERSION


# Panel-managed plugin-config key holding the per-bundle sha256 hashes recorded
# for a runtime-frontend extension at install time (see plugin_service).
RUNTIME_FRONTEND_HASH_KEY = '_frontend_hashes'


def _runtime_frontends(plugins):
    """Descriptor map for extensions delivered as a prebuilt ESM bundle.

    Shape: ``{ slug: { entry, hashes: {entry: sha256}, sdk_version } }``. The
    client runtime loader (frontend/src/plugins/runtime/loader.js) fetches each
    bundle through the JWT-authed assets route, verifies its sha256 against the
    hash recorded here at install time, then blob-imports it — resolving the
    externalized react/router/sdk specifiers through the host import map.

    Only extensions whose manifest ``frontend_entry`` is an ESM bundle (``.mjs``)
    appear here; baked ``.jsx`` builtins render via the build-time glob, not the
    runtime loader. Gated by the ``extensions.runtime_frontend`` kill switch
    (Decision 4) — off means an empty map and the loader is inert.
    """
    from app.services.settings_service import SettingsService
    if not SettingsService.get('extensions.runtime_frontend', True):
        return {}

    out = {}
    for p in plugins:
        manifest = p.manifest or {}
        entry = (manifest.get('frontend_entry') or '').strip()
        if not entry.endswith('.mjs'):
            continue
        hashes = (p.config or {}).get(RUNTIME_FRONTEND_HASH_KEY) or {}
        out[p.slug] = {
            'entry': entry,
            'hashes': hashes,
            'sdk_version': manifest.get('sdk_version') or '',
        }
    return out


def _tag(items, slug):
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item['plugin'] = slug
        out.append(item)
    return out


def get_active_contributions():
    plugins = InstalledPlugin.query.filter_by(
        status=InstalledPlugin.STATUS_ACTIVE,
    ).all()

    nav = []
    routes = []
    page_titles = {}
    command_palette = []
    widgets = []
    dashboard_widgets = []
    layouts = []
    tabs = []
    walkthroughs = []
    # AI assistant contributions: per-route suggested prompts + custom
    # tool-result renderers, consumed by the core AIAssistant.
    ai = {'suggested_prompts': [], 'tool_renderers': []}

    for p in plugins:
        contrib = (p.manifest or {}).get('contributions') or {}
        if not isinstance(contrib, dict):
            continue

        nav.extend(_tag(contrib.get('nav'), p.slug))
        routes.extend(_tag(contrib.get('routes'), p.slug))
        command_palette.extend(_tag(contrib.get('command_palette'), p.slug))
        widgets.extend(_tag(contrib.get('widgets'), p.slug))
        dashboard_widgets.extend(_tag(contrib.get('dashboard_widgets'), p.slug))
        layouts.extend(_tag(contrib.get('layouts'), p.slug))
        tabs.extend(_tag(contrib.get('tabs'), p.slug))
        walkthroughs.extend(_tag(contrib.get('walkthroughs'), p.slug))

        ai_contrib = contrib.get('ai')
        if isinstance(ai_contrib, dict):
            ai['suggested_prompts'].extend(_tag(ai_contrib.get('suggested_prompts'), p.slug))
            ai['tool_renderers'].extend(_tag(ai_contrib.get('tool_renderers'), p.slug))

        titles = contrib.get('page_titles')
        if isinstance(titles, dict):
            for path, title in titles.items():
                if isinstance(path, str) and isinstance(title, str):
                    page_titles[path] = title

    return {
        'nav': nav,
        'routes': routes,
        'page_titles': page_titles,
        'command_palette': command_palette,
        'widgets': widgets,
        'dashboard_widgets': dashboard_widgets,
        'layouts': layouts,
        'tabs': tabs,
        'walkthroughs': walkthroughs,
        'ai': ai,
        # Panel SDK version the client uses to gate runtime bundles (plan 25 #1).
        'sdk_version': SDK_VERSION,
        # Runtime-loadable ESM frontends (plan 25 Phase 2, core-slim #39).
        'frontends': _runtime_frontends(plugins),
    }
