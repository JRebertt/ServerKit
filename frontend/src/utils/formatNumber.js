// Number formatting helpers for KPI tiles and count badges.
//
// `formatCompact` renders large counts in a space-tight notation (107814 ->
// "107.8K") so a 6-digit total never bursts a narrow tile; `formatFull` is the
// grouped exact form (107814 -> "107,814") used as the hover title so the
// precise count stays one hover away. Non-finite / non-numeric input is
// returned unchanged, letting callers pass placeholders like an em dash
// straight through.
//
// Plan 79 §C: both used to build `new Intl.NumberFormat('en')` at module load
// -- a hardcoded locale AND a formatter that could never follow a switch.
// They now delegate to the format door.

import { formatCompactNumber, formatNumber } from './intl.js';

export function formatCompact(value) {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return value;
    return formatCompactNumber(n);
}

export function formatFull(value) {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return value;
    return formatNumber(n);
}

export default formatCompact;
