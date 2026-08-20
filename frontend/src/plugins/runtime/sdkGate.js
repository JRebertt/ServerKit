/**
 * Load-time SDK gate decision (plan 32 Decision 1) — the pure half of the
 * runtime loader's version check, split out so it's unit-testable under plain
 * node (the loader itself touches `import.meta.env` and `crypto`).
 *
 * A runtime frontend declares an `sdk_version` semver range it was built
 * against. The panel reports its own SDK version. Before fetching any bytes the
 * loader decides:
 *
 *   'load'   — range covers the panel's SDK (or the panel didn't report one).
 *   'grace'  — the extension pins no range: warn-and-load for one release,
 *              matching the fail-open in install-time's
 *              `plugin_service._assert_manifest_sdk_compatible`.
 *   'refuse' — the range excludes the panel's SDK; fail closed with an explain
 *              string on the failure card instead of a cryptic import error.
 */
// Explicit `.js` so this module also imports cleanly under plain node for the
// unit test (Vite resolves either form).
import { satisfiesRange } from '../../utils/semverRange.js';

export function sdkGateDecision(range, panelSdkVersion) {
    if (!range || !String(range).trim()) return 'grace';
    if (!panelSdkVersion) return 'load'; // panel didn't report its SDK ⇒ no opinion
    return satisfiesRange(range, panelSdkVersion) ? 'load' : 'refuse';
}

export function sdkRefusalMessage(range, panelSdkVersion) {
    return `needs SDK ${range}, panel has ${panelSdkVersion} — update the extension`;
}
