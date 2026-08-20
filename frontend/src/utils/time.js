// Relative-time and duration helpers.
//
// Plan 79 §C: the implementations moved to `utils/intl.js`, which is the one
// locale-aware formatting door. These names stay because ten files import
// them and the two output shapes are deliberate — but they are now thin
// delegations, not a second implementation. Notably the date tail of both
// styles used to be `toLocaleDateString()` with no argument, which follows the
// BROWSER's locale rather than the panel's.
//
//   - timeAgo(iso)           compact: "just now", "4m", "3h", "2d", else a date
//   - formatRelativeTime     verbose, now fully localized by Intl:
//                            "4 minutes ago", "hace 4 minutos"
//   - formatDuration(secs)   "45s", "3m 20s"

import { formatRelative, formatRelativeShort, formatDuration as formatDurationIntl } from './intl.js';

export function timeAgo(iso) {
    return formatRelativeShort(iso);
}

export function formatRelativeTime(iso) {
    return formatRelative(iso);
}

export function formatDuration(seconds) {
    return formatDurationIntl(seconds);
}

export default timeAgo;
