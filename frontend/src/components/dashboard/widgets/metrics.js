/**
 * Metric catalog for the dashboard widget grid (plan 62).
 *
 * Every entry here is backed by a REAL field on a real payload — there is no
 * synthetic data anywhere in the widget stack. Two history payloads exist and
 * they are shaped differently, so each metric carries the candidate paths for
 * both:
 *
 *   local host   GET /api/v1/metrics/history?period=…
 *                → MetricsHistory.to_dict()  (backend/app/models/metrics_history.py)
 *                  { timestamp, level, cpu:{percent,min,max},
 *                    memory:{percent,used_bytes,total_bytes,…},
 *                    disk:{percent,used_bytes,total_bytes,…},
 *                    load:{'1m','5m','15m'}, sample_count }
 *                  NOTE: no network fields at all.
 *
 *   remote agent GET /api/v1/servers/<id>/metrics/history?period=…
 *                → ServerMetrics.to_dict()   (backend/app/models/server.py)
 *                  { timestamp, cpu_percent, memory_percent, memory_used,
 *                    disk_percent, disk_used, network_rx, network_tx,
 *                    network_rx_rate, network_tx_rate, container_count,
 *                    container_running, extra }
 *                  NOTE: no load average.
 *
 * The live socket/poll payload (GET /api/v1/system/metrics, and the same shape
 * for /servers/<id>/system/metrics) nests differently again — `live` holds its
 * path. Network there is a cumulative byte counter, not a rate, so it cannot
 * stand in for net_in/net_out and is deliberately left null.
 */

// The agent reports network rates in bytes/sec; the catalog presents MB/s.
const BYTES_PER_MB = 1024 * 1024;

export const METRICS = [
    {
        id: 'cpu',
        label: 'CPU usage',
        unit: '%',
        color: 'var(--accent-bright)',
        max: 100,
        field: 'cpu.percent',
        paths: ['cpu.percent', 'cpu_percent'],
        live: 'cpu.percent',
        sources: ['local', 'server'],
    },
    {
        id: 'ram',
        label: 'Memory usage',
        unit: '%',
        color: 'var(--green)',
        max: 100,
        field: 'memory.percent',
        paths: ['memory.percent', 'memory_percent'],
        live: 'memory.percent',
        sources: ['local', 'server'],
    },
    {
        id: 'disk',
        label: 'Disk usage',
        unit: '%',
        color: 'var(--amber)',
        max: 100,
        field: 'disk.percent',
        paths: ['disk.percent', 'disk_percent'],
        live: 'disk.percent',
        sources: ['local', 'server'],
    },
    {
        id: 'net_in',
        label: 'Network in',
        unit: 'MB/s',
        color: 'var(--cyan)',
        max: null,
        // ServerMetrics.network_rx_rate (bytes/sec) is a real, populated column
        // — but ONLY on the agent-server history. The local-host history table
        // has no network columns at all, so this metric is server-scoped and is
        // never offered for `local`. See metricsForSource().
        field: 'network_rx_rate',
        paths: ['network_rx_rate'],
        scale: 1 / BYTES_PER_MB,
        live: null,
        sources: ['server'],
    },
    {
        id: 'net_out',
        label: 'Network out',
        unit: 'MB/s',
        color: 'var(--violet)',
        max: null,
        field: 'network_tx_rate',
        paths: ['network_tx_rate'],
        scale: 1 / BYTES_PER_MB,
        live: null,
        sources: ['server'],
    },
    {
        id: 'load',
        label: 'Load average',
        unit: '',
        color: 'var(--accent-bright)',
        max: null,
        // MetricsHistory column load_1m is serialised as load['1m'].
        // ServerMetrics has no load column, so this is local-host only.
        field: 'load.1m',
        paths: ['load.1m'],
        live: 'load_average.1min',
        sources: ['local'],
    },
];

export const AGGREGATIONS = [
    ['last', 'Last'],
    ['avg', 'Average'],
    ['max', 'Max'],
    ['p95', 'p95'],
    ['min', 'Min'],
];

export const RANGES = [
    ['1h', '1h'],
    ['6h', '6h'],
    ['24h', '24h'],
    ['7d', '7d'],
    ['30d', '30d'],
];

export const RANGE_IDS = RANGES.map(([id]) => id);

/** Look a metric up by id. Falls back to the first entry so callers never
 *  have to null-check a stale saved config. */
export function getMetric(id) {
    return METRICS.find((m) => m.id === id) || METRICS[0];
}

/** Which history source a resource id maps to: 'local' or 'server'. */
export function sourceOf(resource) {
    return !resource || resource === 'local' ? 'local' : 'server';
}

/** True when this metric actually has a backing column on that source. */
export function metricSupports(metric, source) {
    if (!metric) return false;
    return (metric.sources || []).includes(source);
}

/**
 * The metrics a given resource can actually answer for. Config UIs MUST build
 * their metric dropdown from this, not from METRICS — that is what keeps a dead
 * option (network on the local host, load average on an agent server) from ever
 * reaching a user.
 *
 *   metricsForSource('local')  -> cpu, ram, disk, load
 *   metricsForSource('server') -> cpu, ram, disk, net_in, net_out
 */
