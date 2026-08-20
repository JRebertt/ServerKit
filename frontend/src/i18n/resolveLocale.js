// Plan 79 A4 — locale precedence, as pure functions so it can be tested
// without a browser, a store, or i18next.
//
//   user.language (server, per-user)
//     -> localStorage 'language'   (pre-auth cache; stops the login flash)
//       -> panel default           (system_settings, unauthenticated endpoint)
//         -> navigator.language    (first visit, matched language-only)
//           -> 'en'
//
// This mirrors ThemeContext's precedence (workspace -> user -> skin ->
// default) deliberately: same problem shape, same solution, one thing to
// learn.

// Import attribute required by Node (the test runner); Vite/rollup honour it too.
import manifest from './languages.json' with { type: 'json' };

export const LANGUAGES = manifest.languages;
export const DEFAULT_LANGUAGE = 'en';
export const SUPPORTED_CODES = LANGUAGES.map((language) => language.code);
export const STORAGE_KEY = 'language';

/**
 * Match a requested tag against what we ship, language-only.
 *
 * `es-419`, `es-MX` and `ES` all resolve to `es`. Region-specific bundles are
 * not shipped, so keeping the region would mean a miss on every non-neutral
 * browser tag — which is most of them.
 */
export function matchSupported(tag, supported = SUPPORTED_CODES) {
    if (!tag || typeof tag !== 'string') return null;
    const normalized = tag.trim().toLowerCase().replace('_', '-');
    if (!normalized) return null;
    if (supported.includes(normalized)) return normalized;
    const base = normalized.split('-')[0];
    return supported.includes(base) ? base : null;
}

/**
 * First supported match across an ordered list of candidate tags.
 * Unsupported and malformed entries are skipped rather than failing — a
 * user row carrying a locale we no longer ship must not break the app.
 */
export function resolveLocale({
    userLanguage = null,
    stored = null,
    panelDefault = null,
    navigatorLanguages = [],
    supported = SUPPORTED_CODES,
} = {}) {
    const candidates = [userLanguage, stored, panelDefault, ...navigatorLanguages];
    for (const candidate of candidates) {
        const match = matchSupported(candidate, supported);
        if (match) return match;
    }
    return DEFAULT_LANGUAGE;
}

/** The manifest row for a code, or the English row. */
export function languageInfo(code) {
    return LANGUAGES.find((language) => language.code === code)
        || LANGUAGES.find((language) => language.code === DEFAULT_LANGUAGE);
}

/** Writing direction for a code — drives <html dir> (plan 79 §H). */
export function directionFor(code) {
    return languageInfo(code).dir || 'ltr';
}

/** Browser languages, defensively — `navigator` is absent under node. */
export function navigatorLanguages() {
    if (typeof navigator === 'undefined') return [];
    if (Array.isArray(navigator.languages) && navigator.languages.length) {
        return [...navigator.languages];
    }
    return navigator.language ? [navigator.language] : [];
}
