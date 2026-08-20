// Plan 79 §C — the one locale-aware formatting door.
//
// Before this, five util files formatted things for humans and none of them
// took a locale, while 93 files called `toLocaleDateString()` with no
// argument. That follows the BROWSER's locale, not the panel's, so a panel set
// to Spanish already rendered English chrome around Spanish dates — a bug that
// predates any translation work.
//
// Three properties this door has that the scattered calls did not:
//
//   1. A module-level `currentLocale`, published by LocaleContext rather than
//      read from a hook. The API error mapper, the log formatter and the CSV
//      exporter all format for humans outside React; a hook cannot serve them,
//      and a second source of locale is a second locale.
//   2. `useFormat()` for components, so they re-render on a locale switch.
//      Same implementation underneath — the hook is a subscription, not a
//      second door.
//   3. Formatter instances cached per (locale, kind, options). Tables format
//      thousands of cells and `Intl.DateTimeFormat` construction is the
//      expensive part; the `toLocaleDateString()` calls this replaces built a
//      fresh formatter per cell per render.

import i18next from 'i18next';

let currentLocale = 'en';
const formatters = new Map();

/**
 * Point the door at a locale. Called by LocaleContext BEFORE it re-renders,
 * so non-React callers never format against the previous locale.
 */
export function setFormatLocale(locale) {
    if (!locale || locale === currentLocale) return;
    currentLocale = locale;
    formatters.clear();   // cached instances are locale-bound
}

export function getFormatLocale() {
    return currentLocale;
}

function cached(kind, options, build) {
    const key = `${currentLocale}|${kind}|${JSON.stringify(options)}`;
    let instance = formatters.get(key);
    if (!instance) {
        instance = build(currentLocale, options);
        formatters.set(key, instance);
    }
    return instance;
}

/**
 * Translate with an inline English default, tolerating an uninitialised
 * i18next (node tooling, tests, a crash before the provider mounts).
 */
function translate(key, fallback, values) {
    if (i18next.isInitialized) {
        return i18next.t(key, { defaultValue: fallback, ...values });
    }
    return String(fallback).replace(/\{\{(\w+)\}\}/g, (_, name) => (
        values && name in values ? values[name] : `{{${name}}}`
    ));
}