export function metricsForSource(source) {
    const key = source === 'server' ? 'server' : 'local';
    return METRICS.filter((m) => metricSupports(m, key));
}

/** Same, but resolving a resource id rather than a source name. */
export function metricsForResource(resource) {
    return metricsForSource(sourceOf(resource));
}

/** Read a dotted path off a plain object without throwing on gaps. */
export function readAt(obj, path) {
    if (!obj || !path) return undefined;
    let cur = obj;
    for (const key of String(path).split('.')) {
        if (cur === null || cur === undefined) return undefined;
        cur = cur[key];
    }
    return cur;
}

/** Pull one metric's value out of a single history point. Returns null when
 *  the point does not carry that field (e.g. load on an agent server). */
export function readPoint(point, metric) {
    if (!point || !metric) return null;
    for (const path of metric.paths || []) {
        const raw = readAt(point, path);
        if (typeof raw === 'number' && Number.isFinite(raw)) {
            return metric.scale ? raw * metric.scale : raw;
        }
    }
    return null;
}

/** Pull one metric's value out of the live /system/metrics payload. */
export function readLive(liveMetrics, metric) {
    if (!liveMetrics || !metric || !metric.live) return null;
    const raw = readAt(liveMetrics, metric.live);
    if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
    return metric.scale ? raw * metric.scale : raw;
}

/**
 * Turn a history payload ({ data: [...] } from either endpoint) into a plain
 * number[] for one metric. Points missing the field are skipped, so a metric
 * with no backing column yields an empty series rather than a row of zeroes.
 */
export function seriesFrom(payload, metricId) {
    const metric = getMetric(metricId);
    const points = Array.isArray(payload?.data) ? payload.data : [];
    const out = [];
    for (const point of points) {
        const value = readPoint(point, metric);
        if (value !== null) out.push(value);
    }
    return out;
}

/** Timestamps that line up 1:1 with seriesFrom() for the same metric. */
export function stampsFrom(payload, metricId) {
    const metric = getMetric(metricId);
    const points = Array.isArray(payload?.data) ? payload.data : [];
    const out = [];
    for (const point of points) {
        if (readPoint(point, metric) !== null) out.push(point.timestamp || null);
    }
    return out;
}

/** Reduce a series to one number. Unknown aggregations behave as 'last'. */
export function aggregate(series, agg) {
    const values = (series || []).filter((v) => typeof v === 'number' && Number.isFinite(v));
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    switch (agg) {
        case 'avg':
            return values.reduce((a, b) => a + b, 0) / values.length;
        case 'max':
            return sorted[sorted.length - 1];
        case 'min':
            return sorted[0];
        case 'p95':
            return sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)];
        default:
            return values[values.length - 1];
    }
}

/**
 * Percentage change of the aggregate between the older 60% of the window and
 * the whole window — the same "vs earlier in this range" delta the stat tile
 * shows. Returns null when there is not enough history to be honest about it.
 */
export function deltaPercent(series, agg) {
    const values = (series || []).filter((v) => typeof v === 'number' && Number.isFinite(v));
    if (values.length < 4) return null;
    const head = values.slice(0, Math.floor(values.length * 0.6));
    if (!head.length) return null;
    const now = aggregate(values, agg);
    const before = aggregate(head, agg);
    if (now === null || !before) return null;
    return ((now - before) / Math.abs(before)) * 100;
}

/** Human-readable value + unit. `null`/NaN render as an em dash. */
export function formatValue(value, unit) {
    if (value === null || value === undefined || !Number.isFinite(value)) return '—';
    if (unit === '%') return `${Math.round(value * 10) / 10}%`;
    const num = Math.abs(value) >= 1000
        ? `${(value / 1000).toFixed(1)}k`
        : `${Math.round(value * 100) / 100}`;
    return unit ? `${num} ${unit}` : num;
}

/**
 * Threshold colour for a value. `thresholds` is [amber, red]; anything below
 * amber is green. Returns null when no thresholds are configured so callers
 * can fall back to the metric's own colour.
 */
export function thresholdColor(value, thresholds) {
    if (!Array.isArray(thresholds) || thresholds.length === 0) return null;
    if (value === null || value === undefined || !Number.isFinite(value)) return null;
    const [amber, red] = thresholds;
    if (Number.isFinite(red) && value >= red) return 'var(--red)';
    if (Number.isFinite(amber) && value >= amber) return 'var(--amber)';
    return 'var(--green)';
}

/**
 * Fixed y-axis domain for a set of metrics, or null to scale to the data.
 *
 * Percentages get a hard [0, 100]. Auto-scaling them reads badly in both
 * directions: a single spike compresses the rest of the series into a flat line
 * at the bottom, and a metric that idles between 0.4% and 0.7% gets stretched
 * into dramatic mountains that mean nothing. A percentage already has an
 * absolute frame of reference — use it.
 *
 * Only applied when EVERY series is a percentage. A chart mixing CPU% with load
 * average would flatten the load into the floor, so mixed units keep scaling to
 * their data.
 */
export function chartDomain(metricIds) {
    const ids = (metricIds || []).filter(Boolean);
    if (!ids.length) return null;
    const metrics = ids.map((id) => getMetric(id));
    const allPercent = metrics.every((m) => m && m.unit === '%' && m.max === 100);
    return allPercent ? [0, 100] : null;
}
