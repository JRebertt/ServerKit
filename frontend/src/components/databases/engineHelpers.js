// Shared helpers for the database-engine catalog / install UI.
//
// A database engine IS an app template — one carrying an `engine:` block. So
// nothing here knows the name of a single engine: no catalog, no family list,
// no version list. Everything is derived from what
// `GET /api/v1/databases/engines` returns, which is what lets a brand-new
// engine template work with zero UI changes.

import { hasBrandIcon } from '../icons/DatabaseBrands';

// Templates put their engine metadata in `engine`; an installed engine is an
// Application whose template metadata was resolved onto it the same way.
export function engineMeta(entry) {
    return entry?.engine || {};
}

// Which brand glyph, if any, we hold for this engine. The template id wins over
// the protocol so a Redis-compatible fork keeps its own identity (and falls
// through to its template icon URL) instead of wearing the Redis logo.
export function engineBrandKey(entry) {
    const id = entry?.id || entry?.template_id;
    if (hasBrandIcon(id)) return id;
    if (entry?.icon) return null;
    const protocol = engineMeta(entry).protocol;
    return hasBrandIcon(protocol) ? protocol : null;
}

// Families are whatever the catalog says they are. Sorted alphabetically
// because there is no meaningful order to impose from here.
export function familiesOf(catalog) {
    const present = new Set();
    catalog.forEach((entry) => {
        const family = engineMeta(entry).family;
        if (family) present.add(family);
    });
    return [...present].sort((a, b) => a.localeCompare(b));
}

// An installed engine is an Application, so it is keyed by `app_id`.
export function engineInstanceKey(instance) {
    return instance?.app_id ?? instance?.id ?? null;
}

// App/container status -> the tree's row status vocabulary. Deliberately
// generous: the deploy pipeline and Docker each have their own words for
// "not finished yet" and "broke".
const RUNNING = new Set(['running', 'healthy', 'active', 'up']);
const STOPPED = new Set(['stopped', 'exited', 'inactive', 'paused', 'created']);
const BUSY = new Set(['installing', 'deploying', 'building', 'pending', 'queued', 'starting', 'restarting']);
const BROKEN = new Set(['failed', 'error', 'unhealthy', 'dead']);

export function engineTreeStatus(instance) {
    const appStatus = String(instance?.status || '').toLowerCase();
    // A deploy still running, or one that failed, outranks whatever Docker
    // says — a leftover container from a previous attempt is not "running".
    if (BUSY.has(appStatus)) return 'installing';
    if (BROKEN.has(appStatus)) return 'failed';
    // Otherwise the live container is the truth; the app row is only a record.
    const container = instance?.container;
    if (container) return container.running ? 'active' : 'inactive';
    if (RUNNING.has(appStatus)) return 'active';
    if (STOPPED.has(appStatus)) return 'inactive';
    return 'available';
}

// Service/app names follow the same rule as the template deploy drawer:
// lowercase letters, digits and hyphens.
export function slugifyService(value) {
    return String(value || '')
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '')
        .replace(/-{2,}/g, '-');
}

// Database identifiers are the other convention — underscores, no hyphens.
export function slugifyIdent(value) {
    return String(value || '')
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, '_')
        .replace(/_{2,}/g, '_')
        .replace(/^_+|_+$/g, '');
}

// Admin password suggested in the install drawer. Uses the platform CSPRNG —
// Math.random() is not acceptable for something that ends up guarding a
// database port.
const PASSWORD_ALPHABET = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789@%#-';

export function generatePassword(length = 24) {
    const bytes = new Uint32Array(length);
    crypto.getRandomValues(bytes);
    let out = '';
    for (let i = 0; i < length; i += 1) {
        out += PASSWORD_ALPHABET[bytes[i] % PASSWORD_ALPHABET.length];
    }
    return out;
}

// `requirements.memory` is a template field and may be a number of MB or an
// already-formatted string ("512MB"). Render whichever we were handed.
export function formatMemory(value) {
    if (value == null || value === '') return null;
    if (typeof value === 'string') return value;
    return value >= 1024 ? `${Math.round((value / 1024) * 10) / 10} GB` : `${value} MB`;
}

// "collections" -> "collection". Good enough for the unit words an engine block
// uses (tables/collections/keys/buckets/indexes/nodes).
export function singular(unit) {
    if (!unit) return 'table';
    if (unit.endsWith('ies')) return `${unit.slice(0, -3)}y`;
    if (/(x|ch|sh|s)es$/.test(unit)) return unit.slice(0, -2);
    if (unit.endsWith('s')) return unit.slice(0, -1);
    return unit;
}

export function engineUnit(entry) {
    return engineMeta(entry).unit || 'tables';
}

// One line of "where does this thing live" — empty when we genuinely don't
// know, rather than a confident "127.0.0.1" that says nothing.
export function engineLocation(instance) {
    if (!instance) return '';
    const port = instance.port || engineMeta(instance).default_port;
    if (!port) return instance.host || '';
    return `${instance.host || '127.0.0.1'}:${port}`;
}

// Conventional variable names, matching the backend's normalized engine block
// so both ends agree on which variable means what.
const DEFAULT_PORT_VAR = 'PORT';
const DEFAULT_BIND_VAR = 'BIND_ADDRESS';
const DEFAULT_VERSION_VAR = 'IMAGE_TAG';

// The engine block names the variables that carry meaning: the admin secret,
// the initial database, the published port, the bind address, the image tag.
// Each of those gets a purpose-built control (or is set by the backend from
// `expose_public`), so none of them may also appear as a generic field —
// otherwise the same value is asked for twice and answered differently.
export function partitionVariables(entry) {
    const meta = engineMeta(entry);
    const all = entry?.variables || [];
    const byName = (varName) => (varName ? all.find((v) => v.name === varName) || null : null);

    const portVarName = meta.port_var || DEFAULT_PORT_VAR;
    const owned = new Set([
        meta.admin_password_var,
        meta.database_var,
        portVarName,
        meta.bind_var || DEFAULT_BIND_VAR,
        meta.version_var || DEFAULT_VERSION_VAR,
    ].filter(Boolean));

    return {
        passwordVar: byName(meta.admin_password_var),
        databaseVar: byName(meta.database_var),
        portVar: byName(portVarName),
        // Hidden variables still carry their default into the payload; they
        // just don't get a field.
        hidden: all.filter((v) => v.hidden && !owned.has(v.name)),
        visible: all.filter((v) => !v.hidden && !owned.has(v.name)),
    };
}

// Versions the engine offers, resolved by the backend from `engine.versions`
// or the template's own `version`.
export function engineVersions(entry) {
    const meta = engineMeta(entry);
    if (Array.isArray(meta.versions) && meta.versions.length) return meta.versions;
    return entry?.version ? [String(entry.version)] : [];
}

// Seed every variable from its declared default; a password variable with no
// default gets a generated one so the operator can copy it before install.
export function seedVariables(entry) {
    const seeded = {};
    (entry?.variables || []).forEach((v) => {
        if (v.type === 'password') {
            seeded[v.name] = v.default || generatePassword();
        } else if (v.default != null) {
            seeded[v.name] = String(v.default);
        }
    });
    return seeded;
}