/** Accepts an ISO string, epoch millis, or a Date. Returns null when unusable. */
function toDate(value) {
    if (value === null || value === undefined || value === '') return null;
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function toNumber(value) {
    // `Number(null)`, `Number('')` and `Number([])` are all 0, so a plain
    // coercion renders a missing metric as a real zero -- which reads as data.
    if (value === null || value === undefined || value === '') return null;
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    const number = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(number) ? number : null;
}

// ---------------------------------------------------------------- dates ---

const DATE_STYLES = { short: 'short', medium: 'medium', long: 'long', full: 'full' };

export function formatDate(value, { style = 'medium', fallback = '-' } = {}) {
    const date = toDate(value);
    if (!date) return fallback;
    return cached('date', { style }, (locale, options) => new Intl.DateTimeFormat(locale, {
        dateStyle: DATE_STYLES[options.style] || 'medium',
    })).format(date);
}

export function formatTime(value, { seconds = false, fallback = '-' } = {}) {
    const date = toDate(value);
    if (!date) return fallback;
    return cached('time', { seconds }, (locale, options) => new Intl.DateTimeFormat(locale, {
        timeStyle: options.seconds ? 'medium' : 'short',
    })).format(date);
}

export function formatDateTime(value, { style = 'medium', seconds = false, fallback = '-' } = {}) {
    const date = toDate(value);
    if (!date) return fallback;
    return cached('datetime', { style, seconds }, (locale, options) => new Intl.DateTimeFormat(locale, {
        dateStyle: DATE_STYLES[options.style] || 'medium',
        timeStyle: options.seconds ? 'medium' : 'short',
    })).format(date);
}

// ------------------------------------------------------------- relative ---

const RELATIVE_UNITS = [
    ['year', 31536000],
    ['month', 2592000],
    ['week', 604800],
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
    ['second', 1],
];

/**
 * Locale-correct relative time — "3 days ago", "hace 3 días".
 *
 * Uses Intl.RelativeTimeFormat rather than translation keys on purpose: the
 * browser already knows every language's plural rules and wording for this,
 * and hand-keying "{{count}} days ago" would need a per-language plural table
 * that Intl maintains for free.
 */
export function formatRelative(value, { style = 'long', numeric = 'auto', fallback = '' } = {}) {
    const date = toDate(value);
    if (!date) return fallback;

    const deltaSeconds = (date.getTime() - Date.now()) / 1000;
    const absolute = Math.abs(deltaSeconds);

    const [unit, size] = RELATIVE_UNITS.find(([, seconds]) => absolute >= seconds)
        || ['second', 1];
    const amount = Math.round(deltaSeconds / size);

    return cached('relative', { style, numeric }, (locale, options) => (
        new Intl.RelativeTimeFormat(locale, options)
    )).format(amount, unit);
}

/**
 * The panel's compact relative style — "just now", "4m", "3h", "2d", then a
 * date. Intl has no compact-without-"ago" form, so the units come from
 * translation keys; the date tail goes through formatDate and so follows the
 * panel locale rather than the browser's.
 */
export function formatRelativeShort(value, { fallback = '' } = {}) {
    const date = toDate(value);
    if (!date) return fallback;

    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    if (seconds < 45) return translate('common.time.justNow', 'just now');

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return translate('common.time.minutesShort', '{{count}}m', { count: minutes });

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return translate('common.time.hoursShort', '{{count}}h', { count: hours });

    const days = Math.floor(hours / 24);
    if (days < 7) return translate('common.time.daysShort', '{{count}}d', { count: days });

    return formatDate(date, { style: 'short' });
}

/** Duration in SECONDS — "45s", "3m 20s", "2h 5m". */
export function formatDuration(seconds, { fallback = '-' } = {}) {
    const total = toNumber(seconds);
    if (total === null || total < 0) return fallback;

    if (total < 60) {
        return translate('common.duration.seconds', '{{count}}s', { count: Math.round(total) });
    }
    const minutes = Math.floor(total / 60);
    if (minutes < 60) {
        const rest = Math.round(total % 60);
        return rest
            ? translate('common.duration.minutesSeconds', '{{minutes}}m {{seconds}}s',
                { minutes, seconds: rest })
            : translate('common.duration.minutes', '{{count}}m', { count: minutes });
    }
    const hours = Math.floor(minutes / 60);
    const restMinutes = minutes % 60;
    return restMinutes
        ? translate('common.duration.hoursMinutes', '{{hours}}h {{minutes}}m',
            { hours, minutes: restMinutes })
        : translate('common.duration.hours', '{{count}}h', { count: hours });
}

// -------------------------------------------------------------- numbers ---

/**
 * `decimals` pins both bounds (a fixed 2dp money-style read);
 * `maximumFractionDigits` only caps them, so trailing zeros drop — which is
 * what size and metric readouts want.
 */
export function formatNumber(value, { decimals, maximumFractionDigits, fallback = '-' } = {}) {
    const number = toNumber(value);
    if (number === null) return fallback;
    return cached('number', { decimals, maximumFractionDigits }, (locale, options) => (
        new Intl.NumberFormat(locale, {
            ...(options.decimals === undefined ? {} : {
                minimumFractionDigits: options.decimals,
                maximumFractionDigits: options.decimals,
            }),
            ...(options.maximumFractionDigits === undefined ? {} : {
                maximumFractionDigits: options.maximumFractionDigits,
            }),
        })
    )).format(number);
}

/** Space-tight form for KPI tiles — 107814 -> "107.8K" (and its locale's form). */
export function formatCompactNumber(value, { fallback = '-' } = {}) {
    const number = toNumber(value);
    if (number === null) return fallback;
    return cached('compact', {}, (locale) => new Intl.NumberFormat(locale, {
        notation: 'compact',
        maximumFractionDigits: 1,
    })).format(number);
}

/** `value` is the percentage itself (42 -> "42%"), not a 0..1 ratio. */
export function formatPercent(value, { decimals = 0, fallback = '-' } = {}) {
    const number = toNumber(value);
    if (number === null) return fallback;
    return cached('percent', { decimals }, (locale, options) => new Intl.NumberFormat(locale, {
        style: 'percent',
        minimumFractionDigits: options.decimals,
        maximumFractionDigits: options.decimals,
    })).format(number / 100);
}

/** "a, b and c" — join wording differs by language. */
export function formatList(items, { type = 'conjunction' } = {}) {
    const list = (items || []).filter((item) => item !== null && item !== undefined).map(String);
    if (!list.length) return '';
    if (typeof Intl.ListFormat !== 'function') return list.join(', ');
    return cached('list', { type }, (locale, options) => new Intl.ListFormat(locale, {
        style: 'long',
        type: options.type,
    })).format(list);
}

export default {
    formatDate,
    formatTime,
    formatDateTime,
    formatRelative,
    formatRelativeShort,
    formatDuration,
    formatNumber,
    formatCompactNumber,
    formatPercent,
    formatList,
};
