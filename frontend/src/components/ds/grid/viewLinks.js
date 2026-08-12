// Shareable links for list views.
//
// Two shapes, because "share this view" and "look at what I'm looking at" are
// different requests:
//
//   /domains?view=ssl-expiring     a SAVED view, by slug. Short, memorable,
//                                  and always reflects the view's current
//                                  definition — edit the view, the link follows.
//
//   /domains?v=<encoded>           whatever is on screen RIGHT NOW, including
//                                  unsaved tweaks. Self-contained: it needs no
//                                  server lookup and no permission on anyone
//                                  else's saved views, so it works for a
//                                  colleague who has never opened the page.
//
// `copyableLink()` picks: a clean saved view gets the slug, anything dirty or
// unsaved gets the encoded state. Built-in views use `builtin:<slug>` so they
// resolve without a database row.

export const VIEW_PARAM = 'view';
export const STATE_PARAM = 'v';
export const BUILTIN_PREFIX = 'builtin:';

export const slugify = (value) => (
    (value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 140)
);

// ---------------------------------------------------------------- encoding
// base64url over JSON. Not encryption and not meant to be opaque — just a
// URL-safe envelope, so a link survives being pasted into chat clients that
// mangle raw braces and quotes.
export function encodeState(state) {
    try {
        const json = JSON.stringify(state);
        const bytes = new TextEncoder().encode(json);
        let binary = '';
        bytes.forEach((b) => { binary += String.fromCharCode(b); });
        return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    } catch {
        return null;
    }
}

export function decodeState(encoded) {
    if (!encoded) return null;
    try {
        const b64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
        const binary = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
        const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
        const parsed = JSON.parse(new TextDecoder().decode(bytes));
        // A link is untrusted input: only take an object, never an array or a
        // primitive that would then be spread into page state.
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch {
        return null;
    }
}

// ---------------------------------------------------------------- reading
/** What a URL is asking for: {kind:'saved'|'builtin'|'state'|null, …}. */
export function readViewParams(search) {
    const params = new URLSearchParams(search);
    const encoded = params.get(STATE_PARAM);
    if (encoded) {
        const state = decodeState(encoded);
        if (state) return { kind: 'state', state };
    }
    const handle = params.get(VIEW_PARAM);
    if (handle) {
        return handle.startsWith(BUILTIN_PREFIX)
            ? { kind: 'builtin', slug: handle.slice(BUILTIN_PREFIX.length) }
            : { kind: 'saved', slug: handle };
    }
    return { kind: null };
}

/** Find the view a URL handle refers to, across built-ins and saved views. */
export function resolveView({ kind, slug }, { builtinViews = [], userViews = [] }) {
    if (kind === 'builtin') return builtinViews.find((v) => slugify(v.name) === slug) || null;
    if (kind === 'saved') {
        return userViews.find((v) => v.slug === slug)
            // Fall back to the name so a link still works for a view saved
            // before slugs existed, or one the server has not backfilled.
            || userViews.find((v) => slugify(v.name) === slug)
            || builtinViews.find((v) => slugify(v.name) === slug)
            || null;
    }
    return null;
}

// ---------------------------------------------------------------- writing
export function handleFor(view) {
    if (!view) return null;
    return view.builtin ? `${BUILTIN_PREFIX}${slugify(view.name)}` : (view.slug || slugify(view.name));
}

/**
 * The link to put on the clipboard.
 *
 * A saved view that has NOT been modified is worth sharing by handle. The
 * moment it is dirty — or there is no active view at all — the handle would
 * send the recipient somewhere different from what the sender is looking at,
 * so the state travels instead.
 */
export function copyableLink({ pathname, view, isDirty, state, origin }) {
    const base = `${origin ?? window.location.origin}${pathname}`;
    const handle = !isDirty && handleFor(view);
    if (handle) return `${base}?${VIEW_PARAM}=${encodeURIComponent(handle)}`;
    const encoded = encodeState(state);
    return encoded ? `${base}?${STATE_PARAM}=${encoded}` : base;
}

/** Replace the view params on a URL without disturbing the rest of the query. */
export function withViewParam(search, handle) {
    const params = new URLSearchParams(search);
    params.delete(STATE_PARAM);
    if (handle) params.set(VIEW_PARAM, handle);
    else params.delete(VIEW_PARAM);
    return params;
}
