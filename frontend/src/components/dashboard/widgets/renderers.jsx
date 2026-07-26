/**
 * The 13 core dashboard widget renderers (plan 62).
 *
 * Every renderer is presentational — all fetching lives in ./useWidgetData.
 * Every renderer handles three states: loading, empty and error. Nothing here
 * may throw: `WidgetBody` wraps each one in a boundary so one bad widget can
 * never take the grid down with it.
 */
import { Component, useEffect, useId, useMemo, useRef } from 'react';
import {
    Activity,
    Archive,
    ArrowDown,
    ArrowUp,
    Boxes,
    Container,
    Database,
    FolderOpen,
    Globe,
    ListChecks,
    Rocket,
    Server,
    ShieldCheck,
    Terminal,
} from 'lucide-react';
import { Gauge, Pill, Sparkline } from '@/components/ds';
import { getWidgetType } from './registry';
import {
    aggregate,
    deltaPercent,
    formatValue,
    getMetric,
    sourceOf,
    thresholdColor,
} from './metrics';
import {
    useActivity,
    useDeployJobs,
    useFleetHeatmap,
    useLogTail,
    useMetricSeries,
    useMetricSeriesSet,
    useOpenAlerts,
    useResourceLabel,
    useResourceRows,
    useStatusCells,
    useSystemSpecs,
} from './useWidgetData';

/* ------------------------------------------------------------ shared bits */

// A widget's `cfg.resource` may be the literal '$server' dashboard variable.
function resolveResource(resource, ctx) {
    if (resource === '$server') return ctx?.serverVar || 'local';
    return resource || 'local';
}

function Loading({ label = 'Loading…' }) {
    return <div className="skw-empty skw-empty--loading">{label}</div>;
}

function Empty({ children }) {
    return <div className="skw-empty">{children}</div>;
}

// Muted one-liner. A 403 is phrased as a permission note, not a failure.
function Failed({ error, subject = 'data' }) {
    if (error?.forbidden) {
        return <div className="skw-empty skw-empty--error">Your role cannot read {subject}.</div>;
    }
    return (
        <div className="skw-empty skw-empty--error">
            Could not load {subject}
            {error?.message ? ` — ${error.message}` : '.'}
        </div>
    );
}

