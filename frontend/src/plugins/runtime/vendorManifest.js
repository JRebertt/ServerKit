/**
 * The single list of modules a runtime-loaded extension resolves through the
 * host (plan 25 Decision 2; plan 79 §SDK).
 *
 * Three things used to restate this list independently — the import map in
 * vite.config.js, the namespace capture in vendorShare.js, and one
 * hand-written shim per module under public/serverkit-vendor/. They drifted,
 * exactly as three copies of anything do:
 *
 *   * `react.mjs` and `react-router-dom.mjs` were in the import map but had no
 *     shim at all, so an extension importing bare `react` 404'd at load;
 *   * the `serverkit-sdk` shim re-exported 26 of the SDK's 71 exports, so an
 *     extension importing `Button`, `Modal`, `EmptyState` or `formatBytes`
 *     from the SDK got `undefined` and crashed.
 *
 * Now this file is the list, the shims are generated from it
 * (`npm run vendor:shims`), and `--check` fails the build on drift.
 *
 * `exportsFrom` says where the generator learns a module's export names:
 *   'module' — import the real package and read its namespace keys;
 *   'sdk'    — parse the SDK entry's own export statements.
 * Either way the names are derived, never typed out here.
 */
export const VENDOR_MODULES = [
    { specifier: 'react', file: 'react.mjs', exportsFrom: 'module' },
    { specifier: 'react-dom', file: 'react-dom.mjs', exportsFrom: 'module' },
    { specifier: 'react-dom/client', file: 'react-dom-client.mjs', exportsFrom: 'module' },
    { specifier: 'react/jsx-runtime', file: 'react-jsx-runtime.mjs', exportsFrom: 'module' },
    { specifier: 'react-router-dom', file: 'react-router-dom.mjs', exportsFrom: 'module' },
    // i18next and react-i18next are shared for the same reason React is: an
    // extension bundling its own copy would get a SEPARATE, uninitialised
    // i18next, so every `t()` in that extension would silently render its
    // English default forever — the failure mode plan 79 hit twice in core.
    { specifier: 'i18next', file: 'i18next.mjs', exportsFrom: 'module' },
    { specifier: 'react-i18next', file: 'react-i18next.mjs', exportsFrom: 'module' },
    { specifier: 'serverkit-sdk', file: 'serverkit-sdk.mjs', exportsFrom: 'sdk' },
];

/** `{ specifier: '/serverkit-vendor/<file>' }` — the browser import map. */
export const VENDOR_IMPORTMAP = {
    imports: Object.fromEntries(
        VENDOR_MODULES.map(({ specifier, file }) => [specifier, `/serverkit-vendor/${file}`]),
    ),
};

export default VENDOR_MODULES;
