/**
 * Runtime extension frontend loader (plan 25 Phase 2, Decision 1).
 *
 * For an installed extension that ships a prebuilt ESM bundle, the panel:
 *   1. fetches the bundle through the JWT-authed assets route (raw bytes),
 *   2. verifies its sha256 against the hash recorded at install time
 *      (served in the /plugins/contributions `frontends` map),
 *   3. imports it via a Blob URL — resolving its externalized bare specifiers
 *      (react, react-dom, react/jsx-runtime, react-router-dom, serverkit-sdk)
 *      through the host import map to the panel's OWN singleton instances.
 *
 * Auth + integrity in one move, mirroring install-time pinning: on-disk tampering
 * after install is caught at every load. Fail soft, loudly (Decision 5): a bundle
 * that fails hash check or import records an error state and renders a failure card
 * on its routes — never a white screen, never silent absence.
 *
 * Baked builtins + dev keep the build-time glob path (Decision 4); this loader is
 * a no-op in dev (no import map there; dev resolves bare specifiers itself).
 */
import api from '../../services/api';
import { sdkGateDecision, sdkRefusalMessage } from './sdkGate';
import { digestBytes } from './digest';

// Only run in a production build — dev has no injected import map and uses the
// build-time glob path (Decision 4). Guarding here keeps a dev panel that talks
// to a real backend from trying to blob-import a bundle whose `react` import
// can't resolve.
const RUNTIME_ENABLED = import.meta.env.PROD;

// Slug → imported module namespace (named exports resolved like the glob path).
const runtimeModuleBySlug = {};

// Slug → { status: 'ok' | 'error', error?: string }. Drives the failure card.
const runtimeLoadState = {};

// Slugs we've already attempted this session (by entry+hash signature) so a
// re-fetch of contributions doesn't re-download/re-import an unchanged bundle.
const loadedSignature = {};

export function getRuntimeModule(slug) {
    return runtimeModuleBySlug[slug] || null;
}

export function getRuntimeLoadState(slug) {
    if (slug) return runtimeLoadState[slug] || null;
    return runtimeLoadState;
}

// Thrown when a bundle is refused BEFORE any bytes are fetched because its
// declared SDK range doesn't cover the panel's SDK version (plan 32 Decision 1).
// Carried as a distinct load state ('refused') so the Marketplace can tell an
// SDK mismatch apart from an integrity/fetch failure.
class SdkRefusedError extends Error {}

// Is this slug delivered as a runtime bundle (i.e. present in the contributions
// `frontends` map)? Used by ExtensionRoutes to decide whether an unresolved
// component means "broken runtime extension" (show a card) vs "unknown" (skip).
export function isRuntimeFrontend(frontends, slug) {
    return Boolean(frontends && frontends[slug]);
}

// Load-time SDK gate (plan 32 Decision 1). Refuse a bundle whose declared
// `sdk_version` range doesn't cover the panel's SDK version, BEFORE fetching any
// bytes — the failure card then explains the version gap instead of a cryptic
// import error. A missing/blank range is a one-release grace: warn (dev) and
// load, matching the same fail-open in install-time's
// `plugin_service._assert_manifest_sdk_compatible`.
function assertSdkCompatible(slug, descriptor, panelSdkVersion) {
    const range = descriptor && descriptor.sdk_version;
    const decision = sdkGateDecision(range, panelSdkVersion);
    if (decision === 'grace' && import.meta.env.DEV) {
        console.warn(
            `[plugins] runtime frontend "${slug}" declares no sdk_version — `
            + 'loading anyway (one-release grace).');
    }
    if (decision === 'refuse') {
        throw new SdkRefusedError(sdkRefusalMessage(range, panelSdkVersion));
    }
}

async function importOne(slug, descriptor) {
    const entry = descriptor && descriptor.entry;
    const hashes = (descriptor && descriptor.hashes) || {};
    const expected = hashes[entry];
    if (!entry) throw new Error('no frontend entry declared');
    if (!expected) throw new Error(`no recorded hash for ${entry} — reinstall the extension`);

    const bytes = await api.getPluginAssetBytes(slug, entry);
    // Digest via the seam: native crypto.subtle in a secure context, a bundled
    // pure-JS sha256 on an HTTP-only panel — identical result either way.
    const actual = await digestBytes(bytes);
    if (actual !== String(expected).toLowerCase()) {
        throw new Error(
            `integrity check failed for ${entry} (expected ${String(expected).slice(0, 12)}…, `
            + `got ${actual.slice(0, 12)}…) — the on-disk bundle was modified`);
    }

    const url = URL.createObjectURL(new Blob([bytes], { type: 'text/javascript' }));
    try {
        // Blob module: bare specifiers resolve through the document import map.
        const mod = await import(/* @vite-ignore */ url);
        return mod;
    } finally {
        URL.revokeObjectURL(url);
    }
}

/**
 * Load every runtime frontend in the contributions `frontends` map. Resolves
 * once all attempts settle (never rejects — each failure is isolated). Call it
 * before notifying contribution subscribers so routes render with modules ready.
 */
export async function loadRuntimeFrontends(frontends, panelSdkVersion) {
    if (!RUNTIME_ENABLED || !frontends || typeof frontends !== 'object') return;

    const slugs = Object.keys(frontends);
    await Promise.all(slugs.map(async (slug) => {
        const descriptor = frontends[slug];
        // Signature = entry + its hash + panel SDK. Unchanged ⇒ already settled,
        // skip. Include the panel SDK so a panel upgrade re-runs the gate.
        const sig = `${descriptor?.entry}@${descriptor?.hashes?.[descriptor?.entry] || ''}`
            + `~${panelSdkVersion || ''}`;
        if (loadedSignature[slug] === sig && runtimeLoadState[slug]?.status === 'ok') return;

        try {
            assertSdkCompatible(slug, descriptor, panelSdkVersion);
            const mod = await importOne(slug, descriptor);
            runtimeModuleBySlug[slug] = mod;
            runtimeLoadState[slug] = { status: 'ok' };
            loadedSignature[slug] = sig;
        } catch (e) {
            delete runtimeModuleBySlug[slug];
            // 'refused' = SDK gate (Decision 1); 'error' = integrity/fetch/import.
            const status = e instanceof SdkRefusedError ? 'refused' : 'error';
            runtimeLoadState[slug] = { status, error: e?.message || String(e) };
            loadedSignature[slug] = sig;
            // Loud: surfaced on the Marketplace + a failure card on its routes.
            console.error(`[plugins] runtime frontend "${slug}" ${status}:`, e);
        }
    }));
}
