// ONE frontend status → tone vocabulary (plan 77 D3).
//
// Every page used to roll its own status→color map, so "running" rendered
// cyan on some pages and green or amber on others. This module is the single
// door: ONE table maps the union of backend statuses (see
// backend/app/models/status.py) to a ds Pill kind, and a kind→variant map
// derives the ui Badge variant from the same table, so both primitives agree.
//
//   Pill  kind:    green | amber | red | cyan | violet | gray
//   Badge variant: success | warning | destructive | info | secondary | outline
//
// Do NOT add per-page status maps — extend STATUS_KIND (or one of the scoped
// override tables below) instead. A ratchet test
// (src/components/ds/__tests__/statusOneDoor.test.mjs) fails the suite when a
// new local map appears outside this file.

// The one table. Keys are lowercased statuses; values are Pill kinds.
const STATUS_KIND = {
    // green — healthy / succeeded / terminal-good
    success: 'green',
    succeeded: 'green',
    completed: 'green',
    done: 'green',
    passed: 'green',
    pass: 'green',
    ok: 'green',
    online: 'green',
    healthy: 'green',
    up: 'green',
    published: 'green',
    up_to_date: 'green',
    active: 'green',
    live: 'green',
    connected: 'green',
    protected: 'green',
    resolved: 'green',
    sleeping: 'green', // process S state is the normal resting state

    // red — failed / terminal-bad
    failed: 'red',
    failure: 'red',
    error: 'red',
    fail: 'red',
    dead: 'red',
    dead_letter: 'red',
    destroyed: 'red',
    offline: 'red',
    disconnected: 'red',
    critical: 'red',
    high: 'red',
    major: 'red',
    unhealthy: 'red',
    down: 'red',
    investigating: 'red',
    zombie: 'red',

    // cyan — in flight / making progress
    running: 'cyan',
    in_progress: 'cyan',
    in_flight: 'cyan',
    deploying: 'cyan',
    building: 'cyan',
    analyzing: 'cyan',
    verifying: 'cyan',
    restarting: 'cyan',
    activating: 'cyan',
    reloading: 'cyan',
    connecting: 'cyan',
    starting: 'cyan',
    checking: 'cyan',
    monitoring: 'cyan',
    host: 'cyan', // fleet proxy "host default" plane
    info: 'cyan',

    // amber — warn-ish / needs attention
    warn: 'amber',
    warning: 'amber',
    degraded: 'amber',
    medium: 'amber',
    minor: 'amber',
    update_available: 'amber',
    rolled_back: 'amber',
    timeout: 'amber',
    skipped_no_space: 'amber',
    cancelled: 'amber',
    canceled: 'amber',
    identified: 'amber',
    acknowledged: 'amber',
    idle: 'amber',
    'disk-sleep': 'amber',

    // gray — neutral / not started / switched off
    pending: 'gray',
    queued: 'gray',
    scheduled: 'gray',
    created: 'gray',
    paused: 'gray',
    stopped: 'gray',
    inactive: 'gray',
    skipped: 'gray',
    unknown: 'gray',
    low: 'gray',
    none: 'gray',
    debug: 'gray',
    off: 'gray',

    // violet — analyzed-but-not-applied and other "special" states
    analyzed: 'violet',
};

// Pill kind → ui Badge variant. The ONE bridge between the two primitives.
const KIND_VARIANT = {
    green: 'success',
    red: 'destructive',
    cyan: 'info',
    amber: 'warning',
    violet: 'secondary',
    gray: 'outline',
};

// Pill kind → StatusBadge dot color class (kept here so the dot always agrees
// with the kind the same status resolves to).
const KIND_DOT = {
    green: 'bg-green-400',
    red: 'bg-red-400',
    amber: 'bg-yellow-400',
    cyan: 'bg-blue-400',
    violet: 'bg-muted-foreground/60',
    gray: 'bg-muted-foreground/60',
};

// Labels pages already customize; everything else is humanized (underscores →
// spaces, Title Case).
const LABEL_OVERRIDES = {
    host: 'Host default',
    skipped_no_space: 'Skipped (no space)',
};

function normalize(status) {
    return String(status ?? '').toLowerCase().trim();
}

/** Status → ds Pill kind. Unknown statuses read gray. */
export function statusKind(status) {
    return STATUS_KIND[normalize(status)] || 'gray';
}

/** Status → ui Badge variant, driven by the same table as statusKind(). */
export function statusVariant(status) {
    return KIND_VARIANT[statusKind(status)];
}

/** Status → StatusBadge dot color class, derived from the kind. */
export function statusDotClass(status) {
    return KIND_DOT[statusKind(status)];
}

/** Humanized label: underscores/hyphens → spaces, Title Case, with overrides. */
export function statusLabel(status) {
    const key = normalize(status);
    if (!key) return 'Unknown';
    if (LABEL_OVERRIDES[key]) return LABEL_OVERRIDES[key];
    return key
        .split(/[\s_-]+/)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

// ---------------------------------------------------------------------------
// Scoped overrides. A handful of domains reuse a word the main table already
// owns with a different meaning ("active" is healthy for a service but firing
// for an alert; a "running"/"stopped" PROCESS is normal/killed, not in-flight/
// neutral). They live HERE, not in the pages, so the vocabulary stays one file.
// ---------------------------------------------------------------------------

// Fleet alert lifecycle: an ACTIVE alert is the bad state.
const ALERT_STATUS_OVERRIDES = { active: 'red' };

/** Alert lifecycle status → Pill kind (active→red, acknowledged→amber, resolved→green). */
export function alertStatusKind(status) {
    return ALERT_STATUS_OVERRIDES[normalize(status)] || statusKind(status);
}

// OS process states: running/sleeping are the healthy norm, stopped/zombie are
// the broken ones. sleeping/idle/disk-sleep/zombie live in the main table.
const PROCESS_STATE_OVERRIDES = { running: 'green', stopped: 'red' };

/** OS process state → ui Badge variant (running→success, stopped/zombie→destructive). */
export function processStateVariant(state) {
    const kind = PROCESS_STATE_OVERRIDES[normalize(state)] || statusKind(state);
    return KIND_VARIANT[kind];
}

// Env-var change actions are verbs, not lifecycle states: "created" is an
// addition (green), unlike a freshly-created run (gray).
const ENV_ACTION_KIND = { created: 'green', updated: 'amber', deleted: 'red' };

/** Env-var history action → Pill kind (created→green, updated→amber, deleted→red). */
export function envActionKind(action) {
    return ENV_ACTION_KIND[normalize(action)] || statusKind(action);
}

// Long-running services/units/previews: "running" IS the healthy steady
// state (green), unlike a run-shaped job where running is an in-flight
// phase (cyan). Same reasoning as processStateVariant above.
const SERVICE_STATUS_OVERRIDES = { running: 'green' };

/** Service/unit/preview status → Pill kind (running→green, else the shared table). */
export function serviceStatusKind(status) {
    return SERVICE_STATUS_OVERRIDES[normalize(status)] || statusKind(status);
}

/** Service/unit status → ui Badge variant, from the same scoped table. */
export function serviceStatusVariant(status) {
    return KIND_VARIANT[SERVICE_STATUS_OVERRIDES[normalize(status)] || statusKind(status)];
}

/** Service/unit status → StatusBadge dot color class, same scoped table. */
export function serviceStatusDotClass(status) {
    return KIND_DOT[SERVICE_STATUS_OVERRIDES[normalize(status)] || statusKind(status)];
}
