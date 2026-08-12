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
//
// The KPI band that rebuild introduced is gone again. Five of its six tiles
// were filter shortcuts wearing a number — clicking one only ever set
// `filters.severity` — so they are saved views now (see BUILTIN_VIEWS), which
// is the same shortcut plus a name, a link and a place in the picker. "Total
// (24h)" was the one true aggregate (a backend count over a window the table
// never holds), so it moved to the view bar's meta line rather than dying.
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Activity, ChevronRight, Info, Loader2, RefreshCw, Trash2,
} from 'lucide-react';
import api from '../services/api';
import {
    DataTable, DataTableFooter, Drawer, FilterButton, FilterDrawer, ListToolbar,
    Pill, SearchField, countActiveFilters,
} from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { useConfirm } from '@/hooks/useConfirm';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';

const SEVERITY_ORDER = ['critical', 'error', 'warning', 'info', 'debug'];

// `pill` is a Pill kind (green|amber|red|cyan|violet|gray) — only tokens Pill
// knows, or the badge silently renders without its background. `label` is the
// one spelling of a severity the whole page uses: the pill, the filter drawer's
// option list and the built-in view names all read from here.
const SEVERITY_CONFIG = {
    critical: { pill: 'red', label: 'Critical' },
    error: { pill: 'red', label: 'Error' },
    warning: { pill: 'amber', label: 'Warning' },
    info: { pill: 'cyan', label: 'Info' },
    debug: { pill: 'gray', label: 'Debug' },
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

// Built-in saved views, in the shared envelope (see ds/grid/viewState.js).
//
// `page.serverFilters` is this page's SERVER-side query object (EMPTY_FILTERS
// shape: source / event_type / severity / resource_type / …), merged over
// EMPTY_FILTERS and sent straight to the API. It is deliberately NOT
// `columnFilters`: those are client-side column rules, which can only narrow
// the one page of rows already loaded, while this narrows the query. That is
// why the retired severity tiles became these presets and not column rules.
//
// It used to live at the TOP level of the state under the name `filters`, which
// is the envelope's word for column rules — the collision this rename fixes.
// Views users already saved keep working via `rename` on useTableChrome.
const NO_RULES = { match: 'all', rules: [] };
const NEWEST_FIRST = [{ key: 'timestamp', direction: 'desc' }];

// One preset describes a COMPLETE state. `serverFilters` is spelled out even
// when empty, so switching into a view clears the previous one's query instead
// of silently inheriting it — same reason `columnFilters` is always explicit.
const VIEW = (name, serverFilters, sorts = []) => ({
    name,
    state: { sorts, hiddenKeys: [], columnFilters: NO_RULES, page: { serverFilters } },
});

// The severity ladder is the old KPI band, in the band's own order. The three
// that already existed keep their names verbatim — a built-in is identified by
// name, so renaming one would orphan every shared ?view= link and anyone's
// saved default. Info and Debug are new: their tiles had no preset before.
const BUILTIN_VIEWS = [
    VIEW('Critical only', { severity: 'critical' }, NEWEST_FIRST),
    VIEW('Errors', { severity: 'error' }),
    VIEW('Warnings', { severity: 'warning' }),
    VIEW('Info', { severity: 'info' }),
    VIEW('Debug', { severity: 'debug' }),
    VIEW('Newest first', {}, NEWEST_FIRST),
    VIEW('Deploy failures', { source: 'deployment', severity: 'error' }, NEWEST_FIRST),
    VIEW('Backup failures', { source: 'backup', severity: 'error' }, NEWEST_FIRST),
    VIEW('Audit trail', { source: 'audit' }, NEWEST_FIRST),
];

export default function Telemetry() {
    const { isAdmin } = useAuth();
    const { showToast } = useToast();
    const { confirm } = useConfirm();

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

    // Table sort + column visibility, controlled so saved views can drive
    // them — same localStorage keys the DataTable used when uncontrolled.
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-telemetry-sort' });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({ storageKey: 'serverkit-table-telemetry-cols' });

    // The page-private half of a saved view: the FilterDrawer's server-side
    // query, and nothing else. The load-more page and the detail drawer are
    // deliberately out — as is `q`, which never was captured: a view that
    // pinned the search box would fight whatever the operator is typing.
    const viewPageState = useMemo(() => ({ serverFilters: filters }), [filters]);
    const applyViewPageState = useCallback((saved) => {
        if (saved.serverFilters !== undefined) {
            setFilters({ ...EMPTY_FILTERS, ...saved.serverFilters });
        }
    }, []);

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
        const confirmed = await confirm({
            title: 'Clean Up Old Events',
            message: 'Delete telemetry events older than 90 days? This cannot be undone.',
            confirmText: 'Delete',
            variant: 'danger',
        });
        if (!confirmed) {
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
            sortable: true,
            type: 'enum',
            // Sorting and filtering want DIFFERENT values here, so both are
            // spelled out. `sortValue` is the rank, because critical-before-
            // debug is the only useful order and alphabetical is nonsense.
            // `value` is the raw string, because that is what a rule matches —
            // and with only `sortValue` present, `fieldValue` falls back to it,
            // the column infers as `num`, and a rule of `severity is any of
            // critical` compares "critical" against 0 and matches nothing.
            value: (event) => event.severity,
            sortValue: (event) => {
                const rank = SEVERITY_ORDER.indexOf(event.severity);
                return rank === -1 ? null : rank;
            },
            // The grid only ever holds one page of events, so the menu would
            // otherwise list whichever severities the last 50 rows happened to
            // contain, alphabetically. Pin the full ladder in rank order.
            enumOrder: SEVERITY_ORDER,
            render: (event) => {
                const config = SEVERITY_CONFIG[event.severity] || SEVERITY_CONFIG.info;
                return <Pill kind={config.pill}>{config.label}</Pill>;
            },
        },
        {
            key: 'message',
            header: 'Event',
            sortable: true,
            sortValue: (event) => event.message || event.event_type || null,
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
            sortable: true,
            sortValue: (event) => (event.timestamp ? new Date(event.timestamp).getTime() : null),
            cellClassName: 'telemetry-cell__when',
            render: (event) => new Date(event.timestamp).toLocaleString(),
        },
    ];

    // Shared list chrome: view picker + chips + column-rule drawer + tools. It
    // sits ALONGSIDE the server-side FilterDrawer above, not in place of it —
    // a column rule sifts the 50 rows on screen, the drawer sifts the query.
    const chrome = useTableChrome({
        columns,
        rows: events,
        viewPageKey: 'telemetry',
        builtinViews: BUILTIN_VIEWS,
        noun: 'events',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        pageState: viewPageState,
        applyPage: applyViewPageState,
        // Views saved before the envelope kept this page's server-side query at
        // the top level as `filters`, which now means column rules.
        rename: { filters: 'serverFilters' },
    });

    const hasFilters = Boolean(q || activeFilterCount);

    return (
        <div className="sk-tabgroup__inner telemetry-page">
            {/* Outside the empty check below on purpose: a view that returns
                no events must still be swappable for another one. "Total (24h)"
                is the KPI band's one surviving number — a backend count over a
                window the loaded rows never model, so nothing on the grid can
                restate it. It rides the meta line beside the row count. */}
            <GridViewPicker
                views={chrome.views}
                label="events"
                total={`${events.length} loaded · ${stats?.total || 0} in the last 24h`}
                onCreate={chrome.createView}
            />
            <ListToolbar
                tools={(
                    <>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={() => fetchEvents(1, true)} />
                    </>
                )}
            />

            <GridChips {...chrome.chipProps} />

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
                            <Button
                                variant="outline"
                                onClick={() => {
                                    setFilters(EMPTY_FILTERS);
                                    setQ('');
                                    // The chips sit right above this button, so
                                    // leaving the column rules armed would read
                                    // as "Clear filters" doing half its job.
                                    chrome.api.resetToView();
                                }}
                            >
                                Clear filters
                            </Button>
                        )
                        : undefined}
                />
            ) : (
                <>
                    <DataTable
                        tableClassName="sk-dtable telemetry-table"
                        data={events}
                        keyField="id"
                        columns={chrome.columns}
                        sorts={sorts}
                        onSortsChange={setSorts}
                        {...chrome.tableProps}
                        loading={loading && events.length === 0}
                        onRowClick={setSelectedEvent}
                        rowClassName={(event) => `is-${event.severity}`}
                        footer={(
                            <DataTableFooter
                                shown={events.length}
                                total={null}
                                noun="event"
                                hasMore={hasMore}
                                onLoadMore={() => fetchEvents(page + 1, false)}
                                loading={loading}
                            />
                        )}
                    />

                    {loading && events.length > 0 && (
                        <div className="telemetry-loading"><Loader2 size={20} className="spin" /></div>
                    )}
                </>
            )}

            {/* The query filter, opened from the top bar's FilterButton. It
                narrows what the API returns, so it reaches every event on the
                server — not just the page in memory. The column-rule drawer
                below is the other tool, not a replacement for this one. */}
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

            <GridFilterDrawer {...chrome.drawerProps} />

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