function relTime(value) {
    if (!value) return '';
    const stamp = new Date(value).getTime();
    if (Number.isNaN(stamp)) return '';
    const minutes = Math.floor(Math.max(0, Date.now() - stamp) / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
}

const OK_STATE = /^(running|healthy|online|succeeded|success|completed|up|active)$/i;
const BAD_STATE = /^(failed|error|down|exited|stopped|offline|cancelled)$/i;

function pillKind(state) {
    const value = String(state || '');
    if (OK_STATE.test(value)) return 'green';
    if (BAD_STATE.test(value)) return 'red';
    return 'amber';
}

/**
 * Multi-series area chart. Hand-rolled rather than reusing ds/AreaChart
 * because a widget needs the fill toggle and a height that tracks its cell.
 * Gradient ids are per-instance (useId) so two charts on one board cannot
 * capture each other's fills.
 */
function WidgetChart({ series, colors, fill = true, grid = true, height = '100%' }) {
    const uid = useId().replace(/:/g, '');
    const data = (series || []).filter((s) => Array.isArray(s) && s.length > 0);
    const all = data.flat();
    if (!all.length) return null;

    const w = 100;
    const h = 100;
    const max = Math.max(...all) * 1.12;
    const min = Math.min(...all) * 0.7;
    const span = max - min || 1;
    const toX = (i, len) => (i / (len - 1 || 1)) * w;
    const toY = (v) => h - ((v - min) / span) * h;
    const line = (s) => s.map((v, i) => `${i ? 'L' : 'M'}${toX(i, s.length).toFixed(2)} ${toY(v).toFixed(2)}`).join(' ');

    return (
        <svg
            viewBox={`0 0 ${w} ${h}`}
            preserveAspectRatio="none"
            style={{ width: '100%', height, display: 'block' }}
            aria-hidden="true"
        >
            <defs>
                {colors.map((color, i) => (
                    <linearGradient key={i} id={`skw-${uid}-${i}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={color} stopOpacity="0.26" />
                        <stop offset="100%" stopColor={color} stopOpacity="0" />
                    </linearGradient>
                ))}
            </defs>
            {grid && [0, 25, 50, 75, 100].map((y) => (
                <line
                    key={y}
                    x1="0"
                    y1={y}
                    x2={w}
                    y2={y}
                    stroke="var(--border-soft)"
                    strokeWidth="0.4"
                    vectorEffect="non-scaling-stroke"
                />
            ))}
            {fill && data.map((s, i) => (
                <path key={`a${i}`} d={`${line(s)} L ${w} ${h} L 0 ${h} Z`} fill={`url(#skw-${uid}-${i % colors.length})`} />
            ))}
            {data.map((s, i) => (
                <path
                    key={`l${i}`}
                    d={line(s)}
                    fill="none"
                    stroke={colors[i % colors.length]}
                    strokeWidth="1.6"
                    vectorEffect="non-scaling-stroke"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                />
            ))}
        </svg>
    );
}

// Phrase why a metric has no series on this resource, using real reasons.
function unsupportedNote(metric, resource) {
    const where = sourceOf(resource) === 'local' ? 'the local host' : 'agent servers';
    return `${metric.label} is not collected for ${where}.`;
}

/* -------------------------------------------------------------------- stat */

function WStat({ cfg, ctx }) {
    const resource = resolveResource(cfg.resource, ctx);
    const label = useResourceLabel(resource);
    const agg = cfg.agg || 'last';
    const { series, loading, error, supported, metric } = useMetricSeries(resource, cfg.metric, ctx.range, ctx.tick);

    if (loading && !series.length) return <Loading />;
    if (error) return <Failed error={error} subject="metrics" />;
    if (!supported) return <Empty>{unsupportedNote(metric, resource)}</Empty>;
    if (!series.length) return <Empty>No samples recorded in this range yet.</Empty>;

    const value = aggregate(series, agg);
    const delta = deltaPercent(series, agg);
    const color = cfg.color || thresholdColor(value, cfg.thresholds) || metric.color;

    return (
        <div className="skw-stat">
            <div className="skw-stat__value" style={{ color }}>{formatValue(value, metric.unit)}</div>
            <div className="skw-stat__meta mono">
                {delta === null ? (
                    <span className="faint">no trend yet</span>
                ) : (
                    // Written out rather than interpolated so the modifier is a
                    // literal a stylesheet audit can find.
                    <span className={delta >= 0 ? 'skw-stat__delta skw-stat__delta--up' : 'skw-stat__delta skw-stat__delta--down'}>
                        {delta >= 0 ? <ArrowUp size={11} /> : <ArrowDown size={11} />}
                        {Math.abs(delta).toFixed(1)}%
                    </span>
                )}
                <span className="faint">{agg} · {label}</span>
            </div>
            {cfg.spark !== false && (
                <div className="skw-stat__spark">
                    <Sparkline data={series} color={color} width={220} height={40} />
                </div>
            )}
        </div>
    );
}

/* -------------------------------------------------------------- timeseries */

// A board should not be able to ask for an unreadable number of lines.
const MAX_SERIES = 6;

function WTimeseries({ cfg, ctx }) {
    const serverVar = ctx.serverVar;
    const entries = useMemo(() => {
        const configured = Array.isArray(cfg.series) && cfg.series.length
            ? cfg.series
            : [{ resource: '$server', metric: 'cpu' }];
        return configured.slice(0, MAX_SERIES).map((entry) => ({
            resource: entry?.resource === '$server' ? (serverVar || 'local') : (entry?.resource || 'local'),
            metric: entry?.metric,
            color: entry?.color || '',
        }));
    }, [cfg.series, serverVar]);

    const { rows, loading, error } = useMetricSeriesSet(entries, ctx.range, ctx.tick);
    const withData = rows.filter((r) => r.supported && r.series.length > 0);

    if (error) return <Failed error={error} subject="metrics" />;
    if (loading && !withData.length) return <Loading />;
    if (!withData.length) {
        const blocked = rows.find((r) => !r.supported);
        return (
            <Empty>
                {blocked
                    ? unsupportedNote(blocked.metric, blocked.resource)
                    : 'No samples recorded in this range yet.'}
            </Empty>
        );
    }

    const colors = withData.map((row) => row.color || row.metric.color);

    return (
        <div className="skw-ts">
            <div className="skw-ts__chart">
                <WidgetChart
                    series={withData.map((r) => r.series)}
                    colors={colors}
                    fill={cfg.fill !== false}
                />
            </div>
            {cfg.legend !== false && (
                <div className="skw-legend">
                    {withData.map((row, i) => {
                        const last = row.series[row.series.length - 1];
                        return (
                            <span className="skw-legend__item" key={`${row.resource}-${row.metric.id}-${i}`}>
                                <span className="skw-legend__swatch" style={{ background: colors[i] }} />
                                {row.metric.label}
                                <b>{formatValue(last, row.metric.unit)}</b>
                            </span>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

/* ------------------------------------------------------------------- gauge */

// Half-circle radial. No ds primitive covers this shape (ds/Gauge is a linear
// meter), so the arc is hand-rolled.
const GAUGE_RADIUS = 54;
const GAUGE_ARC = Math.PI * GAUGE_RADIUS;
const GAUGE_PATH = 'M16 72 A54 54 0 0 1 124 72';

function WGauge({ cfg, ctx }) {
    const resource = resolveResource(cfg.resource, ctx);
    const label = useResourceLabel(resource);
    const { series, loading, error, supported, metric } = useMetricSeries(resource, cfg.metric, ctx.range, ctx.tick);

    if (loading && !series.length) return <Loading />;
    if (error) return <Failed error={error} subject="metrics" />;
    if (!supported) return <Empty>{unsupportedNote(metric, resource)}</Empty>;
    if (!series.length) return <Empty>No samples recorded in this range yet.</Empty>;

    const value = aggregate(series, cfg.agg || 'last');
    // Percentage metrics have a real ceiling; rates do not, so scale to the
    // observed peak rather than inventing a maximum.
    const ceiling = metric.max || Math.max(...series) * 1.15 || 1;
    const ratio = Math.max(0, Math.min(1, (value ?? 0) / ceiling));
    const color = thresholdColor(value, cfg.thresholds) || metric.color;

    return (
        <div className="skw-gauge">
            <svg viewBox="0 0 140 82" style={{ width: '100%', maxWidth: 200 }} role="img" aria-label={`${metric.label} ${formatValue(value, metric.unit)}`}>
                <path d={GAUGE_PATH} fill="none" stroke="var(--surface-3)" strokeWidth="12" strokeLinecap="round" />
                <path
                    d={GAUGE_PATH}
                    fill="none"
                    stroke={color}
                    strokeWidth="12"
                    strokeLinecap="round"
                    strokeDasharray={`${(GAUGE_ARC * ratio).toFixed(1)} ${GAUGE_ARC.toFixed(1)}`}
                />
                <text x="70" y="63" textAnchor="middle" fill={color} style={{ font: '600 24px var(--sans)' }}>
                    {formatValue(value, metric.unit)}
                </text>
            </svg>
            <div className="skw-gauge__sub mono">
                {label}{metric.max ? ` · max ${metric.max}${metric.unit}` : ''}
            </div>
        </div>
    );
}

/* -------------------------------------------------------------------- topn */

// The fleet heatmap exposes exactly these three per-server metrics.
const HEATMAP_KEY = { cpu: 'cpu', ram: 'memory', disk: 'disk' };

function WTopN({ cfg, ctx }) {
    const { servers, loading, error } = useFleetHeatmap(ctx.tick);
    const metric = getMetric(cfg.metric);
    const key = HEATMAP_KEY[metric.id];

    if (loading && !servers.length) return <Loading />;
    if (error) return <Failed error={error} subject="fleet metrics" />;
    if (!key) {
        return <Empty>{metric.label} cannot be ranked across servers — pick CPU, memory or disk.</Empty>;
    }

    const rows = servers
        .map((s) => ({ id: s.id, label: s.name, value: s[key] }))
        .filter((r) => typeof r.value === 'number' && Number.isFinite(r.value))
        .sort((a, b) => b.value - a.value)
        .slice(0, Math.max(1, Number(cfg.limit) || 5));

    if (!rows.length) return <Empty>No fleet servers are reporting metrics yet.</Empty>;

    const peak = Math.max(...rows.map((r) => r.value), 1);

    return (
        <div className="skw-topn">
            {rows.map((row) => (
                <div className="skw-topn__row" key={row.id}>
                    <span className="skw-topn__label">{row.label}</span>
                    <Gauge
                        className="skw-topn__track"
                        value={(row.value / peak) * 100}
                        color={metric.color}
                    />
                    <span className="skw-topn__value mono">{formatValue(row.value, metric.unit)}</span>
                </div>
            ))}
        </div>
    );
}

/* ------------------------------------------------------------------- table */

const TABLE_DEFS = {
    services: {
        empty: 'No applications yet.',
        cols: [['Name', 'name'], ['Type', 'app_type'], ['Status', 'status'], ['Server', 'server_name']],
        href: (row) => `/services/${row.id}`,
    },
    servers: {
        empty: 'No servers connected.',
        cols: [['Name', 'name'], ['Status', 'status'], ['Group', 'group_name'], ['OS', 'os_type']],
        href: (row) => (row.is_local ? '/servers' : `/servers/${row.id}`),
    },
    containers: {
        empty: 'No containers on this host.',
        cols: [['Name', 'name'], ['Image', 'image'], ['Status', 'state'], ['Ports', 'ports']],
        href: () => '/docker',
    },
    deploys: {
        empty: 'No deployments recorded.',
        cols: [['App', 'app_name'], ['Trigger', 'trigger'], ['Status', 'status'], ['When', 'created_at']],
        href: (row) => `/deployments/${row.id}`,
    },
};

function WTable({ cfg, ctx }) {
    const limit = Math.max(1, Number(cfg.limit) || 6);
    const { rows, loading, error, source } = useResourceRows(cfg.source, limit, ctx.tick);
    const def = TABLE_DEFS[source] || TABLE_DEFS.services;

    if (loading && !rows.length) return <Loading />;
    if (error) return <Failed error={error} subject={source} />;
    if (!rows.length) return <Empty>{def.empty}</Empty>;

    return (
        <div className="skw-table-wrap">
            <table className="skw-table">
                <thead>
                    <tr>{def.cols.map(([label]) => <th key={label}>{label}</th>)}</tr>
                </thead>
                <tbody>
                    {rows.map((row, i) => (
                        <tr key={row.id ?? i} onClick={() => ctx.navigate?.(def.href(row))}>
                            {def.cols.map(([label, key]) => {
                                const value = row[key];
                                if (key === 'status' || key === 'state') {
                                    return (
                                        <td key={label}>
                                            <Pill kind={pillKind(value)}>{value || 'unknown'}</Pill>
                                        </td>
                                    );
                                }
                                const isName = key === 'name' || key === 'app_name';
                                const text = key === 'created_at' ? relTime(value) : value;
                                return (
                                    <td key={label} className={isName ? 'nm' : 'mono'}>
                                        {text === null || text === undefined || text === '' ? '—' : String(text)}
                                    </td>
                                );
                            })}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

/* -------------------------------------------------------------------- logs */

function WLogs({ cfg, ctx }) {
    const bodyRef = useRef(null);
    const { lines, label, loading, error } = useLogTail(cfg, ctx.tick);

    const shown = cfg.level && cfg.level !== 'all'
        ? lines.filter((l) => l.lvl === cfg.level)
        : lines;

    useEffect(() => {
        if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }, [shown.length]);

    if (loading && !lines.length) return <Loading />;
    if (error) return <Failed error={error} subject="logs" />;
    if (!lines.length) return <Empty>No log lines available.</Empty>;

    const counts = lines.reduce((acc, l) => ({ ...acc, [l.lvl]: (acc[l.lvl] || 0) + 1 }), {});

    return (
        <div className="skw-logs">
            <div className="skw-logs__bar mono">
                <span>{label || 'log'}</span>
                <span className="faint">{lines.length} lines</span>
                {counts.err ? <span className="lv-err">{counts.err} errors</span> : null}
                {counts.warn ? <span className="lv-warn">{counts.warn} warnings</span> : null}
            </div>
            <div className="skw-logs__body" ref={bodyRef}>
                {shown.length === 0 ? (
                    <Empty>No lines at this level.</Empty>
                ) : shown.map((l, i) => (
                    <div className={`skw-logs__line lv-${l.lvl}`} key={i}>
                        {l.t ? <span className="t">{l.t}</span> : null}
                        {l.txt}
                    </div>
                ))}
            </div>
        </div>
    );
}

/* ----------------------------------------------------------------- deploys */

const DEPLOY_COLOR = {
    succeeded: 'var(--green)',
    completed: 'var(--green)',
    failed: 'var(--red)',
    running: 'var(--amber)',
};

// A job reports total_steps + current_step; derive each dot's state from those
// rather than inventing per-step records the API does not return.
function stepState(index, job) {
    if (index < job.current_step) return 'done';
    if (index > job.current_step) return '';
    if (job.status === 'failed') return 'failed';
    if (job.status === 'running') return 'running';
    return job.status === 'succeeded' || job.status === 'completed' ? 'done' : '';
}

function WDeploys({ cfg, ctx }) {
    const { jobs, loading, error } = useDeployJobs(cfg.limit, ctx.tick);

    if (loading && !jobs.length) return <Loading />;
    if (error) return <Failed error={error} subject="deployments" />;
    if (!jobs.length) return <Empty>No deployments yet.</Empty>;

    return (
        <div className="skw-list">
            {jobs.map((job) => (
                <div
                    className="skw-dep"
                    key={job.id}
                    onClick={() => ctx.navigate?.(`/deployments/${job.id}`)}
                >
                    <div className="skw-dep__top">
                        <span className="skw-dep__name">{job.app_name || job.kind || 'deployment'}</span>
                        <span className="skw-dep__state mono" style={{ color: DEPLOY_COLOR[job.status] || 'var(--text-faint)' }}>
                            {job.status}
                        </span>
                    </div>
                    {job.total_steps > 0 && (
                        <div className="skw-dep__steps">
                            {Array.from({ length: job.total_steps }, (_, i) => (
                                <i key={i} className={`st ${stepState(i, job)}`} />
                            ))}
                        </div>
                    )}
                    <div className="skw-dep__meta mono">
                        {job.trigger || 'manual'} · {job.target_server_name || 'local'} · {relTime(job.created_at) || '—'}
                    </div>
                </div>
            ))}
        </div>
    );
}

/* ------------------------------------------------------------------ alerts */

const SEVERITY_COLOR = { critical: 'var(--red)', warning: 'var(--amber)' };

function WAlerts({ cfg, ctx }) {
    const { alerts, loading, error } = useOpenAlerts(cfg.limit, ctx.tick);

    if (loading && !alerts.length) return <Loading />;
    if (error) return <Failed error={error} subject="alerts" />;

    const shown = cfg.severity && cfg.severity !== 'all'
        ? alerts.filter((a) => a.severity === cfg.severity)
        : alerts;

    if (!shown.length) return <Empty>No alerts firing.</Empty>;

    return (
        <div className="skw-list">
            {shown.map((alert) => {
                const color = SEVERITY_COLOR[alert.severity] || 'var(--cyan)';
                return (
                    <div className="skw-alert" key={alert.id} onClick={() => ctx.navigate?.('/monitoring')}>
                        <span className="skw-alert__sev" style={{ background: color, boxShadow: `0 0 7px ${color}` }} />
                        <div className="skw-alert__body">
                            <div className="skw-alert__title">{alert.title}</div>
                            <div className="skw-alert__meta mono">
                                {alert.target}{alert.time ? ` · ${relTime(alert.time)}` : ''}
                            </div>
                        </div>
                        <Pill kind={alert.state === 'firing' ? 'red' : 'amber'}>{alert.state}</Pill>
                    </div>
                );
            })}
        </div>
    );
}

/* ------------------------------------------------------------------ status */

const STATE_COLOR = { up: 'var(--green)', down: 'var(--red)', unknown: 'var(--amber)' };

function WStatus({ cfg, ctx }) {
    const { cells, loading, error, source } = useStatusCells(cfg.source, cfg.limit, ctx.tick);

    if (loading && !cells.length) return <Loading />;
    if (error) return <Failed error={error} subject={source} />;
    if (!cells.length) return <Empty>Nothing to monitor yet.</Empty>;

    const target = source === 'services' ? '/services' : '/servers';

    return (
        <div className="skw-status">
            {cells.map((cell) => {
                const color = STATE_COLOR[cell.state] || 'var(--amber)';
                return (
                    <div
                        className="skw-status__cell"
                        key={cell.id}
                        onClick={() => ctx.navigate?.(target)}
                        title={`${cell.name} · ${cell.state}`}
                    >
                        <span className="skw-status__dot" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
                        <div className="skw-status__name">{cell.name}</div>
                        <div className="skw-status__meta mono">{cell.meta || cell.state}</div>
                    </div>
                );
            })}
        </div>
    );
}

/* -------------------------------------------------------------------- feed */

// Turn an audit action ('app.deploy', 'user.login') into something readable
// without pretending we know more than the row carries.
function describeLog(entry) {
    const action = String(entry.action || 'change').replace(/[._]/g, ' ');
    const who = entry.username || 'system';
    const what = entry.target_type
        ? `${entry.target_type}${entry.target_id ? ` #${entry.target_id}` : ''}`
        : '';
    return what ? `${who} · ${action} · ${what}` : `${who} · ${action}`;
}

function WFeed({ cfg, ctx }) {
    const isAdmin = Boolean(ctx.isAdmin);
    const { items, loading, error } = useActivity(cfg.limit, isAdmin, ctx.tick);

    // The audit trail lives behind /admin/activity/feed. Say so instead of
    // firing a request that can only come back 403.
    if (!isAdmin) return <Empty>Requires admin.</Empty>;
    if (loading && !items.length) return <Loading />;
    if (error) return <Failed error={error} subject="the activity feed" />;
    if (!items.length) return <Empty>No recorded activity yet.</Empty>;

    return (
        <div className="skw-list">
            {items.map((entry) => (
                <div className="skw-feed__item" key={entry.id} onClick={() => ctx.navigate?.('/security')}>
                    <span className="skw-feed__dot" />
                    <div className="skw-feed__body">
                        <div className="skw-feed__text">{describeLog(entry)}</div>
                        <div className="skw-feed__time mono">{relTime(entry.created_at)}</div>
                    </div>
                </div>
            ))}
        </div>
    );
}

/* ----------------------------------------------------------------- actions */

// Every destination is a real route registered in App.jsx.
const ACTIONS = {
    servers: ['Manage servers', Server, '/servers'],
    services: ['Services', Boxes, '/services'],
    docker: ['Docker containers', Container, '/docker'],
    terminal: ['Open terminal', Terminal, '/terminal'],
    deploys: ['Deploy activity', Rocket, '/deployments'],
    databases: ['Databases', Database, '/databases'],
    backups: ['Backups', Archive, '/backups'],
    monitoring: ['Monitoring', Activity, '/monitoring'],
    domains: ['Domains', Globe, '/domains'],
    files: ['File manager', FolderOpen, '/files'],
    security: ['Security', ShieldCheck, '/security'],
    jobs: ['Jobs', ListChecks, '/jobs'],
};

export const QUICK_ACTION_KEYS = Object.keys(ACTIONS);

// [key, label] pairs for the inspector's shortcut picker. Derived from ACTIONS
// so the list of shortcuts a user can *choose* can never drift from the list
// this widget can actually *render* — they did drift once already.
export const QUICK_ACTION_OPTIONS = Object.entries(ACTIONS).map(([key, [label]]) => [key, label]);

function WActions({ cfg, ctx }) {
    const items = (Array.isArray(cfg.items) ? cfg.items : []).filter((key) => ACTIONS[key]);
    if (!items.length) return <Empty>No actions selected.</Empty>;

    return (
        <div className="skw-actions">
            {items.map((key) => {
                const [label, Icon, href] = ACTIONS[key];
                return (
                    <button type="button" className="skw-actions__row" key={key} onClick={() => ctx.navigate?.(href)}>
                        <span className="skw-actions__label">{label}</span>
                        <span className="skw-actions__icon"><Icon size={15} /></span>
                    </button>
                );
            })}
        </div>
    );
}

/* ------------------------------------------------------------------- specs */

function WSpecs({ cfg, ctx }) {
    const resource = resolveResource(cfg.resource, ctx);
    const { rows, loading, error } = useSystemSpecs(resource, ctx.tick);

    if (loading && !rows.length) return <Loading />;
    if (error) return <Failed error={error} subject="host details" />;
    if (!rows.length) return <Empty>This host reported no details.</Empty>;

    return (
        <div className="skw-kv">
            {rows.map(([key, value]) => (
                <div className="skw-kv__row" key={key}>
                    <span className="skw-kv__k">{key}</span>
                    <span className="skw-kv__v">{value}</span>
                </div>
            ))}
        </div>
    );
}

/* -------------------------------------------------------------------- note */

// Minimal inline markdown rendered as React nodes. Deliberately NOT an HTML
// string: no dangerouslySetInnerHTML means no sink to sanitize.
function renderInline(text, keyPrefix) {
    const nodes = [];
    const pattern = /\*\*([^*]+)\*\*|`([^`]+)`/g;
    let cursor = 0;
    let match = pattern.exec(text);
    let n = 0;

    while (match) {
        if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
        if (match[1] !== undefined) {
            nodes.push(<b key={`${keyPrefix}-b${n}`}>{match[1]}</b>);
        } else {
            nodes.push(<code className="mono" key={`${keyPrefix}-c${n}`}>{match[2]}</code>);
        }
        cursor = match.index + match[0].length;
        n += 1;
        match = pattern.exec(text);
    }
    if (cursor < text.length) nodes.push(text.slice(cursor));
    return nodes;
}

function WNote({ cfg }) {
    const text = typeof cfg.text === 'string' ? cfg.text : '';
    if (!text.trim()) return <Empty>Empty note — add text in the widget settings.</Empty>;

    return (
        <div className="skw-note">
            {text.split('\n').map((line, i) => (
                <p key={i}>{line ? renderInline(line, `l${i}`) : ' '}</p>
            ))}
        </div>
    );
}

/* --------------------------------------------------------------- dispatch */

const CORE_RENDERERS = {
    stat: WStat,
    timeseries: WTimeseries,
    gauge: WGauge,
    topn: WTopN,
    table: WTable,
    logs: WLogs,
    deploys: WDeploys,
    alerts: WAlerts,
    status: WStatus,
    feed: WFeed,
    actions: WActions,
    specs: WSpecs,
    note: WNote,
};

/**
 * Last line of defence. A renderer that throws (a plugin widget, or a core one
 * fed a malformed saved cfg) degrades to a muted note instead of unmounting
 * the whole grid.
 */
class WidgetBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { failed: false };
    }

    static getDerivedStateFromError() {
        return { failed: true };
    }

    componentDidCatch(error) {
        console.error(`Dashboard widget "${this.props.widgetType}" crashed:`, error);
    }

    render() {
        if (this.state.failed) {
            return <div className="skw-empty skw-empty--error">This widget failed to render.</div>;
        }
        return this.props.children;
    }
}

/**
 * Render one widget's body.
 *
 * `ctx` carries { range, tick, serverVar, isAdmin, navigate } and may also
 * carry `types` (the merged registry from useWidgetTypes) — when present,
 * plugin-contributed widget types render through their own component.
 * An unknown type renders a `.skw-empty` notice and never throws.
 */
export function WidgetBody({ widget, ctx }) {
    const safeCtx = ctx || {};
    const type = widget?.type;

    const Core = type ? CORE_RENDERERS[type] : null;
    const contributed = !Core && type
        ? getWidgetType(safeCtx.types, type)?.component || null
        : null;
    const Renderer = Core || contributed;

    if (!Renderer) {
        return <div className="skw-empty">Unknown widget type “{String(type ?? '')}”.</div>;
    }

    return (
        <WidgetBoundary key={`${widget?.i ?? ''}:${type}`} widgetType={type}>
            <Renderer cfg={widget?.cfg || {}} ctx={safeCtx} widget={widget} />
        </WidgetBoundary>
    );
}

export default WidgetBody;
