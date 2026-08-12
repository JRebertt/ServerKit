// Monitors — the synthetic-check list (watch a URL, a service, a WordPress site).
//
// Tab-group page (the Domains/Cron/Jobs pattern): the group's shared PageTopbar
// carries SearchField + FilterDrawer + Refresh + "Add monitor" via
// useTopbarActions, so there is no second header inside the page. Clickable KPI
// tiles are the quick status filter; the drawer owns type + status together.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Activity, AlertTriangle, ChevronRight, Globe, Pause, Play, Plus, Radar,
    RefreshCw, ShieldAlert, Zap,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import {
    DataTable, DataTableFooter, Drawer, FilterButton, FilterDrawer, KpiBand,
    MetricCard, Pill, SearchField, Sparkline, ViewMenu, countActiveFilters,
} from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { useTableViews } from '@/hooks/useTableViews';
import useFocusParam from '@/hooks/useFocusParam';
import { CHECK_TYPES, MONITOR_STATUS, monitorStateOf } from '../components/monitoring/monitorShared';

const POLL_MS = 15000;

const emptyForm = {
    name: '',
    check_type: 'http',
    check_target: '',
    check_interval: 60,
    check_timeout: 10,
    check_method: 'GET',
    expected_status: '200-299',
    keyword: '',
    follow_redirects: true,
    verify_tls: true,
    retries: 2,
};

const TARGET_PLACEHOLDER = {
    http: 'https://example.com/health',
    keyword: 'https://example.com/',
    tcp: 'db.example.com:5432',
    dns: 'example.com',
    smtp: 'mail.example.com:25',
    ping: 'example.com',
};

