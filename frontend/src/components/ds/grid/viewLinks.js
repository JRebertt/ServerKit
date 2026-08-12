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

// ---------------------------------------------------------------- readable
// Ad-hoc state travels as PLAIN, EDITABLE query params, not an opaque blob:
//
//   /domains?sort=sslDays:asc&hide=registrar&f=ssl:any:none,expiring&match=any
//
// You can widen a threshold or drop a rule in the address bar and hit enter.
// An encoded blob makes the URL a black box you can only regenerate from the
// UI, which is the opposite of why a link is useful.
//
// Reserved keys are `sort`, `cols`, `hide`, `groupby`, `match`, `f` (repeatable)
// — `groupby` rather than `group` because pages already own a `group` param.
// Every other key in the state is a page-owned primitive (status, search,
// filter, …) and keeps its own name.
const RESERVED = new Set(['sort', 'cols', 'hide', 'groupby', 'match', 'f', VIEW_PARAM, STATE_PARAM]);

const encodeRule = (r) => {
    const value = Array.isArray(r.value) ? r.value.join(',') : String(r.value ?? '');
    return `${r.field}:${r.op}:${value}`;
};

const decodeRule = (raw, index) => {
    // field:op:value  — split on the FIRST two colons only, so a value may
    // legitimately contain one (a timestamp, say).
    const first = raw.indexOf(':');
    const second = raw.indexOf(':', first + 1);
    if (first < 1 || second < 0) return null;
    const field = raw.slice(0, first);
    const op = raw.slice(first + 1, second);
    const rest = raw.slice(second + 1);
    const multi = op === 'any' || op === 'none';
    const numeric = op === 'lt' || op === 'gt' || op === 'eq';
    let value;
    if (multi) value = rest ? rest.split(',').filter(Boolean) : [];
    else if (numeric) value = Number(rest);
    else if (op === 'is' && (rest === 'true' || rest === 'false')) value = rest === 'true';
    else value = rest;
    if (numeric && Number.isNaN(value)) return null;
    return { id: `u${index}`, field, op, value };
};

/** State -> readable URLSearchParams. */
export function stateToParams(state = {}) {
    const params = new URLSearchParams();
    const {
        sorts, hiddenKeys, columnOrder, groupBy, columnFilters, ...rest
    } = state;

    if (sorts?.length) params.set('sort', sorts.map((s) => `${s.key}:${s.direction}`).join(','));
    if (columnOrder?.length) params.set('cols', columnOrder.join(','));
    if (hiddenKeys?.length) params.set('hide', hiddenKeys.join(','));
    if (groupBy) params.set('groupby', groupBy);
    if (columnFilters?.rules?.length) {
        if (columnFilters.match && columnFilters.match !== 'all') params.set('match', columnFilters.match);
        columnFilters.rules.forEach((r) => params.append('f', encodeRule(r)));
    }
    // Page-owned primitives keep their own names, so ?status=online reads as
    // what it is. Objects are skipped: they belong in a saved view, not a URL.
    Object.entries(rest).forEach(([key, value]) => {
        if (RESERVED.has(key) || value == null || value === '') return;
        if (typeof value === 'object') return;
        params.set(key, String(value));
    });
    return params;
}

/** Readable URLSearchParams -> state. Tolerant: junk is dropped, not fatal. */
export function paramsToState(params) {
    const state = {};
    let touched = false;

    const sort = params.get('sort');
    if (sort) {
        const sorts = sort.split(',').map((part) => {
            const [key, dir] = part.split(':');
            return key ? { key, direction: dir === 'desc' ? 'desc' : 'asc' } : null;
        }).filter(Boolean);
        if (sorts.length) { state.sorts = sorts; touched = true; }
    }
    const cols = params.get('cols');
    if (cols) { state.columnOrder = cols.split(',').filter(Boolean); touched = true; }
    const hide = params.get('hide');
    if (hide) { state.hiddenKeys = hide.split(',').filter(Boolean); touched = true; }
    if (params.has('groupby')) { state.groupBy = params.get('groupby') || null; touched = true; }

    const rules = params.getAll('f').map(decodeRule).filter(Boolean);
    if (rules.length) {
        state.columnFilters = { match: params.get('match') === 'any' ? 'any' : 'all', rules };
        touched = true;
    }

    for (const [key, value] of params.entries()) {
        if (RESERVED.has(key)) continue;
        state[key] = value;
        touched = true;
    }
    return touched ? state : null;
}

// ---------------------------------------------------------------- encoding
// Kept for links shared before the readable format existed — decode still
// accepts ?v=<base64url>, nothing generates it any more.
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

    // A saved-view handle wins: it is the more specific request, and it can be
    // combined with readable params to mean "that view, tweaked".
    const handle = params.get(VIEW_PARAM);
    if (handle) {
        const base = handle.startsWith(BUILTIN_PREFIX)
            ? { kind: 'builtin', slug: handle.slice(BUILTIN_PREFIX.length) }
            : { kind: 'saved', slug: handle };
        return { ...base, overrides: paramsToState(params) };
    }

    const readable = paramsToState(params);
    if (readable) return { kind: 'state', state: readable };

    // Legacy: links shared before the readable format existed.
    const encoded = params.get(STATE_PARAM);
    if (encoded) {
        const state = decodeState(encoded);
        if (state) return { kind: 'state', state };
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
    const params = stateToParams(state);
    const qs = params.toString();
    return qs ? `${base}?${qs}` : base;
}

/** Replace the view params on a URL without disturbing the rest of the query. */
export function withViewParam(search, handle) {
    const params = new URLSearchParams(search);
    params.delete(STATE_PARAM);
    if (handle) params.set(VIEW_PARAM, handle);
    else params.delete(VIEW_PARAM);
    return params;
}
