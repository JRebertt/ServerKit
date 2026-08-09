// Jobs — admin view over the unified job system (job orchestration, "Phase 9").
//
// A tab in the Monitoring group now, not a top-level page: it is the same class
// of thing as Events, and the two read as rival pages while one sat in the
// sidebar and the other inside the group. The group's shared PageTopbar carries
// SearchField + FilterDrawer (status/kind) + Refresh; Activity/Scheduled is an
// in-page SegControl rather than its own tab strip, because the group's bar
// already owns the tab row and a nav under a nav reads as two headers.
//
// Activity shows clickable compact KPIs, a DataTable of runs, and server-side
// pagination over a job store that can hold six figures of scheduler-tick rows.
// Wired to the real ApiService job methods (see frontend/src/services/api/jobs.js).
import { useState, useEffect, useCallback, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ListChecks, RefreshCw, RotateCcw, XCircle, Play, Clock } from 'lucide-react';
import api from '../services/api';
import {
    MetricCard, KpiBand, Pill, DataTable, DataTableFooter, SegControl,
    SearchField, FilterDrawer, FilterButton, ViewMenu, countActiveFilters,
} from '@/components/ds';
import { Button } from '@/components/ui/button';
import EmptyState from '../components/EmptyState';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { useTableViews } from '@/hooks/useTableViews';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { timeAgo } from '../utils/timeAgo';

const titleCase = (value = '') => value.charAt(0).toUpperCase() + value.slice(1);

const STATUSES = ['all', 'queued', 'running', 'succeeded', 'failed', 'cancelled'];
const PAGE_SIZE = 50;
const POLL_MS = 5000;

// Built-in saved views. State shape: { filters, sorts, hiddenKeys } — `filters`
// is the FilterDrawer's value (status/kind, '' = all), `sorts` use real column
// keys. A Scheduled/Activity view is NOT expressible here: that switch lives in
// the URL-driven SegControl, and the drawer's kind options come from the API.
const BUILTIN_VIEWS = [
    { name: 'Failed', state: { filters: { status: 'failed', kind: '' } } },
    { name: 'Newest first', state: { sorts: [{ key: 'when', direction: 'desc' }] } },
];

// Map a job status to a DS Pill colour.
const STATUS_KIND = {
    queued: 'gray',
    pending: 'gray',
    scheduled: 'gray',
    running: 'cyan',
    succeeded: 'green',
    success: 'green',
    completed: 'green',
    failed: 'red',
    error: 'red',
    cancelled: 'amber',
    canceled: 'amber',
};

function statusKind(status) {
    return STATUS_KIND[String(status || '').toLowerCase()] || 'gray';
}

function ownerLabel(job) {
    if (!job.owner_type) return '—';
    return `${job.owner_type}${job.owner_id ? ` #${job.owner_id}` : ''}`;
}

function progressLabel(job) {
    if (typeof job.progress === 'number') return `${Math.round(job.progress)}%`;
    if (job.completed_units != null && job.total_units != null) {
        return `${job.completed_units}/${job.total_units}`;
    }
    return '—';
}

const isRunning = (s) => ['running', 'queued', 'pending', 'scheduled'].includes(String(s || '').toLowerCase());
const canRetry = (s) => ['failed', 'error', 'cancelled', 'canceled'].includes(String(s || '').toLowerCase());

