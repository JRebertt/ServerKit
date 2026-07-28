// Events — the system event stream (the "Events" tab of the Monitoring group).
//
// Rebuilt on the standard tab-group page pattern. What it used to do wrong:
//   - it rendered its own <PageTopbar> while nested inside <TabGroupLayout>,
//     so the page carried two stacked headers
//   - its KPI row was bespoke `telemetry-stat` divs instead of KpiBand +
//     MetricCard, so it matched nothing else in the panel
//   - filters were an inline collapsible panel instead of the shared topbar
//     SearchField + FilterDrawer that Domains / Cron / Jobs / Monitors use
//
// Every capability it had is kept: source / type / severity / resource / date
// filters, correlation drill-down, test-event emit, cleanup, and pagination.
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Activity, AlertTriangle, ChevronRight, Info, Loader2, RefreshCw, Trash2,
    XCircle,
} from 'lucide-react';
import api from '../services/api';
import {
    DataTable, Drawer, FilterButton, FilterDrawer, KpiBand, MetricCard, Pill,
    SearchField, countActiveFilters,
} from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';

const SEVERITY_ORDER = ['critical', 'error', 'warning', 'info', 'debug'];

// `tone` is a MetricCard tone (accent|green|cyan|amber|red|violet) and `pill` is
// a Pill kind (green|amber|red|cyan|violet|gray). They overlap but are not the
// same set — passing one token to both silently drops the Pill's background for
// values Pill doesn't know, which is what "accent" for info was doing.
const SEVERITY_CONFIG = {
    critical: { icon: XCircle, tone: 'red', pill: 'red', label: 'Critical' },
    error: { icon: XCircle, tone: 'red', pill: 'red', label: 'Error' },
    warning: { icon: AlertTriangle, tone: 'amber', pill: 'amber', label: 'Warning' },
    info: { icon: Info, tone: 'cyan', pill: 'cyan', label: 'Info' },
    debug: { icon: Activity, tone: 'violet', pill: 'gray', label: 'Debug' },
};

const PAGE_SIZE = 50;

const EMPTY_FILTERS = {
    source: '',
    event_type: '',
    severity: '',
    resource_type: '',
    resource_id: '',
    correlation_id: '',
    start_date: '',
    end_date: '',
};

