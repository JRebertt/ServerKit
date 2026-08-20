import assert from 'node:assert/strict';
import test, { afterEach } from 'node:test';

import {
    formatBytes,
} from '../formatBytes.js';
import {
    formatDate, formatDateTime, formatDuration, formatList, formatNumber,
    formatPercent, formatRelative, formatRelativeShort, formatTime,
    getFormatLocale, setFormatLocale,
} from '../intl.js';
import { timeAgo, formatRelativeTime } from '../time.js';

afterEach(() => setFormatLocale('en'));

test('the door starts on English', () => {
    assert.equal(getFormatLocale(), 'en');
});

test('dates follow the panel locale, not the browser', () => {
    // The bug this door exists for: `toLocaleDateString()` with no argument
    // follows the browser. These must differ by panel locale alone.
    const iso = '2026-08-19T10:00:00Z';
    const english = formatDate(iso);
    setFormatLocale('es');
    const spanish = formatDate(iso);

    assert.notEqual(english, spanish);
    assert.match(english, /Aug/);
    assert.match(spanish, /ago/);
});

test('numbers use the locale separators', () => {
    assert.equal(formatNumber(1234567.89, { decimals: 1 }), '1,234,567.9');
    setFormatLocale('es');
    assert.equal(formatNumber(1234567.89, { decimals: 1 }), '1.234.567,9');
});

test('relative time is localized by Intl, not by keys', () => {
    const threeDaysAgo = Date.now() - 3 * 86400000;
    assert.equal(formatRelative(threeDaysAgo), '3 days ago');
    setFormatLocale('es');
    assert.equal(formatRelative(threeDaysAgo), 'hace 3 días');
});

test('relative time handles the future and the present', () => {
    assert.equal(formatRelative(Date.now() + 2 * 3600000), 'in 2 hours');
    assert.match(formatRelative(Date.now()), /now|second/);
});

test('lists join the way the language joins', () => {
    assert.equal(formatList(['a', 'b', 'c']), 'a, b, and c');
    setFormatLocale('es');
    assert.equal(formatList(['a', 'b', 'c']), 'a, b y c');
});

test('percent is a percentage, not a ratio', () => {
    assert.equal(formatPercent(42), '42%');
    assert.equal(formatPercent(42.55, { decimals: 1 }), '42.6%');
});

test('durations read in seconds', () => {
    assert.equal(formatDuration(45), '45s');
    assert.equal(formatDuration(200), '3m 20s');
    assert.equal(formatDuration(180), '3m');
    assert.equal(formatDuration(7500), '2h 5m');
    assert.equal(formatDuration(7200), '2h');
});

test('unusable input yields a placeholder, never NaN or Invalid Date', () => {
    for (const bad of [null, undefined, '', 'not-a-date', NaN]) {
        assert.equal(formatDate(bad), '-', `formatDate(${String(bad)})`);
        assert.equal(formatTime(bad), '-', `formatTime(${String(bad)})`);
        assert.equal(formatDateTime(bad), '-', `formatDateTime(${String(bad)})`);
        assert.equal(formatRelative(bad), '', `formatRelative(${String(bad)})`);
    }
    for (const bad of [null, undefined, 'abc', NaN, Infinity]) {
        assert.equal(formatNumber(bad), '-', `formatNumber(${String(bad)})`);
    }
    assert.equal(formatDuration(-1), '-');
});

test('accepts ISO strings, epoch millis, and Date alike', () => {
    const iso = '2026-08-19T10:00:00Z';
    const expected = formatDate(iso);
    assert.equal(formatDate(new Date(iso)), expected);
    assert.equal(formatDate(new Date(iso).getTime()), expected);
});

test('the compact style keeps its shape, and its date tail follows the locale', () => {
    // Deliberately NOT switched to Intl's "4 minutes ago": the compact form is
    // a table style with no Intl equivalent, so its units are translation keys.
    assert.equal(formatRelativeShort(Date.now() - 10 * 1000), 'just now');
    assert.equal(formatRelativeShort(Date.now() - 4 * 60000), '4m');
    assert.equal(formatRelativeShort(Date.now() - 3 * 3600000), '3h');
    assert.equal(formatRelativeShort(Date.now() - 2 * 86400000), '2d');

    // Past a week it becomes a date -- which used to be the browser's date.
    const old = Date.now() - 60 * 86400000;
    const english = formatRelativeShort(old);
    setFormatLocale('es');
    assert.notEqual(formatRelativeShort(old), english);
});

test('time.js delegates rather than reimplementing', () => {
    assert.equal(timeAgo(Date.now() - 4 * 60000), formatRelativeShort(Date.now() - 4 * 60000));
    assert.equal(
        formatRelativeTime(Date.now() - 3 * 86400000),
        formatRelative(Date.now() - 3 * 86400000),
    );
    assert.equal(timeAgo(null), '');
    assert.equal(timeAgo('nonsense'), '');
});

test('formatBytes output is unchanged for English', () => {
    // Parity against the examples documented on the pre-migration util. The
    // trimming used to be a regex on toFixed(); it is now Intl's
    // maximumFractionDigits, which must behave the same in en.
    assert.equal(formatBytes(1536), '1.5 KB');
    assert.equal(formatBytes(0), '0 B');
    assert.equal(formatBytes(null), '-');
    assert.equal(formatBytes(1234567, { decimals: 2 }), '1.18 MB');
    assert.equal(formatBytes(2048, { iec: true }), '2 KiB');
    assert.equal(formatBytes(2048, { suffix: false }), '2');
    assert.equal(formatBytes(512), '512 B');
    assert.equal(formatBytes(1073741824), '1 GB');
    assert.equal(formatBytes(-2048), '-2 KB');
});

test('formatBytes uses the locale decimal separator', () => {
    // The old regex trim could not: a Spanish panel read "1.5 KB" while every
    // other number on the page used a comma.
    setFormatLocale('es');
    assert.equal(formatBytes(1536), '1,5 KB');
});

test('switching locale invalidates the formatter cache', () => {
    const iso = '2026-08-19T10:00:00Z';
    const first = formatDate(iso);
    setFormatLocale('es');
    const second = formatDate(iso);
    setFormatLocale('en');
    assert.equal(formatDate(iso), first);
    assert.notEqual(first, second);
});

test('parts passes Intl component options through, still per locale', () => {
    // The escape hatch that removes the reason to call toLocaleDateString
    // directly: exact control of the components, panel locale either way.
    const iso = '2026-08-19T10:00:00Z';
    const english = formatDate(iso, { parts: { month: 'short', day: 'numeric' } });
    setFormatLocale('es');
    const spanish = formatDate(iso, { parts: { month: 'short', day: 'numeric' } });

    assert.match(english, /Aug/);
    assert.match(spanish, /ago/);
    assert.notEqual(english, spanish);
    // A named style still works unchanged.
    assert.equal(formatDate(iso, { style: 'medium' }), formatDate(iso));
});