export default function Jobs() {
    const { isAdmin } = useAuth();
    const toast = useToast();
    const location = useLocation();
    const navigate = useNavigate();
    // The view still lives in the URL (so a link to the scheduled list keeps
    // working) — only the control that switches it moved into the page.
    const scheduledView = location.pathname.endsWith('/scheduled');
    const [jobs, setJobs] = useState([]);
    const [total, setTotal] = useState(0);
    const [stats, setStats] = useState(null);
    const [scheduled, setScheduled] = useState([]);
    // Advanced filters live in the shared FilterDrawer (status + kind, single-
    // select; '' = all). Search is a separate debounced term.
    const [filters, setFilters] = useState({ status: '', kind: '' });
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [kinds, setKinds] = useState([]);
    const [q, setQ] = useState('');
    const [page, setPage] = useState(0);
    const [loading, setLoading] = useState(true);
    const pollRef = useRef(null);

    // Table sort + column visibility, controlled so saved views can drive
    // them — same localStorage keys the DataTables used when uncontrolled.
    const { sorts: activitySorts, setSorts: setActivitySorts } = useTableSort({
        storageKey: 'serverkit-table-jobs-activity-sort',
    });
    const { hiddenKeys: activityHidden, setHiddenKeys: setActivityHidden } = useColumnVisibility({
        storageKey: 'serverkit-table-jobs-activity-cols',
    });
    const { sorts: schedSorts, setSorts: setSchedSorts } = useTableSort({
        storageKey: 'serverkit-table-jobs-scheduled-sort',
    });
    const { hiddenKeys: schedHidden } = useColumnVisibility({
        storageKey: 'serverkit-table-jobs-scheduled-cols',
    });

    // Saved views: capture the FilterDrawer value plus the activity table's
    // sort/column state — never the server-side page/offset.
    const captureViewState = useCallback(() => ({
        filters,
        sorts: activitySorts,
        hiddenKeys: activityHidden,
    }), [filters, activitySorts, activityHidden]);
    const applyViewState = useCallback((state) => {
        if (state.filters !== undefined) {
            setFilters({ status: '', kind: '', ...state.filters });
            setPage(0);
        }
        if (Array.isArray(state.sorts)) setActivitySorts(state.sorts);
        if (Array.isArray(state.hiddenKeys)) setActivityHidden(state.hiddenKeys);
    }, [setActivitySorts, setActivityHidden]);
    const tableViews = useTableViews({
        page: 'jobs',
        builtinViews: BUILTIN_VIEWS,
        capture: captureViewState,
        apply: applyViewState,
    });
    // Stable primitive for the topbar publish deps: re-publish the ViewMenu
    // node when the user's views or the active view change.
    const activeViewKey = tableViews.activeView
        ? `${tableViews.activeView.builtin ? 'builtin' : 'user'}:${tableViews.activeView.name}`
        : '';

    const load = useCallback(async () => {
        try {
            const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
            if (filters.status) params.status = filters.status;
            if (filters.kind) params.kind = filters.kind;
            if (q) params.q = q;
            const [jobsRes, statsRes, schedRes] = await Promise.all([
                api.getJobs(params),
                api.getJobStats().catch(() => null),
                api.getScheduledJobs().catch(() => null),
            ]);
            setJobs(jobsRes?.jobs || []);
            setTotal(jobsRes?.total ?? (jobsRes?.jobs?.length || 0));
            setStats(statsRes?.stats || statsRes || null);
            setScheduled(schedRes?.scheduled || schedRes?.jobs || schedRes || []);
        } catch {
            // Keep the last good state on screen rather than blanking the page.
        } finally {
            setLoading(false);
        }
    }, [filters, q, page]);

    useEffect(() => {
        if (!isAdmin) return undefined;
        api.getJobKinds()
            .then((res) => setKinds(res?.kinds || res || []))
            .catch(() => { /* filter just won't populate */ });
        return undefined;
    }, [isAdmin]);

    useEffect(() => {
        if (!isAdmin) return undefined;
        load();
        pollRef.current = setInterval(load, POLL_MS);
        return () => clearInterval(pollRef.current);
    }, [isAdmin, load]);

    // KPI tiles are quick status filters; the drawer owns the full set.
    const setStatusQuick = (value) => { setFilters((f) => ({ ...f, status: value })); setPage(0); };
    const onFiltersChange = (next) => { setFilters(next); setPage(0); };
    const onSearch = (value) => { setQ(value.trim()); setPage(0); };
    const resetFilters = () => { setFilters({ status: '', kind: '' }); setQ(''); setPage(0); };
    const activeFilterCount = countActiveFilters(filters);

    // Search + advanced-filter trigger + Refresh sit in the shared page top bar
    // (the Marketplace/Domains pattern). Search/filters only apply to the
    // Activity tab; the Scheduled tab just gets Refresh.
    useTopbarActions(() => {
        if (!isAdmin) return null;
        return (
            <>
                {!scheduledView && (
                    <>
                        <ViewMenu views={tableViews} />
                        <SearchField value={q} onSearch={onSearch} placeholder="Search by kind or owner…" />
                        <FilterButton count={activeFilterCount} onClick={() => setFiltersOpen(true)} />
                    </>
                )}
                <Button variant="outline" size="sm" onClick={load}>
                    <RefreshCw size={14} /> Refresh
                </Button>
            </>
        );
    }, [isAdmin, scheduledView, q, activeFilterCount, load, tableViews.userViews, activeViewKey]);

    const onRetry = async (id) => {
        try { await api.retryJob(id); toast.success('Job re-queued'); load(); }
        catch { toast.error('Retry failed'); }
    };
    const onCancel = async (id) => {
        try { await api.cancelJob(id); toast.success('Job cancelled'); load(); }
        catch { toast.error('Cancel failed'); }
    };
    const onRunScheduled = async (id) => {
        try { await api.runScheduledJob(id); toast.success('Scheduled job triggered'); load(); }
        catch { toast.error('Trigger failed'); }
    };
    const onToggleScheduled = async (id, enabled) => {
        try { await api.setScheduledJobEnabled(id, enabled); load(); }
        catch { toast.error('Update failed'); }
    };

    if (!isAdmin) {
        return (
            <div className="sk-tabgroup__inner jobs-page">
                <div className="sk-jobs"><EmptyState title="Admins only." /></div>
            </div>
        );
    }

    const byStatus = stats?.by_status || {};
    const hasFilters = Boolean(filters.status || filters.kind || q);
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    const kindOptions = kinds
        .map((k) => (typeof k === 'string' ? k : k.kind || k.name))
        .filter(Boolean);

    const filterGroups = [
        {
            key: 'status',
            label: 'Status',
            type: 'single',
            options: STATUSES.filter((s) => s !== 'all').map((s) => ({ value: s, label: titleCase(s) })),
        },
        {
            key: 'kind',
            label: 'Kind',
            type: 'single',
            options: kindOptions.map((k) => ({ value: k, label: k })),
        },
    ];

    const jobColumns = [
        { key: 'status', header: 'Status', sortable: true, render: (j) => <Pill kind={statusKind(j.status)}>{j.status}</Pill> },
        { key: 'kind', header: 'Kind', sortable: true, cellClassName: 'sk-jobs__kind', render: (j) => j.kind || '—' },
        { key: 'owner', header: 'Owner', sortable: true, sortValue: (j) => j.owner_type || null, cellClassName: 'sk-jobs__owner', render: ownerLabel },
        {
            key: 'progress',
            header: 'Progress',
            render: (j) => (
                <>
                    {progressLabel(j)}
                    {j.error_message && (
                        <div className="sk-jobs__error" title={j.error_message}>{j.error_message}</div>
                    )}
                </>
            ),
        },
        {
            key: 'when',
            header: 'When',
            sortable: true,
            sortValue: (j) => {
                const stamp = j.created_at || j.updated_at;
                return stamp ? new Date(stamp).getTime() : null;
            },
            cellClassName: 'sk-jobs__when',
            render: (j) => timeAgo(j.created_at || j.updated_at),
        },
        {
            key: 'actions',
            header: '',
            className: 'sk-jobs__actions-col',
            cellClassName: 'sk-jobs__actions-cell',
            render: (j) => (
                <div className="sk-jobs__actions">
                    {isRunning(j.status) && (
                        <Button variant="ghost" size="sm" onClick={() => onCancel(j.id)}>
                            <XCircle size={14} /> Cancel
                        </Button>
                    )}
                    {canRetry(j.status) && (
                        <Button variant="ghost" size="sm" onClick={() => onRetry(j.id)}>
                            <RotateCcw size={14} /> Retry
                        </Button>
                    )}
                </div>
            ),
        },
    ];

    const scheduledColumns = [
        { key: 'name', header: 'Name', sortable: true, sortValue: (s) => s.name || s.kind || null, render: (s) => s.name || s.kind || `#${s.id}` },
        { key: 'kind', header: 'Kind', sortable: true, cellClassName: 'sk-jobs__kind', render: (s) => s.kind || '—' },
        { key: 'schedule', header: 'Schedule', sortable: true, sortValue: (s) => s.schedule || s.cron || null, cellClassName: 'sk-jobs__owner', render: (s) => s.schedule || s.cron || (s.interval_seconds ? `every ${s.interval_seconds}s` : '—') },
        { key: 'next', header: 'Next run', cellClassName: 'sk-jobs__when', render: (s) => (s.next_run_at ? timeAgo(s.next_run_at) : '—') },
        { key: 'enabled', header: 'Enabled', render: (s) => <Pill kind={s.enabled ? 'green' : 'gray'}>{s.enabled ? 'On' : 'Off'}</Pill> },
        {
            key: 'actions',
            header: '',
            className: 'sk-jobs__actions-col',
            cellClassName: 'sk-jobs__actions-cell',
            render: (s) => (
                <div className="sk-jobs__actions">
                    <Button variant="ghost" size="sm" onClick={() => onRunScheduled(s.id)}>
                        <Play size={14} /> Run now
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => onToggleScheduled(s.id, !s.enabled)}>
                        {s.enabled ? 'Disable' : 'Enable'}
                    </Button>
                </div>
            ),
        },
    ];

    return (
        <div className="sk-tabgroup__inner jobs-page">
            <div className="sk-jobs">
                <div className="sk-jobs__viewswitch">
                    <SegControl
                        value={scheduledView ? 'scheduled' : 'activity'}
                        onChange={(value) => navigate(
                            value === 'scheduled' ? '/monitoring/jobs/scheduled' : '/monitoring/jobs',
                        )}
                        options={[
                            { value: 'activity', label: 'Activity', icon: <ListChecks size={14} /> },
                            { value: 'scheduled', label: 'Scheduled', icon: <Clock size={14} /> },
                        ]}
                    />
                </div>

                {scheduledView ? (
                    <DataTable
                        columns={scheduledColumns}
                        data={scheduled}
                        keyField="id"
                        sorts={schedSorts}
                        onSortsChange={setSchedSorts}
                        hiddenKeys={schedHidden}
                        loading={loading && scheduled.length === 0}
                        emptyTitle="No scheduled jobs yet."
                        emptyMessage=""
                    />
                ) : (
                    <>
                        <KpiBand>
                            <MetricCard label="Total" value={stats?.total ?? total ?? 0} tone="accent" compact
                                onClick={() => setStatusQuick('')} />
                            <MetricCard label="Running" value={byStatus.running ?? 0} tone="cyan" compact
                                onClick={() => setStatusQuick('running')} />
                            <MetricCard label="Queued" value={byStatus.pending ?? byStatus.queued ?? 0} tone="amber" compact
                                onClick={() => setStatusQuick('queued')} />
                            <MetricCard label="Failed" value={byStatus.failed ?? 0} tone="red" compact
                                onClick={() => setStatusQuick('failed')} />
                        </KpiBand>

                        {hasFilters && (
                            <div className="sk-jobs__resultbar">
                                <Button variant="ghost" size="sm" onClick={resetFilters}>
                                    Reset filters
                                </Button>
                            </div>
                        )}

                        <DataTable
                            columns={jobColumns}
                            data={jobs}
                            keyField="id"
                            sorts={activitySorts}
                            onSortsChange={setActivitySorts}
                            hiddenKeys={activityHidden}
                            loading={loading && jobs.length === 0}
                            footer={(
                                <DataTableFooter
                                    shown={jobs.length}
                                    total={total}
                                    noun="job"
                                    page={page + 1}
                                    totalPages={totalPages}
                                    onPageChange={(next) => setPage(next - 1)}
                                />
                            )}
                            emptyTitle={hasFilters ? 'No jobs match these filters.' : 'No jobs have run yet.'}
                            emptyMessage=""
                        />
                    </>
                )}
            </div>

            <FilterDrawer
                open={filtersOpen}
                onOpenChange={setFiltersOpen}
                groups={filterGroups}
                value={filters}
                onChange={onFiltersChange}
                title="Filter jobs"
            />
        </div>
    );
}