function relativeTime(iso) {
    if (!iso) return 'never';
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return '—';
    const seconds = Math.round((Date.now() - then) / 1000);
    if (seconds < 0) return 'in a moment';
    if (seconds < 5) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function countdown(iso) {
    if (!iso) return '—';
    const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
    if (Number.isNaN(seconds)) return '—';
    if (seconds <= 0) return 'due';
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m`;
}

function formatUptime(value) {
    if (value == null) return '—';
    return `${Number(value).toFixed(2)}%`;
}

// Built-in saved views. State shape: { search, filters, sorts, hiddenKeys } —
// `filters` values are the FilterDrawer's real group options (status values
// from MONITOR_STATUS), `sorts` use real column keys.
const BUILTIN_VIEWS = [
    { name: 'Down', state: { search: '', filters: { status: 'major_outage', type: '' }, sorts: [], hiddenKeys: [] } },
    { name: 'Degraded', state: { search: '', filters: { status: 'degraded', type: '' }, sorts: [], hiddenKeys: [] } },
    { name: 'Slowest', state: { search: '', filters: { status: '', type: '' }, sorts: [{ key: 'response', direction: 'desc' }], hiddenKeys: [] } },
    {
        // Least reliable over the month, slowest first among ties — the review
        // list, as opposed to "what is broken right now".
        name: 'Worst uptime (30d)',
        state: {
            search: '', filters: { status: '', type: '' }, hiddenKeys: ['next_check_at'],
            sorts: [{ key: 'uptime_30d', direction: 'asc' }, { key: 'response', direction: 'desc' }],
        },
    },
    {
        // Paused checks are silent by design; this is how you notice one has
        // been silent for longer than anybody intended.
        name: 'Paused — still silenced',
        state: {
            search: '', filters: { status: 'paused', type: '' },
            hiddenKeys: ['last_check_at', 'next_check_at'],
            sorts: [{ key: 'name', direction: 'asc' }],
        },
    },
    {
        name: 'Slow web checks',
        state: {
            search: '', filters: { status: '', type: 'http' }, hiddenKeys: ['check_type'],
            sorts: [{ key: 'response', direction: 'desc' }],
        },
    },
    {
        name: 'In maintenance',
        state: {
            search: '', filters: { status: 'maintenance', type: '' }, hiddenKeys: ['next_check_at'],
            sorts: [{ key: 'name', direction: 'asc' }],
        },
    },
];

export default function Monitors() {
    const navigate = useNavigate();
    const toast = useToast();

    const [monitors, setMonitors] = useState([]);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [q, setQ] = useState('');
    const [filters, setFilters] = useState({ status: '', type: '' });
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [formOpen, setFormOpen] = useState(false);
    const [form, setForm] = useState(emptyForm);
    const [saving, setSaving] = useState(false);
    // Bumps once a second so "next check in 42s" actually counts down between
    // polls instead of sitting still for 15 seconds at a time.
    const [, setTick] = useState(0);
    const pollRef = useRef(null);

    const load = useCallback(async () => {
        try {
            const [listRes, statsRes] = await Promise.all([
                api.getMonitors({ q: q || undefined, status: filters.status || undefined, type: filters.type || undefined }),
                api.getMonitorStats().catch(() => null),
            ]);
            setMonitors(listRes?.monitors || []);
            setStats(statsRes?.stats || null);
        } catch {
            // Keep the last good list on screen rather than blanking the page.
        } finally {
            setLoading(false);
        }
    }, [q, filters.status, filters.type]);

    useEffect(() => {
        load();
        pollRef.current = setInterval(load, POLL_MS);
        return () => clearInterval(pollRef.current);
    }, [load]);

    useEffect(() => {
        const timer = setInterval(() => setTick((n) => n + 1), 1000);
        return () => clearInterval(timer);
    }, []);

    const activeFilterCount = countActiveFilters(filters);
    const setStatusQuick = (value) => setFilters((f) => ({ ...f, status: f.status === value ? '' : value }));

    // Table sort + column visibility, controlled so saved views can drive them.
    // Same storage keys DataTable used internally, so existing choices survive.
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-monitors-sort' });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({ storageKey: 'serverkit-table-monitors-cols' });

    // Saved views: capture/apply adapt the hook to this page's table state.
    const captureViewState = useCallback(() => ({
        search: q, filters, sorts, hiddenKeys,
    }), [q, filters, sorts, hiddenKeys]);
    const applyViewState = useCallback((state) => {
        if (state.search !== undefined) setQ(state.search);
        if (state.filters !== undefined) setFilters((f) => ({ ...f, ...state.filters }));
        if (Array.isArray(state.sorts)) setSorts(state.sorts);
        if (Array.isArray(state.hiddenKeys)) setHiddenKeys(state.hiddenKeys);
    }, [setSorts, setHiddenKeys]);
    const tableViews = useTableViews({
        page: 'monitors',
        builtinViews: BUILTIN_VIEWS,
        capture: captureViewState,
        apply: applyViewState,
    });
    // Stable dep for the topbar publish below — the views object itself is
    // rebuilt every render, so depending on it would re-publish in a loop.
    const activeViewKey = tableViews.activeView
        ? `${tableViews.activeView.builtin ? 'builtin' : 'user'}:${tableViews.activeView.id ?? tableViews.activeView.name}`
        : null;

    const openCreate = () => { setForm(emptyForm); setFormOpen(true); };
    // Quick-create deep link: /monitoring/monitors?focus=create:monitor opens the form.
    useFocusParam('create', openCreate);

    useTopbarActions(() => (
        <>
            <SearchField value={q} onSearch={(value) => setQ(value.trim())} placeholder="Search monitors or targets…" />
            <ViewMenu views={tableViews} />
            <FilterButton count={activeFilterCount} onClick={() => setFiltersOpen(true)} />
            <Button variant="outline" size="sm" onClick={load}>
                <RefreshCw size={14} /> Refresh
            </Button>
            <Button size="sm" onClick={openCreate}>
                <Plus size={14} /> Add monitor
            </Button>
        </>
    ), [q, activeFilterCount, load, captureViewState, tableViews.userViews, activeViewKey]);

    const onSave = async (e) => {
        e.preventDefault();
        setSaving(true);
        try {
            const payload = { ...form };
            if (payload.check_type !== 'keyword') delete payload.keyword;
            if (!['http', 'keyword'].includes(payload.check_type)) {
                delete payload.check_method;
                delete payload.expected_status;
                delete payload.follow_redirects;
            }
            await api.createMonitor(payload);
            toast.success(`Monitoring ${form.name}`);
            setFormOpen(false);
            load();
        } catch (err) {
            toast.error(err.message || 'Could not create the monitor');
        } finally {
            setSaving(false);
        }
    };

    const onTogglePause = async (monitor) => {
        try {
            await api.setMonitorPaused(monitor.id, !monitor.is_paused);
            toast.success(monitor.is_paused ? `Resumed ${monitor.name}` : `Paused ${monitor.name}`);
            load();
        } catch (err) {
            toast.error(err.message || 'Could not change the monitor');
        }
    };

    const onCheckNow = async (monitor) => {
        try {
            const res = await api.runMonitorCheck(monitor.id);
            const check = res?.check;
            if (check?.status === 'up') toast.success(`${monitor.name}: up in ${check.response_time ?? '—'} ms`);
            else toast.warning(`${monitor.name}: ${check?.status || 'failed'}${check?.error ? ` — ${check.error}` : ''}`);
            load();
        } catch (err) {
            toast.error(err.message || 'Check failed');
        }
    };

    const filterGroups = useMemo(() => ([
        {
            key: 'status',
            label: 'Status',
            type: 'single',
            options: MONITOR_STATUS.map((s) => ({ value: s.value, label: s.label })),
        },
        {
            key: 'type',
            label: 'Check type',
            type: 'single',
            options: CHECK_TYPES.map((t) => ({ value: t.value, label: t.label })),
        },
    ]), []);

    const columns = [
        {
            key: 'name',
            header: 'Monitor',
            sortable: true,
            hideable: false,
            sortValue: (m) => m.name,
            render: (m) => (
                <div className="sk-cell-name">
                    <span className="mon-ico"><Globe size={15} /></span>
                    <div className="mon-namecell">
                        <div className="mon-namecell__name">{m.name}</div>
                        <div className="mon-namecell__target">{m.check_target || 'bound site'}</div>
                    </div>
                </div>
            ),
        },
        {
            key: 'check_type',
            header: 'Type',
            sortable: true,
            render: (m) => <span className="mon-type">{m.check_type}</span>,
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (m) => monitorStateOf(m).label,
            render: (m) => {
                const state = monitorStateOf(m);
                return <Pill kind={state.tone}>{state.label}</Pill>;
            },
        },
        {
            key: 'response',
            header: 'Response',
            sortable: true,
            sortValue: (m) => m.last_response_time,
            render: (m) => {
                if (m.last_response_time == null) return <span className="mon-muted">—</span>;
                const slow = m.last_response_time > 300;
                return (
                    <div className="mon-response">
                        {m.spark?.length > 1 && (
                            <Sparkline
                                data={m.spark}
                                width={44}
                                height={18}
                                color={slow ? 'var(--amber)' : 'var(--green)'}
                            />
                        )}
                        <span className={slow ? 'mon-response__ms is-slow' : 'mon-response__ms'}>
                            {m.last_response_time} ms
                        </span>
                    </div>
                );
            },
        },
        {
            key: 'uptime_30d',
            header: 'Uptime (30d)',
            sortable: true,
            render: (m) => <span className="mon-uptime">{formatUptime(m.uptime_30d)}</span>,
        },
        {
            key: 'last_check_at',
            header: 'Last check',
            sortable: true,
            render: (m) => (
                <span className="mon-muted">{m.is_paused ? 'paused' : relativeTime(m.last_check_at)}</span>
            ),
        },
        {
            key: 'next_check_at',
            header: 'Next check',
            render: (m) => <span className="mon-muted">{m.is_paused ? '—' : countdown(m.next_check_at)}</span>,
        },
        {
            key: 'actions',
            header: '',
            className: 'mon-actions-col',
            cellClassName: 'mon-actions-cell',
            hideable: false,
            render: (m) => (
                <div className="mon-actions" onClick={(e) => e.stopPropagation()}>
                    <Button variant="ghost" size="sm" onClick={() => onCheckNow(m)} title="Check now">
                        <RefreshCw size={14} />
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onTogglePause(m)}
                        title={m.is_paused ? 'Resume' : 'Pause'}
                    >
                        {m.is_paused ? <Play size={14} /> : <Pause size={14} />}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => navigate(`/monitoring/monitors/${m.id}`)} title="Open">
                        <ChevronRight size={14} />
                    </Button>
                </div>
            ),
        },
    ];

    const hasFilters = Boolean(q || filters.status || filters.type);
    const isHttpish = ['http', 'keyword'].includes(form.check_type);

    return (
        <div className="sk-tabgroup__inner monitors-page">
            <KpiBand>
                <MetricCard
                    label="Operational" value={stats?.operational ?? 0} tone="green" compact
                    icon={<Activity size={17} />}
                    onClick={() => setStatusQuick('operational')}
                />
                <MetricCard
                    label="Degraded" value={stats?.degraded ?? 0} tone="amber" compact
                    icon={<AlertTriangle size={17} />}
                    onClick={() => setStatusQuick('degraded')}
                />
                <MetricCard
                    label="Down" value={stats?.down ?? 0} tone="red" compact
                    icon={<ShieldAlert size={17} />}
                    onClick={() => setStatusQuick('major_outage')}
                />
                <MetricCard
                    label="Uptime (30d)"
                    value={stats?.overall_uptime_30d != null ? `${stats.overall_uptime_30d}%` : '—'}
                    tone="accent" icon={<Zap size={17} />}
                />
            </KpiBand>

            {loading && monitors.length === 0 ? (
                <EmptyState loading loadingVariant="table" title="Loading monitors" />
            ) : monitors.length === 0 ? (
                <EmptyState
                    icon={Radar}
                    title={hasFilters ? 'No monitors match' : 'Nothing is being watched yet'}
                    description={hasFilters
                        ? 'Try a different search or clear the filters.'
                        : 'Add a monitor to watch a website, an API endpoint, a database port or a WordPress site — and get an incident when it stops answering.'}
                    action={hasFilters
                        ? <Button variant="outline" onClick={() => { setQ(''); setFilters({ status: '', type: '' }); }}>Clear filters</Button>
                        : <Button onClick={openCreate}><Plus size={16} /> Add monitor</Button>}
                />
            ) : (
                <div className="mon-card">
                    <DataTable
                        tableClassName="sk-dtable monitors-table"
                        storageKey="serverkit-table-monitors"
                        data={monitors}
                        keyField="id"
                        columns={columns}
                        sorts={sorts}
                        onSortsChange={setSorts}
                        hiddenKeys={hiddenKeys}
                        onRowClick={(m) => navigate(`/monitoring/monitors/${m.id}`)}
                        rowClassName={(m) => (m.is_paused ? 'is-disabled' : undefined)}
                        footer={<DataTableFooter shown={monitors.length} total={monitors.length} noun="monitor" />}
                    />
                </div>
            )}

            <FilterDrawer
                open={filtersOpen}
                onOpenChange={setFiltersOpen}
                groups={filterGroups}
                value={filters}
                onChange={setFilters}
                title="Filter monitors"
            />

            <Drawer
                open={formOpen}
                onOpenChange={setFormOpen}
                title="Add monitor"
                subtitle="Probe a URL, host or port on a schedule"
                icon={<Radar size={18} />}
            >
                <form className="mon-form" onSubmit={onSave}>
                    <div className="form-group">
                        <Label htmlFor="mon-name">Name</Label>
                        <Input
                            id="mon-name" required value={form.name}
                            onChange={(e) => setForm({ ...form, name: e.target.value })}
                            placeholder="Marketing site"
                        />
                    </div>

                    <div className="form-group">
                        <Label htmlFor="mon-type">Check type</Label>
                        <select
                            id="mon-type" className="mon-select" value={form.check_type}
                            onChange={(e) => setForm({ ...form, check_type: e.target.value })}
                        >
                            {CHECK_TYPES.map((t) => (
                                <option key={t.value} value={t.value}>{t.label} — {t.hint}</option>
                            ))}
                        </select>
                    </div>

                    <div className="form-group">
                        <Label htmlFor="mon-target">Target</Label>
                        <Input
                            id="mon-target" required value={form.check_target}
                            onChange={(e) => setForm({ ...form, check_target: e.target.value })}
                            placeholder={TARGET_PLACEHOLDER[form.check_type]}
                        />
                    </div>

                    {form.check_type === 'keyword' && (
                        <div className="form-group">
                            <Label htmlFor="mon-keyword">Keyword</Label>
                            <Input
                                id="mon-keyword" required value={form.keyword}
                                onChange={(e) => setForm({ ...form, keyword: e.target.value })}
                                placeholder="Proceed to checkout"
                            />
                            <span className="form-help">
                                A 200 response without this text counts as an outage.
                            </span>
                        </div>
                    )}

                    <div className="mon-form__row">
                        <div className="form-group">
                            <Label htmlFor="mon-interval">Interval (s)</Label>
                            <Input
                                id="mon-interval" type="number" min="30" max="86400" value={form.check_interval}
                                onChange={(e) => setForm({ ...form, check_interval: Number(e.target.value) })}
                            />
                        </div>
                        <div className="form-group">
                            <Label htmlFor="mon-timeout">Timeout (s)</Label>
                            <Input
                                id="mon-timeout" type="number" min="1" max="120" value={form.check_timeout}
                                onChange={(e) => setForm({ ...form, check_timeout: Number(e.target.value) })}
                            />
                        </div>
                        <div className="form-group">
                            <Label htmlFor="mon-retries">Retries</Label>
                            <Input
                                id="mon-retries" type="number" min="0" max="10" value={form.retries}
                                onChange={(e) => setForm({ ...form, retries: Number(e.target.value) })}
                            />
                            <span className="form-help">Failed checks tolerated before an incident opens.</span>
                        </div>
                    </div>

                    {isHttpish && (
                        <>
                            <div className="mon-form__row">
                                <div className="form-group">
                                    <Label htmlFor="mon-method">Method</Label>
                                    <select
                                        id="mon-method" className="mon-select" value={form.check_method}
                                        onChange={(e) => setForm({ ...form, check_method: e.target.value })}
                                    >
                                        {['GET', 'HEAD', 'POST', 'PUT', 'OPTIONS'].map((m) => (
                                            <option key={m} value={m}>{m}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <Label htmlFor="mon-expected">Expected status</Label>
                                    <Input
                                        id="mon-expected" value={form.expected_status}
                                        onChange={(e) => setForm({ ...form, expected_status: e.target.value })}
                                        placeholder="200-299"
                                    />
                                </div>
                            </div>

                            <div className="mon-switch-row">
                                <div>
                                    <strong>Follow redirects</strong>
                                    <span>A 30x lands on its destination before grading.</span>
                                </div>
                                <Switch
                                    checked={form.follow_redirects}
                                    onCheckedChange={(v) => setForm({ ...form, follow_redirects: v })}
                                />
                            </div>
                            <div className="mon-switch-row">
                                <div>
                                    <strong>Verify TLS</strong>
                                    <span>Off for self-signed certificates on internal hosts.</span>
                                </div>
                                <Switch
                                    checked={form.verify_tls}
                                    onCheckedChange={(v) => setForm({ ...form, verify_tls: v })}
                                />
                            </div>
                        </>
                    )}

                    <div className="mon-form__actions">
                        <Button type="button" variant="ghost" onClick={() => setFormOpen(false)}>Cancel</Button>
                        <Button type="submit" disabled={saving}>
                            {saving ? 'Adding…' : 'Add monitor'}
                        </Button>
                    </div>
                </form>
            </Drawer>
        </div>
    );
}