export default function Telemetry() {
    const { isAdmin } = useAuth();
    const { showToast } = useToast();

    const [events, setEvents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [hasMore, setHasMore] = useState(false);
    const [page, setPage] = useState(1);
    const [stats, setStats] = useState(null);
    const [sources, setSources] = useState([]);
    const [eventTypes, setEventTypes] = useState([]);
    const [selectedEvent, setSelectedEvent] = useState(null);
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [filters, setFilters] = useState(EMPTY_FILTERS);
    const [q, setQ] = useState('');

    const loadStats = useCallback(async () => {
        try {
            setStats(await api.getTelemetryStats({ hours: 24 }));
        } catch {
            // stats are optional
        }
    }, []);

    const loadFilterOptions = useCallback(async () => {
        try {
            const [sourcesData, typesData] = await Promise.all([
                api.getTelemetrySources(),
                api.getTelemetryEventTypes({ source: filters.source || undefined }),
            ]);
            setSources(sourcesData.sources || []);
            setEventTypes(typesData.event_types || []);
        } catch {
            // filter options are optional
        }
    }, [filters.source]);

    const fetchEvents = useCallback(async (nextPage = 1, replace = true) => {
        setLoading(true);
        try {
            const params = { ...filters, q, per_page: PAGE_SIZE, page: nextPage };
            Object.keys(params).forEach((key) => {
                if (params[key] === '') delete params[key];
            });
            const data = await api.getTelemetryEvents(params);
            const fresh = data.events || [];
            setEvents((prev) => (replace ? fresh : [...prev, ...fresh]));
            setHasMore(fresh.length === PAGE_SIZE);
            setPage(nextPage);
        } catch (err) {
            showToast(`Failed to load telemetry: ${err.message}`, 'error');
            setHasMore(false);
        } finally {
            setLoading(false);
        }
    }, [filters, q, showToast]);

    useEffect(() => {
        loadStats();
        loadFilterOptions();
        fetchEvents(1, true);
    }, [loadStats, loadFilterOptions, fetchEvents]);

    const emitTestEvent = async () => {
        try {
            await api.emitTestTelemetryEvent({
                source: 'system',
                event_type: 'telemetry.test',
                message: 'Test event from UI',
                severity: 'info',
                payload: { from_ui: true },
            });
            showToast('Test event emitted', 'success');
            fetchEvents(1, true);
            loadStats();
        } catch (err) {
            showToast(`Failed to emit test event: ${err.message}`, 'error');
        }
    };

    const cleanupOldEvents = async () => {
        if (!window.confirm('Delete telemetry events older than 90 days? This cannot be undone.')) {
            return;
        }
        try {
            const data = await api.cleanupTelemetryEvents(90);
            showToast(`Deleted ${data.deleted} old events`, 'success');
            fetchEvents(1, true);
            loadStats();
        } catch (err) {
            showToast(`Cleanup failed: ${err.message}`, 'error');
        }
    };

    const activeFilterCount = countActiveFilters(filters);

    // Search + advanced filters + Refresh live in the group's shared top bar,
    // the way every other list page in the panel does it.
    useTopbarActions(() => (
        <>
            <SearchField value={q} onSearch={(value) => setQ(value.trim())} placeholder="Search messages…" />
            <FilterButton count={activeFilterCount} onClick={() => setFiltersOpen(true)} />
            {isAdmin && (
                <Button variant="outline" size="sm" onClick={emitTestEvent}>
                    <Activity size={14} /> Test event
                </Button>
            )}
            {isAdmin && (
                <Button variant="outline" size="sm" onClick={cleanupOldEvents}>
                    <Trash2 size={14} /> Cleanup
                </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => fetchEvents(1, true)} disabled={loading}>
                <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
            </Button>
        </>
    ), [q, activeFilterCount, isAdmin, loading, fetchEvents]);

    const setSeverityQuick = (severity) => {
        setFilters((f) => ({ ...f, severity: f.severity === severity ? '' : severity }));
    };

    const filterGroups = useMemo(() => ([
        {
            key: 'source',
            label: 'Source',
            type: 'single',
            options: sources.map((s) => ({ value: s, label: s })),
        },
        {
            key: 'event_type',
            label: 'Event type',
            type: 'single',
            options: eventTypes.map((t) => ({ value: t, label: t })),
        },
        {
            key: 'severity',
            label: 'Severity',
            type: 'single',
            options: SEVERITY_ORDER.map((s) => ({ value: s, label: SEVERITY_CONFIG[s].label })),
        },
    ]), [sources, eventTypes]);

    const columns = [
        {
            key: 'severity',
            header: 'Severity',
            render: (event) => {
                const config = SEVERITY_CONFIG[event.severity] || SEVERITY_CONFIG.info;
                return <Pill kind={config.pill}>{config.label}</Pill>;
            },
        },
        {
            key: 'message',
            header: 'Event',
            render: (event) => (
                <div className="telemetry-cell">
                    <div className="telemetry-cell__message">{event.message || event.event_type}</div>
                    <div className="telemetry-cell__meta">
                        <span className="telemetry-cell__source">{event.source}</span>
                        <span className="telemetry-cell__type">{event.event_type}</span>
                        {event.resource_type && (
                            <span className="telemetry-cell__badge">
                                {event.resource_type}:{event.resource_id}
                            </span>
                        )}
                        {event.actor_username && (
                            <span className="telemetry-cell__badge">by {event.actor_username}</span>
                        )}
                    </div>
                </div>
            ),
        },
        {
            key: 'correlation_id',
            header: 'Related',
            render: (event) => (event.correlation_id ? (
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                        e.stopPropagation();
                        setFilters((f) => ({ ...f, correlation_id: event.correlation_id }));
                    }}
                    title="Show every event in this trace"
                >
                    trace <ChevronRight size={12} />
                </Button>
            ) : <span className="telemetry-cell__muted">—</span>),
        },
        {
            key: 'timestamp',
            header: 'When',
            cellClassName: 'telemetry-cell__when',
            render: (event) => new Date(event.timestamp).toLocaleString(),
        },
    ];

    const hasFilters = Boolean(q || activeFilterCount);

    return (
        <div className="sk-tabgroup__inner telemetry-page">
            {/* Ordered by what an operator acts on. KpiBand keeps the first four
                up front; info/debug are counts you rarely chase, so they ride in
                the folded strip rather than pushing Total out of the row. */}
            <KpiBand>
                {['critical', 'error', 'warning'].map((severity) => {
                    const config = SEVERITY_CONFIG[severity];
                    const Icon = config.icon;
                    return (
                        <MetricCard
                            key={severity}
                            label={config.label}
                            value={stats?.by_severity?.[severity] || 0}
                            tone={config.tone}
                            compact
                            icon={<Icon size={17} />}
                            onClick={() => setSeverityQuick(severity)}
                        />
                    );
                })}
                <MetricCard
                    label="Total (24h)"
                    value={stats?.total || 0}
                    tone="accent"
                    compact
                    icon={<Activity size={17} />}
                />
                {['info', 'debug'].map((severity) => {
                    const config = SEVERITY_CONFIG[severity];
                    const Icon = config.icon;
                    return (
                        <MetricCard
                            key={severity}
                            secondary
                            label={config.label}
                            value={stats?.by_severity?.[severity] || 0}
                            tone={config.tone}
                            compact
                            icon={<Icon size={17} />}
                            onClick={() => setSeverityQuick(severity)}
                        />
                    );
                })}
            </KpiBand>

            {filters.correlation_id && (
                <div className="telemetry-trace">
                    <span>
                        Showing one trace: <code>{filters.correlation_id}</code>
                    </span>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setFilters((f) => ({ ...f, correlation_id: '' }))}
                    >
                        Clear
                    </Button>
                </div>
            )}

            {events.length === 0 && !loading ? (
                <EmptyState
                    icon={Info}
                    title={hasFilters ? 'No events match' : 'No events recorded yet'}
                    description={hasFilters
                        ? 'Try a different search or clear the filters.'
                        : 'System activity shows up here as it happens.'}
                    action={hasFilters
                        ? (
                            <Button variant="outline" onClick={() => { setFilters(EMPTY_FILTERS); setQ(''); }}>
                                Clear filters
                            </Button>
                        )
                        : undefined}
                />
            ) : (
                <>
                    <DataTable
                        tableClassName="sk-dtable telemetry-table"
                        sortable={false}
                        data={events}
                        keyField="id"
                        loading={loading && events.length === 0}
                        onRowClick={setSelectedEvent}
                        rowClassName={(event) => `is-${event.severity}`}
                        columns={columns}
                    />

                    {loading && events.length > 0 && (
                        <div className="telemetry-loading"><Loader2 size={20} className="spin" /></div>
                    )}

                    {hasMore && !loading && (
                        <div className="telemetry-more">
                            <Button variant="outline" onClick={() => fetchEvents(page + 1, false)}>
                                Load more
                            </Button>
                        </div>
                    )}
                </>
            )}

            <FilterDrawer
                open={filtersOpen}
                onOpenChange={setFiltersOpen}
                groups={filterGroups}
                value={filters}
                onChange={setFilters}
                onClear={() => setFilters(EMPTY_FILTERS)}
                activeCount={activeFilterCount}
                title="Filter events"
            >
                {/* Free-text and date bounds don't fit the option-list shape the
                    drawer's groups use, so they ride along as extra fields. */}
                <div className="form-group">
                    <Label htmlFor="tel-resource-type">Resource type</Label>
                    <Input
                        id="tel-resource-type"
                        value={filters.resource_type}
                        onChange={(e) => setFilters({ ...filters, resource_type: e.target.value })}
                        placeholder="application"
                    />
                </div>
                <div className="form-group">
                    <Label htmlFor="tel-resource-id">Resource ID</Label>
                    <Input
                        id="tel-resource-id"
                        value={filters.resource_id}
                        onChange={(e) => setFilters({ ...filters, resource_id: e.target.value })}
                    />
                </div>
                <div className="form-group">
                    <Label htmlFor="tel-start">From</Label>
                    <Input
                        id="tel-start"
                        type="datetime-local"
                        value={filters.start_date}
                        onChange={(e) => setFilters({ ...filters, start_date: e.target.value })}
                    />
                </div>
                <div className="form-group">
                    <Label htmlFor="tel-end">To</Label>
                    <Input
                        id="tel-end"
                        type="datetime-local"
                        value={filters.end_date}
                        onChange={(e) => setFilters({ ...filters, end_date: e.target.value })}
                    />
                </div>
            </FilterDrawer>

            <Drawer
                open={Boolean(selectedEvent)}
                onOpenChange={(open) => { if (!open) setSelectedEvent(null); }}
                title={selectedEvent?.message || selectedEvent?.event_type || 'Event'}
                subtitle={selectedEvent
                    ? `${selectedEvent.source} · ${new Date(selectedEvent.timestamp).toLocaleString()}`
                    : ''}
                icon={<Activity size={18} />}
            >
                {selectedEvent && (
                    <div className="telemetry-detail">
                        <dl className="mon-inforows">
                            <div><dt>ID</dt><dd><code>{selectedEvent.id}</code></dd></div>
                            <div><dt>Type</dt><dd>{selectedEvent.event_type}</dd></div>
                            <div>
                                <dt>Severity</dt>
                                <dd>
                                    <Pill kind={(SEVERITY_CONFIG[selectedEvent.severity] || SEVERITY_CONFIG.info).pill}>
                                        {selectedEvent.severity}
                                    </Pill>
                                </dd>
                            </div>
                            {selectedEvent.resource_type && (
                                <div>
                                    <dt>Resource</dt>
                                    <dd>{selectedEvent.resource_type}:{selectedEvent.resource_id}</dd>
                                </div>
                            )}
                            {selectedEvent.actor_username && (
                                <div><dt>Actor</dt><dd>{selectedEvent.actor_username}</dd></div>
                            )}
                            {selectedEvent.correlation_id && (
                                <div>
                                    <dt>Correlation</dt>
                                    <dd>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => {
                                                setFilters((f) => ({ ...f, correlation_id: selectedEvent.correlation_id }));
                                                setSelectedEvent(null);
                                            }}
                                        >
                                            {selectedEvent.correlation_id} <ChevronRight size={12} />
                                        </Button>
                                    </dd>
                                </div>
                            )}
                        </dl>
                        <h4 className="telemetry-detail__heading">Payload</h4>
                        <pre className="telemetry-detail__payload">
                            {JSON.stringify(selectedEvent.payload || {}, null, 2)}
                        </pre>
                    </div>
                )}
            </Drawer>
        </div>
    );
}
