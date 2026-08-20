// Canonical byte/size formatter for the whole frontend.
//
// Replaces the ~14 local `formatBytes` / `formatSize` / `formatMemory`
// implementations that had drifted apart. The codebase universally treats
// sizes as binary (divide by 1024) with conventional KB/MB/GB labels, so that
// is the default here — displayed values stay identical after migration.
//
//   formatBytes(1536)                       -> "1.5 KB"
//   formatBytes(0)                          -> "0 B"
//   formatBytes(null)                        -> "-"
//   formatBytes(1234567, { decimals: 2 })   -> "1.18 MB"
//   formatBytes(2048, { iec: true })        -> "2 KiB"
//   formatBytes(2048, { suffix: false })    -> "2"

import { formatNumber } from './intl.js';

const DECIMAL_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB'];
const IEC_UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB'];

export function formatBytes(bytes, options = {}) {
    const {
        decimals = 1,
        suffix = true,
        iec = false, // true -> KiB/MiB/GiB labels (divisor is always 1024)
        defaultValue = '-',
    } = options;

    if (bytes === null || bytes === undefined || bytes === '') return defaultValue;

    const value = typeof bytes === 'string' ? Number(bytes) : bytes;
    if (!Number.isFinite(value)) return defaultValue;
    if (value === 0) return suffix ? '0 B' : '0';

    const units = iec ? IEC_UNITS : DECIMAL_UNITS;

    const negative = value < 0;
    const abs = Math.abs(value);

    const exponent = Math.min(
        Math.floor(Math.log(abs) / Math.log(1024)),
        units.length - 1
    );
    const scaled = abs / 1024 ** exponent;

    // Whole-byte values never need decimals.
    const places = exponent === 0 ? 0 : decimals;

    // Plan 79 §C: through the format door rather than toFixed + a regex trim.
    // `maximumFractionDigits` drops trailing zeros for free ("1.0" -> "1",
    // "1.50" -> "1.5") AND uses the locale's decimal separator, which the
    // string-trim could not: a Spanish panel showed "1.5 KB" where every other
    // number on the page read "1,5".
    const formatted = formatNumber(scaled, { maximumFractionDigits: places });

    const sign = negative ? '-' : '';
    return suffix ? `${sign}${formatted} ${units[exponent]}` : `${sign}${formatted}`;
}

export default formatBytes;
