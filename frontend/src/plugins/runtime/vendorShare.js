/**
 * Host vendor sharing for runtime-loaded extension bundles (plan 25 Decision 2).
 *
 * A runtime extension bundle externalizes the shared libraries (react,
 * react-dom, react/jsx-runtime, react-router-dom, i18next, react-i18next,
 * serverkit-sdk — the list lives in ./vendorManifest.js) and
 * resolves them at load time through a static import map injected into
 * index.html (see vite.config.js `serverkitImportmap`). Each mapped URL points
 * at a small shim under `/serverkit-vendor/*.mjs` that re-exports from THIS
 * global — so the extension and the host share ONE instance of React et al.
 * (two React copies ⇒ "Invalid hook call" crash).
 *
 * Capturing the namespaces here (rather than letting the shim import the
 * package) is what guarantees the single instance: the host already bundled
 * these once; the shim just hands the extension the host's own objects.
 *
 * Imported first in main.jsx so the global is populated long before any
 * extension bundle is fetched (extensions load post-boot, after contributions).
 */
import * as React from 'react';
import * as ReactDOM from 'react-dom';
import * as ReactDOMClient from 'react-dom/client';
import * as JsxRuntime from 'react/jsx-runtime';
import * as ReactRouterDom from 'react-router-dom';
import * as I18next from 'i18next';
import * as ReactI18next from 'react-i18next';
import * as ServerkitSdk from 'serverkit-sdk';

const vendor = {
    'react': React,
    'react-dom': ReactDOM,
    'react-dom/client': ReactDOMClient,
    'react/jsx-runtime': JsxRuntime,
    'react-router-dom': ReactRouterDom,
    // Shared for the same reason React is: a second i18next instance would be
    // uninitialised, so every t() in that extension would render its English
    // default forever and nothing would report it.
    'i18next': I18next,
    'react-i18next': ReactI18next,
    'serverkit-sdk': ServerkitSdk,
};

// Stable, documented handle. The `/serverkit-vendor/*.mjs` shims read this.
globalThis.__SK_VENDOR__ = vendor;

export default vendor;
