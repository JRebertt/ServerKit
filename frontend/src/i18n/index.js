// Plan 79 A1/A2 — the i18next instance.
//
// Delivery is deliberately NOT the usual http-backend fetch:
//
//   * `en` is bundled into the main chunk. The login and setup screens render
//     before any API call succeeds, so a locale that arrives over the network
//     either flashes English first or -- when the backend is the thing that is
//     broken -- never arrives, on the one screen whose job is to say so.
//   * Every other locale is a dynamic import, which Vite emits as its own
//     chunk served from the same static origin as the app. No second fetch
//     path to 404 behind a misconfigured proxy or a subpath install, and
//     nothing to reach for in an air-gapped deployment.
//
// Adding a language is therefore data-only: drop `xx.json` into ./locales and
// add a row to languages.json. `import.meta.glob` picks it up; no loader to
// register.

import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json' with { type: 'json' };
import { DEFAULT_LANGUAGE, SUPPORTED_CODES } from './resolveLocale';

// Vite REPLACES this call at build time with a map of
// './locales/<code>.json' -> () => import(…). It must be a BARE call.
//
// A runtime guard around it — `typeof import.meta.glob === 'function' ? … : {}`
// — looks defensive and is always false in the browser: there is no such
// function, only the compile-time transform. The guard therefore threw every
// locale away and silently fell back to English for all of them. It shipped
// that way for one commit; probe-locale.mjs is what caught it.
//
// `en` is matched too and simply never loaded (it is statically imported above
// and belongs in the main chunk). Rollup notes that as INEFFECTIVE_DYNAMIC_
// IMPORT, which is the correct outcome, not a problem to silence.
const localeModules = import.meta.glob('./locales/*.json');

const loaded = new Set([DEFAULT_LANGUAGE]);

i18next
    .use(initReactI18next)
    .init({
        lng: DEFAULT_LANGUAGE,
        fallbackLng: DEFAULT_LANGUAGE,
        supportedLngs: SUPPORTED_CODES,
        load: 'languageOnly',
        resources: { [DEFAULT_LANGUAGE]: { translation: en } },
        // React escapes on render; escaping here would double-encode.
        interpolation: { escapeValue: false },
        // An empty translation must fall through to the inline English default
        // rather than render as a blank label.
        returnEmptyString: false,
        react: { useSuspense: false },
    });

// Re-exported so `@/i18n` stays a valid import for browser-only callers;
// node-reachable modules must import '@/i18n/t' directly (see that file).
export { t } from './t';

/**
 * Make a locale's bundle available, importing it on first use.
 * Resolves to the code actually loaded — `en` if the bundle is missing, so a
 * half-shipped locale degrades to English instead of to key paths.
 */
export async function loadLocale(code) {
    if (!SUPPORTED_CODES.includes(code)) return DEFAULT_LANGUAGE;
    if (loaded.has(code)) return code;

    const loader = localeModules[`./locales/${code}.json`];
    if (!loader) return DEFAULT_LANGUAGE;

    try {
        const module = await loader();
        i18next.addResourceBundle(code, 'translation', module.default || module, true, true);
        loaded.add(code);
        return code;
    } catch {
        return DEFAULT_LANGUAGE;
    }
}

/** Load then activate. Returns the code that actually took effect. */
export async function activateLocale(code) {
    const resolved = await loadLocale(code);
    if (i18next.language !== resolved) {
        await i18next.changeLanguage(resolved);
    }
    return resolved;
}

export default i18next;
