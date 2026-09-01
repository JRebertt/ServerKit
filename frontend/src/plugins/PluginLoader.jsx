/**
 * PluginLoader - Renders installed plugin widgets in the global slot.
 *
 * Two ways a plugin can show a widget:
 *
 *   1. Declarative (preferred): manifest contributions block —
 *        "contributions": { "widgets": [{ "slot": "global",
 *                                          "component": "MyWidget" }] }
 *      The host fetches contributions at runtime and resolves the
 *      `component` name against the plugin's index module exports.
 *
 *   2. Legacy auto-render: any plugin with a default export from
 *      index.js gets rendered globally with no manifest required.
 *      Kept for backward compatibility with plugins that predate
 *      the contribution model.
 *
 * Plugins that declare ANY contribution (routes, nav, tabs, widgets,
 * palette entries, layouts, walkthroughs, ai) own their rendering through the
 * contribution model and are excluded from the legacy auto-render.
 * Gating on widgets alone let bundled extensions whose index module
 * happened to have a default export (WordPress, Cloudflare zone ops)
 * mount their whole PAGE globally on every route — the page then ran
 * with no route params (zones/undefined) and the WordPress sub-router
 * swallowed the current location ("/domains" → siteId "domains"),
 * stacking several pages into one view.
 */
import { useMemo } from 'react';
import { useContributions, resolveComponent, getPluginModule } from './contributions';

const pluginModules = import.meta.glob('./*/index.{js,jsx}', { eager: true });

function getInstalledPlugins() {
    const plugins = [];
    for (const [path, mod] of Object.entries(pluginModules)) {
        const match = path.match(/^\.\/([^/]+)\/index\.(?:js|jsx)$/);
        if (!match) continue;
        const slug = match[1];
        if (slug === 'PluginLoader' || slug === 'sdk') continue;
        plugins.push({
            slug,
            Component: mod.default || null,
            Provider: mod.Provider || null,
            module: mod,
        });
    }
    return plugins;
}

const PluginLoader = ({ api }) => {
    const contributions = useContributions();
    const { widgets } = contributions;
    const legacyPlugins = useMemo(() => getInstalledPlugins(), []);

    // Any plugin that declares any contribution owns its rendering
    // through the contribution model; skip the legacy auto-render for it.
    const slugsWithDeclared = useMemo(() => {
        const set = new Set();
        const buckets = [
            contributions.routes, contributions.nav, contributions.tabs,
            contributions.widgets, contributions.command_palette,
            contributions.layouts,
            contributions.walkthroughs,
            contributions.ai?.suggested_prompts, contributions.ai?.tool_renderers,
        ];
        for (const bucket of buckets) {
            for (const item of bucket || []) {
                if (item && item.plugin) set.add(item.plugin);
            }
        }
        return set;
    }, [contributions]);

    const declaredWidgets = (widgets || [])
        .filter((w) => w && (w.slot || 'global') === 'global')
        .map((w, i) => {
            const Component = resolveComponent(w.plugin, w.component);
            if (!Component) return null;
            const mod = getPluginModule(w.plugin);
            const Provider = (mod && mod.Provider) || null;
            const node = <Component key={`${w.plugin}:${w.component}:${i}`} api={api} />;
            return Provider
                ? <Provider key={`provider:${w.plugin}:${i}`}>{node}</Provider>
                : node;
        })
        .filter(Boolean);

    const legacyWidgets = legacyPlugins
        .filter(({ slug, Component }) => Component && !slugsWithDeclared.has(slug))
        .map(({ slug, Component, Provider }) => {
            const node = <Component key={slug} api={api} />;
            return Provider
                ? <Provider key={`legacy-provider:${slug}`}>{node}</Provider>
                : node;
        });

    if (declaredWidgets.length === 0 && legacyWidgets.length === 0) return null;

    return <>{declaredWidgets}{legacyWidgets}</>;
};

export default PluginLoader;
