// MonitorDetail — the drill-down for a single check.
//
// Outside the Monitoring tab group (like /queue/:group/:queue) because it is a
// drill-down, so it carries its own PageTopbar with a breadcrumb back to the
// list. Its sections are a SegControl, not a tab strip: a nav under the page's
// own header would be the same two-competing-headers problem the group layout
// exists to avoid.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
    Activity, ArrowLeft, BarChart3, CheckCircle2, Clock, ExternalLink, Lock,
    Pause, Play, RefreshCw, Rows3, ShieldAlert, SlidersHorizontal, Trash2, Zap,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useConfirm } from '../hooks/useConfirm';
import EmptyState from '../components/EmptyState';
import UptimeBars from '../components/monitoring/UptimeBars';
import { monitorStateOf } from '../components/monitoring/monitorShared';
import {
    AreaChart, ColumnsMenu, DataTable, DataTableFooter, KpiBand, MetricCard,
    Pill, SegControl, SortMenu,
} from '@/components/ds';
import PageLayout from '../layouts/PageLayout';
import { Button } from '@/components/ui/button';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';

const POLL_MS = 15000;

const SECTIONS = [
    { value: 'performance', label: 'Performance', icon: <Activity size={14} /> },
    { value: 'uptime', label: 'Uptime', icon: <BarChart3 size={14} /> },
    { value: 'checks', label: 'Check log', icon: <Rows3 size={14} /> },
    { value: 'config', label: 'Configuration', icon: <SlidersHorizontal size={14} /> },
];

const RANGES = [
    { value: 1, label: '1h' },
    { value: 24, label: '24h' },
    { value: 168, label: '7d' },
    { value: 720, label: '30d' },
];

function percentile(values, p) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
}

function formatUptime(value) {
    return value == null ? '—' : `${Number(value).toFixed(2)}%`;
}

function certDaysLeft(iso) {
    if (!iso) return null;
    return Math.round((new Date(iso).getTime() - Date.now()) / 86400000);
}

