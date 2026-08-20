import i18next from 'i18next';

/**
 * Translate outside React — class components (ErrorBoundary), module-level
 * helpers, the API client's error mapper.
 *
 * A bare export rather than reaching for `i18next.t` at the call site: the
 * extractor collects bare `t(...)` calls, so a member call would leave that
 * copy out of en.json and quietly untranslatable.
 *
 * Deliberately separate from ./index.js, which owns initialisation and the
 * `import.meta.glob` locale map. That glob is a Vite compile-time transform
 * and throws under plain node, so anything reachable from a node test — the
 * API client is — must not pull it in. Importing the i18next singleton here
 * costs nothing and keeps that path clean.
 *
 * Before i18next is initialised (node tooling, a crash before the provider
 * mounts) i18next returns the supplied defaultValue, so callers still get
 * their English.
 */
export const t = (...args) => i18next.t(...args);

export default t;
