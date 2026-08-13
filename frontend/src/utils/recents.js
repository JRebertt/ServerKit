// Recently visited entities + pinned favorites, kept in localStorage so the
// command palette (and later the sidebar) can surface them. Client-only —
// same stance as paletteFrecency: cross-device sync is out of scope.
//
// An entry is { type, id, path, label, at } — e.g.
//   { type: 'service', id: 12, path: '/services/12', label: 'shop-api', at: 1733… }

const RECENTS_KEY = 'serverkit:recents';
const FAVORITES_KEY = 'serverkit:favorites';
const MAX_RECENTS = 10;

function load(key) {
    try {
        const raw = localStorage.getItem(key);
        const parsed = raw ? JSON.parse(raw) : null;
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function save(key, entries) {
    try {
        localStorage.setItem(key, JSON.stringify(entries));
    } catch {
        /* storage full / disabled — a nicety, never fatal */
    }
}

const sameEntry = (a, b) => a.type === b.type && String(a.id) === String(b.id);

/** Record a detail-page visit. Most recent first, deduped by type+id. */
export function recordVisit({ type, id, path, label }) {
    if (!type || id == null || !path) return;
    const entry = { type, id, path, label: label || String(id), at: Date.now() };
    const rest = load(RECENTS_KEY).filter((e) => !sameEntry(e, entry));
    save(RECENTS_KEY, [entry, ...rest].slice(0, MAX_RECENTS));
    // Keep the label fresh if this entity is a favorite.
    const favorites = load(FAVORITES_KEY);
    if (favorites.some((e) => sameEntry(e, entry))) {
        save(FAVORITES_KEY, favorites.map((e) => (sameEntry(e, entry) ? { ...e, label: entry.label, path } : e)));
    }
}

export function getRecents(limit = MAX_RECENTS) {
    return load(RECENTS_KEY).slice(0, limit);
}

export function getFavorites() {
    return load(FAVORITES_KEY);
}

export function isFavorite(type, id) {
    return load(FAVORITES_KEY).some((e) => e.type === type && String(e.id) === String(id));
}

/** Toggle a favorite; returns the new state (true = now a favorite). */
export function toggleFavorite({ type, id, path, label }) {
    const entry = { type, id, path, label: label || String(id), at: Date.now() };
    const favorites = load(FAVORITES_KEY);
    const exists = favorites.some((e) => sameEntry(e, entry));
    save(FAVORITES_KEY, exists
        ? favorites.filter((e) => !sameEntry(e, entry))
        : [entry, ...favorites]);
    return !exists;
}