export default function MonitorDetail() {
    const { monitorId } = useParams();
    const navigate = useNavigate();
    const toast = useToast();
    const { confirm } = useConfirm();

    const [monitor, setMonitor] = useState(null);
    const [checks, setChecks] = useState([]);
    const [uptime, setUptime] = useState(null);
    const [loading, setLoading] = useState(true);
    const [notFound, setNotFound] = useState(false);
    const [section, setSection] = useState('performance');
    const [rangeHours, setRangeHours] = useState(24);
    const [selectedDay, setSelectedDay] = useState(null);
    // Freezing the log is what makes a streaming table readable — without it the
    // row you are reading slides away on the next poll.
    const [frozen, setFrozen] = useState(null);
    const [busy, setBusy] = useState(false);
    const pollRef = useRef(null);
    // Sort/column state for the check log lives above the early returns so the
    // hook order never changes; storageKey keeps the choices across visits.
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-monitor-checks-sort' });
    const { hiddenKeys, toggleColumn, showAllColumns } = useColumnVisibility({
        storageKey: 'serverkit-table-monitor-checks-cols',
    });

    const load = useCallback(async () => {
        try {
            const [monitorRes, historyRes, uptimeRes] = await Promise.all([
                api.getMonitor(monitorId),
                api.getMonitorHistory(monitorId, { hours: rangeHours, limit: 300 }),
                api.getMonitorUptime(monitorId, 90).catch(() => null),
            ]);
            setMonitor(monitorRes);
            setChecks(historyRes?.checks || []);
            setUptime(uptimeRes || null);
        } catch (err) {
            if (String(err.message || '').toLowerCase().includes('not found')) setNotFound(true);
        } finally {
            setLoading(false);
        }
    }, [monitorId, rangeHours]);

    useEffect(() => {
        load();
        pollRef.current = setInterval(load, POLL_MS);
        return () => clearInterval(pollRef.current);
    }, [load]);

    // Oldest-first for the chart; the API returns newest-first for the log.
    const series = useMemo(() => {
        const withTiming = checks.filter((c) => c.response_time != null);
        return [...withTiming].reverse().map((c) => c.response_time);
    }, [checks]);

    const stats = useMemo(() => {
        if (!series.length) return { avg: null, min: null, max: null, p95: null };
        return {
            avg: Math.round(series.reduce((a, b) => a + b, 0) / series.length),
            min: Math.min(...series),
            max: Math.max(...series),
            p95: percentile(series, 0.95),
        };
    }, [series]);

    // Both pre-load states keep the shell, so the bar is in place from the
    // first paint rather than appearing once the monitor resolves.
    if (loading && !monitor) {
        return (
            <PageLayout className="monitor-detail" icon={<ArrowLeft size={18} />} title="Monitor">
                <EmptyState loading loadingVariant="detail" title="Loading monitor" />
            </PageLayout>
        );
    }

    if (notFound || !monitor) {
        return (
            <PageLayout className="monitor-detail" icon={<ArrowLeft size={18} />} title="Monitor">
                <EmptyState
                    icon={ShieldAlert}
                    title="Monitor not found"
                    description="It may have been deleted."
                    action={<Button onClick={() => navigate('/monitoring/monitors')}>Back to monitors</Button>}
                />
            </PageLayout>
        );
    }

    const state = monitorStateOf(monitor);
    const certDays = certDaysLeft(monitor.cert_expires_at);
    const isHttpish = ['http', 'keyword'].includes(monitor.check_type);
    const rows = frozen || checks;
    const newSinceFreeze = frozen
        ? checks.filter((c) => !frozen.some((f) => f.id === c.id)).length
        : 0;
    const downMinutes = uptime?.days
        ? uptime.days.filter((d) => d.state !== 'none').reduce((total, d) => (
            total + Math.round(((100 - (d.uptime ?? 100)) / 100) * 1440)
        ), 0)
        : null;

    const checkColumns = [
        {
            key: 'checked_at',
            header: 'Time',
            sortable: true,
            hideable: false,
            render: (c) => new Date(c.checked_at).toLocaleTimeString(),
        },
        {
            key: 'status',
            header: 'Result',
            sortable: true,
            sortValue: (c) => c.status,
            render: (c) => (
                <span className={`mon-code mon-code--${c.status === 'up' ? 'ok' : 'bad'}`}>
                    {c.status_code ?? c.status}
                </span>
            ),
        },
        {
            key: 'response_time',
            header: 'Latency',
            sortable: true,
            render: (c) => (c.response_time == null ? '—' : `${c.response_time} ms`),
        },
        {
            key: 'error',
            header: 'Detail',
            cellClassName: 'mon-checkdetail',
            render: (c) => c.error || `${monitor.check_method || 'GET'} ${monitor.check_target}`,
        },
    ];

    const act = async (fn, successMessage) => {
        setBusy(true);
        try {
            await fn();
            if (successMessage) toast.success(successMessage);
            await load();
        } catch (err) {
            toast.error(err.message || 'Action failed');
        } finally {
            setBusy(false);
        }
    };

    const onCheckNow = () => act(async () => {
        const res = await api.runMonitorCheck(monitor.id);
        const check = res?.check;
        if (check?.status === 'up') toast.success(`Up in ${check.response_time ?? '—'} ms`);
        else toast.warning(`${check?.status || 'failed'}${check?.error ? ` — ${check.error}` : ''}`);
    });

    const onTogglePause = () => act(
        () => api.setMonitorPaused(monitor.id, !monitor.is_paused),
        monitor.is_paused ? 'Monitor resumed' : 'Monitor paused',
    );

    const onDelete = async () => {
        const ok = await confirm({
            title: 'Delete this monitor?',
            message: `“${monitor.name}” and its check history will be removed. Any open incident is resolved first.`,
            confirmText: 'Delete',
            variant: 'danger',
        });
        if (!ok) return;
        try {
            await api.deleteMonitor(monitor.id);
            toast.success('Monitor deleted');
            navigate('/monitoring/monitors');
        } catch (err) {
            toast.error(err.message || 'Could not delete the monitor');
        }
    };

    return (
        <PageLayout
            className="monitor-detail"
            icon={<ArrowLeft size={18} />}
            title={monitor.name}
            meta={`${monitor.check_type} · ${monitor.check_target || 'bound site'} · every ${monitor.check_interval}s`}
            actions={(
                <>
                    <Pill kind={state.tone}>{state.label}</Pill>
                    <Button variant="outline" size="sm" onClick={onCheckNow} disabled={busy}>
                        <RefreshCw size={14} /> Check now
                    </Button>
                    <Button variant="outline" size="sm" onClick={onTogglePause} disabled={busy}>
                        {monitor.is_paused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Pause</>}
                    </Button>
                    {isHttpish && monitor.check_target && (
                        <Button variant="outline" size="sm" asChild>
                            <a href={monitor.check_target} target="_blank" rel="noreferrer">
                                <ExternalLink size={14} />
                            </a>
                        </Button>
                    )}
                </>
            )}
        >

            <nav className="monitor-detail__crumb">
                <Link to="/monitoring/monitors">Monitors</Link>
                <span aria-hidden="true">/</span>
                <span>{monitor.name}</span>
            </nav>

            <KpiBand>
                <MetricCard
                    label="Response now" tone="cyan" icon={<Zap size={17} />}
                    value={monitor.last_response_time ?? '—'}
                    unit={monitor.last_response_time != null ? 'ms' : undefined}
                >
                    <div className="mon-kpi-sub">
                        avg {stats.avg ?? '—'} ms · p95 {stats.p95 ?? '—'} ms
                    </div>
                </MetricCard>
                <MetricCard
                    label="Uptime (30d)" tone="accent" icon={<CheckCircle2 size={17} />}
                    value={formatUptime(monitor.uptime_30d)}
                >
                    <div className="mon-kpi-sub">
                        24h {formatUptime(monitor.uptime_24h)} · 7d {formatUptime(monitor.uptime_7d)}
                    </div>
                </MetricCard>
                <MetricCard
                    label="Downtime (90d)" tone="amber" icon={<Clock size={17} />}
                    value={downMinutes ?? '—'} unit={downMinutes != null ? 'min' : undefined}
                >
                    <div className="mon-kpi-sub">
                        {uptime?.days ? `${uptime.days.filter((d) => d.state !== 'none' && d.state !== 'up').length} bad days` : 'no history yet'}
                    </div>
                </MetricCard>
                <MetricCard
                    label="Certificate"
                    tone={certDays == null ? 'accent' : certDays < 0 ? 'red' : certDays < 21 ? 'amber' : 'green'}
                    icon={<Lock size={17} />}
                    value={certDays == null ? 'n/a' : certDays < 0 ? 'Expired' : certDays}
                    unit={certDays != null && certDays >= 0 ? 'days' : undefined}
                >
                    <div className="mon-kpi-sub">
                        {monitor.cert_issuer || (isHttpish ? 'not read yet' : 'no TLS on this check')}
                    </div>
                </MetricCard>
            </KpiBand>

            <SegControl
                className="monitor-detail__sections"
                value={section}
                onChange={setSection}
                options={SECTIONS}
            />

            {section === 'performance' && (
                <div className="mon-panel">
                    <div className="mon-panel__header">
                        <div>
                            <h3>Response time</h3>
                            <span className="mon-panel-sub">
                                {series.length} sample{series.length === 1 ? '' : 's'} in this window
                            </span>
                        </div>
                        <SegControl
                            value={rangeHours}
                            onChange={setRangeHours}
                            options={RANGES}
                        />
                    </div>
                    {series.length === 0 ? (
                        <p className="mon-panel-hint">
                            No timed samples yet — the first check lands within {monitor.check_interval}s.
                        </p>
                    ) : (
                        <>
                            <AreaChart series={[series]} colors={['var(--cyan)']} height={220} />
                            <div className="mon-statstrip">
                                {[
                                    ['Average', stats.avg != null ? `${stats.avg} ms` : '—'],
                                    ['Fastest', stats.min != null ? `${stats.min} ms` : '—'],
                                    ['Slowest', stats.max != null ? `${stats.max} ms` : '—'],
                                    ['p95', stats.p95 != null ? `${stats.p95} ms` : '—'],
                                    ['Samples', series.length],
                                ].map(([label, value]) => (
                                    <div key={label}>
                                        <span className="mon-statstrip__label">{label}</span>
                                        <span className="mon-statstrip__value">{value}</span>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </div>
            )}

            {section === 'uptime' && (
                <div className="mon-stack">
                    <div className="mon-panel">
                        <div className="mon-panel__header">
                            <div>
                                <h3>Uptime — last 90 days</h3>
                                <span className="mon-panel-sub">Click a day for its detail</span>
                            </div>
                            <div className="mon-uptime-summary">
                                {[['24h', monitor.uptime_24h], ['7d', monitor.uptime_7d],
                                    ['30d', monitor.uptime_30d], ['90d', monitor.uptime_90d]].map(([label, value]) => (
                                    <div key={label}>
                                        <span className="mon-statstrip__label">{label}</span>
                                        <span className="mon-statstrip__value">{formatUptime(value)}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                        <UptimeBars
                            days={uptime?.days || []}
                            selected={selectedDay?.date}
                            onSelect={(day) => setSelectedDay(selectedDay?.date === day.date ? null : day)}
                        />
                        <div className="mon-uptime-axis">
                            <span>90 days ago</span>
                            <span>today</span>
                        </div>
                    </div>

                    {selectedDay && (
                        <div className="mon-panel">
                            <div className="mon-panel__header">
                                <div>
                                    <h3>{selectedDay.date}</h3>
                                    <span className="mon-panel-sub">
                                        {selectedDay.state === 'none'
                                            ? 'Not monitored on this day'
                                            : `${selectedDay.checks} checks · ${selectedDay.down_checks} failed · ${formatUptime(selectedDay.uptime)} uptime`}
                                    </span>
                                </div>
                                <Button variant="ghost" size="sm" onClick={() => setSelectedDay(null)}>Close</Button>
                            </div>
                        </div>
                    )}

                    <div className="mon-panel">
                        <div className="mon-panel__header">
                            <div>
                                <h3>Certificate</h3>
                                <span className="mon-panel-sub">Read from the last https probe</span>
                            </div>
                            {certDays != null && (
                                <Pill kind={certDays < 0 ? 'red' : certDays < 21 ? 'amber' : 'green'}>
                                    {certDays < 0 ? 'expired' : 'valid'}
                                </Pill>
                            )}
                        </div>
                        {monitor.cert_expires_at ? (
                            <dl className="mon-inforows">
                                <div><dt>Issuer</dt><dd>{monitor.cert_issuer || '—'}</dd></div>
                                <div><dt>Expires</dt><dd>{new Date(monitor.cert_expires_at).toLocaleDateString()}</dd></div>
                                <div>
                                    <dt>Remaining</dt>
                                    <dd>{certDays < 0 ? `${-certDays} days ago` : `${certDays} days`}</dd>
                                </div>
                            </dl>
                        ) : (
                            <p className="mon-panel-hint">
                                {isHttpish && monitor.check_target?.startsWith('https://')
                                    ? 'Not read yet — it is captured on the next probe.'
                                    : 'This check does not negotiate TLS.'}
                            </p>
                        )}
                    </div>
                </div>
            )}

            {section === 'checks' && (
                <div className="mon-panel mon-panel--flush">
                    <div className="mon-panel__header">
                        <div>
                            <h3>Check log</h3>
                            <span className="mon-panel-sub">
                                {rows.length} result{rows.length === 1 ? '' : 's'} · {frozen ? 'frozen' : 'live'}
                            </span>
                        </div>
                        <div className="mon-panel__actions">
                            {frozen && newSinceFreeze > 0 && (
                                <Pill kind="cyan">{newSinceFreeze} new</Pill>
                            )}
                            <SortMenu columns={checkColumns} sorts={sorts} onChange={setSorts} />
                            <ColumnsMenu
                                columns={checkColumns}
                                hiddenKeys={hiddenKeys}
                                onToggle={toggleColumn}
                                onShowAll={showAllColumns}
                            />
                            <Button variant="outline" size="sm" onClick={() => setFrozen(frozen ? null : checks)}>
                                {frozen ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Hold</>}
                            </Button>
                        </div>
                    </div>
                    <DataTable
                        tableClassName="sk-dtable monitor-checks-table"
                        data={rows}
                        keyField="id"
                        sorts={sorts}
                        onSortsChange={setSorts}
                        hiddenKeys={hiddenKeys}
                        rowClassName={(c) => (c.status === 'up' ? undefined : 'is-bad')}
                        emptyState={(
                            <EmptyState
                                icon={Activity}
                                title="No checks in this window yet."
                            />
                        )}
                        columns={checkColumns}
                        footer={<DataTableFooter shown={rows.length} total={rows.length} noun="check" />}
                    />
                </div>
            )}

            {section === 'config' && (
                <div className="mon-grid-2">
                    <div className="mon-panel">
                        <div className="mon-panel__header"><div><h3>Check</h3></div></div>
                        <dl className="mon-inforows">
                            <div><dt>Type</dt><dd>{monitor.check_type}</dd></div>
                            <div><dt>Target</dt><dd>{monitor.check_target || 'bound site'}</dd></div>
                            <div><dt>Interval</dt><dd>{monitor.check_interval}s</dd></div>
                            <div><dt>Timeout</dt><dd>{monitor.check_timeout}s</dd></div>
                            {isHttpish && <div><dt>Method</dt><dd>{monitor.check_method}</dd></div>}
                            {isHttpish && <div><dt>Expected</dt><dd>{monitor.expected_status}</dd></div>}
                            {monitor.check_type === 'keyword' && (
                                <div><dt>Keyword</dt><dd>{monitor.keyword || '—'}</dd></div>
                            )}
                            {isHttpish && (
                                <div><dt>Follow redirects</dt><dd>{monitor.follow_redirects ? 'yes' : 'no'}</dd></div>
                            )}
                            {isHttpish && <div><dt>Verify TLS</dt><dd>{monitor.verify_tls ? 'yes' : 'no'}</dd></div>}
                        </dl>
                    </div>

                    <div className="mon-panel">
                        <div className="mon-panel__header">
                            <div>
                                <h3>Alerting</h3>
                                <span className="mon-panel-sub">Delivery is configured in Settings → Notifications</span>
                            </div>
                        </div>
                        <dl className="mon-inforows">
                            <div>
                                <dt>Open an incident after</dt>
                                <dd>{(monitor.retries ?? 0) + 1} failed check{(monitor.retries ?? 0) + 1 === 1 ? '' : 's'}</dd>
                            </div>
                            <div><dt>Current failure streak</dt><dd>{monitor.consecutive_failures ?? 0}</dd></div>
                            <div>
                                <dt>Published on a status page</dt>
                                <dd>{monitor.page_id ? 'yes' : 'no'}</dd>
                            </div>
                        </dl>
                        <div className="mon-panel__footer">
                            <Button variant="ghost" size="sm" className="mon-danger" onClick={onDelete}>
                                <Trash2 size={14} /> Delete monitor
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </PageLayout>
    );
}
