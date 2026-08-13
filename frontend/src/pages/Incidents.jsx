// Incidents — one place for "something is wrong right now".
//
// This absorbed the old Alerts tab. A CPU threshold crossing on a host and a
// monitor going down are the same question asked of two different subjects, and
// splitting them across two tabs is what made alerting look like it only ever
// described the panel's own machine. Host threshold alerting is unchanged —
// same endpoints, same ack/check actions — it just renders in this timeline
// alongside monitor outages.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    AlertTriangle, CheckCircle2, ChevronRight, Radar, RefreshCw, Siren,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import FleetAlertsPanel from '../components/monitoring/FleetAlertsPanel';
import { DataTable, DataTableFooter, Drawer, Pill, SearchField } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { useTopbarActions, useTopbarChrome } from '@/hooks/useTopbarActions';
import { IMPACT_TONE, INCIDENT_STATES } from '../components/monitoring/monitorShared';

// Built-in views. This page used to carry BOTH old affordances at once — a KPI
// band whose tiles set a filter, and an Active/Resolved/All segment row — while
// having no column menu, no search and no saved views at all. Every bucket
// either of them offered is a rule here now.
//
// `resolved` is the axis both sources share: an incident is resolved when its
// status says so, a host alert when it is history rather than firing.
const NO_RULES = { match: 'all', rules: [] };
const RESOLVED_IS = (value) => ({
    match: 'all',
    rules: [{ id: 'rs', field: 'resolved', op: 'is', value }],
});

const BUILTIN_VIEWS = [
    {
        // The page's reason to exist: what is wrong RIGHT NOW.
        name: 'Active',
        state: {
            sorts: [{ key: 'when', direction: 'desc' }], hiddenKeys: [],
            columnFilters: RESOLVED_IS(false), page: { search: '' },
        },
    },
    {
        name: 'Resolved',
        state: {
            sorts: [{ key: 'when', direction: 'desc' }], hiddenKeys: [],
            columnFilters: RESOLVED_IS(true), page: { search: '' },
        },
    },
    {
        // What the "Open incidents" tile counted — and note it is NOT the same
        // as Active: it deliberately excludes host alerts, which is why the
        // tile's number never matched the segment's row count.
        name: 'Open incidents',
        state: {
            sorts: [{ key: 'when', direction: 'desc' }], hiddenKeys: ['kind'],
            columnFilters: {
                match: 'all',
                rules: [
                    { id: 'oi1', field: 'kind', op: 'any', value: ['incident'] },
                    { id: 'oi2', field: 'resolved', op: 'is', value: false },
                ],
            },
            page: { search: '' },
        },
    },
    {
        // The host side of the same question, for when a threshold is flapping.
        name: 'Host alerts',
        state: {
            sorts: [{ key: 'when', direction: 'desc' }], hiddenKeys: ['kind'],
            columnFilters: { match: 'all', rules: [{ id: 'ha', field: 'kind', op: 'any', value: ['alert'] }] },
            page: { search: '' },
        },
    },
    {
        name: 'Everything, newest first',
        state: {
            sorts: [{ key: 'when', direction: 'desc' }], hiddenKeys: [],
            columnFilters: NO_RULES, page: { search: '' },
        },
    },
];

const STATE_TONE = {
    investigating: 'red',
    identified: 'amber',
    monitoring: 'cyan',
    resolved: 'green',
};

const SEVERITY_TONE = { critical: 'red', warning: 'amber', info: 'cyan' };

function formatWhen(iso) {
    if (!iso) return 'unknown';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return 'unknown';
    return date.toLocaleString();
}

function formatValue(value) {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—';
    return value.toFixed(1);
}

export default function Incidents() {
    const toast = useToast();
    const [search, setSearch] = useState('');
    const [incidents, setIncidents] = useState([]);
    const [activeAlerts, setActiveAlerts] = useState([]);
    const [alertHistory, setAlertHistory] = useState([]);
    const [monitors, setMonitors] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState(null);
    const [note, setNote] = useState('');
    const [checking, setChecking] = useState(false);
    const [hasFleet, setHasFleet] = useState(false);
    const { sorts, setSorts } = useTableSort({
        defaultSorts: [{ key: 'when', direction: 'desc' }],
        storageKey: 'serverkit-table-incidents-sort',
    });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({
        storageKey: 'serverkit-table-incidents-cols',
    });

    const load = useCallback(async () => {
        try {
            const [incidentsRes, statusRes, historyRes, monitorsRes, serversRes] = await Promise.all([
                api.getIncidents({ state: 'all', limit: 200 }).catch(() => null),
                api.getMonitoringStatus().catch(() => null),
                api.getAlertHistory(50).catch(() => null),
                api.getMonitors().catch(() => null),
                api.getServers().catch(() => null),
            ]);
            setIncidents(incidentsRes?.incidents || []);
            setActiveAlerts(statusRes?.active_alerts || []);
            setAlertHistory(historyRes?.alerts || []);
            setMonitors(monitorsRes?.monitors || []);
            // The fleet panel is only meaningful once there are paired servers.
            const servers = Array.isArray(serversRes) ? serversRes : (serversRes?.servers || []);
            setHasFleet(servers.length > 0);
        } catch {
            // Keep the last good list rather than blanking the page.
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const onCheckAlerts = async () => {
        setChecking(true);
        try {
            const result = await api.checkAlerts();
            const count = result.alerts?.length || 0;
            toast[count > 0 ? 'warning' : 'success'](`${count} host alert${count === 1 ? '' : 's'} firing`);
            await load();
        } catch (err) {
            toast.error(err.message || 'Alert check failed');
        } finally {
            setChecking(false);
        }
    };

    useTopbarActions(() => (
        <>
            <Button variant="outline" size="sm" onClick={onCheckAlerts} disabled={checking}>
                <Siren size={14} /> {checking ? 'Checking…' : 'Check hosts'}
            </Button>
            <Button variant="outline" size="sm" onClick={load}>
                <RefreshCw size={14} /> Refresh
            </Button>
            <SearchField
                value={search}
                onSearch={setSearch}
                placeholder="Search incidents and alerts…"
            />
        </>
    ), [checking, load, search]);

    const monitorsById = useMemo(
        () => Object.fromEntries(monitors.map((m) => [m.id, m])),
        [monitors],
    );

    // One list, two sources. Host alerts have no lifecycle of their own — they
    // are either firing or historical — so they map onto the same active/resolved
    // axis the incidents use.
    const items = useMemo(() => {
        const fromIncidents = incidents.map((incident) => ({
            kind: 'incident',
            key: `incident-${incident.id}`,
            id: incident.id,
            title: incident.title,
            subject: monitorsById[incident.component_id]?.name || 'Service',
            state: incident.status,
            tone: STATE_TONE[incident.status] || 'gray',
            impact: incident.impact,
            when: incident.created_at,
            resolved: incident.status === 'resolved',
            raw: incident,
        }));

        const fromActive = activeAlerts.map((alert, index) => ({
            kind: 'alert',
            key: `active-${alert.type}-${index}`,
            title: alert.message,
            subject: 'This server',
            state: 'firing',
            tone: 'red',
            impact: alert.severity,
            when: alert.timestamp,
            resolved: false,
            raw: alert,
        }));

        const fromHistory = alertHistory.map((alert, index) => ({
            kind: 'alert',
            key: `history-${alert.timestamp || index}-${index}`,
            title: alert.message,
            subject: 'This server',
            state: alert.severity,
            tone: SEVERITY_TONE[alert.severity] || 'gray',
            impact: alert.severity,
            when: alert.timestamp,
            resolved: true,
            raw: alert,
        }));

        return [...fromActive, ...fromIncidents, ...fromHistory]
            .sort((a, b) => new Date(b.when || 0) - new Date(a.when || 0));
    }, [incidents, activeAlerts, alertHistory, monitorsById]);

    // Search only. The active/resolved split used to live here as a segment
    // filter; it is a column rule now, applied inside the table.
    const shown = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return items;
        return items.filter((item) => (
            [item.title, item.subject, item.state].some((v) => String(v || '').toLowerCase().includes(q))
        ));
    }, [items, search]);

    const onPostUpdate = async (state) => {
        if (!selected || selected.kind !== 'incident') return;
        try {
            await api.updateIncident(selected.id, {
                status: state,
                update_body: note.trim() || `Status moved to ${state}.`,
            });
            toast.success(`Incident ${state}`);
            setNote('');
            setSelected(null);
            await load();
        } catch (err) {
            toast.error(err.message || 'Could not post the update');
        }
    };

    // Column values are the RAW strings the rules filter on; the cells render
    // the same values, so a preset reads the way the row does.
    const columns = useMemo(() => [
        {
            key: 'title',
            header: 'What happened',
            sortable: true,
            hideable: false,
            type: 'text',
            value: (item) => item.title || '',
            render: (item) => (
                <div className="sk-cell-name">
                    <span className={`incident-row__sev incident-row__sev--${item.tone}`} />
                    <span>
                        <div>{item.title}</div>
                        <div className="sk-cell-sub">
                            {item.kind === 'alert' && item.raw.type
                                ? `${item.raw.type} ${formatValue(item.raw.value)} / ${item.raw.threshold}`
                                : item.subject}
                        </div>
                    </span>
                </div>
            ),
        },
        {
            key: 'state',
            header: 'State',
            sortable: true,
            type: 'enum',
            value: (item) => item.state || '',
            render: (item) => <Pill kind={item.tone}>{item.state}</Pill>,
        },
        {
            key: 'subject',
            header: 'Subject',
            sortable: true,
            type: 'enum',
            value: (item) => item.subject || '',
        },
        {
            // The axis both sources share, and what Active/Resolved filter on.
            key: 'resolved',
            header: 'Resolved',
            sortable: true,
            type: 'bool',
            value: (item) => !!item.resolved,
            render: (item) => (item.resolved ? 'yes' : 'no'),
        },
        {
            // Monitor outage vs host threshold alert — the distinction the
            // "Open incidents" tile silently relied on.
            key: 'kind',
            header: 'Source',
            sortable: true,
            type: 'enum',
            value: (item) => item.kind || '',
            render: (item) => (item.kind === 'alert' ? 'host alert' : 'incident'),
        },
        {
            key: 'impact',
            header: 'Impact',
            sortable: true,
            type: 'enum',
            value: (item) => item.impact || '—',
        },
        {
            key: 'when',
            header: 'When',
            sortable: true,
            type: 'date',
            value: (item) => item.when || null,
            sortValue: (item) => (item.when ? new Date(item.when).getTime() : null),
            cellClassName: 'sk-cell-mono',
            render: (item) => formatWhen(item.when),
        },
        {
            key: 'open',
            header: '',
            sortable: false,
            hideable: false,
            render: () => <ChevronRight size={16} className="incident-row__chev" />,
        },
    ], []);

    const viewPageState = useMemo(() => ({ search }), [search]);
    const applyViewPageState = useCallback((saved) => {
        if (saved.search !== undefined) setSearch(saved.search);
    }, []);

    const chrome = useTableChrome({
        columns,
        rows: shown,
        viewPageKey: 'incidents',
        builtinViews: BUILTIN_VIEWS,
        noun: 'incidents',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        pageState: viewPageState,
        applyPage: applyViewPageState,
    });

    const { portal: topbarChrome } = useTopbarChrome(
        <>
            <GridFilterButton
                count={chrome.filterCount}
                onClick={() => chrome.setDrawerOpen(true)}
            />
            <GridToolsMenu {...chrome.toolsProps} onRefresh={load} />
        </>,
    );

    if (loading) {
        return (
            <div className="sk-tabgroup__inner incidents-page">
                <EmptyState loading loadingVariant="feed" title="Loading incidents" />
            </div>
        );
    }

    const selectedMonitor = selected?.kind === 'incident'
        ? monitorsById[selected.raw.component_id]
        : null;

    return (
        <div className="sk-tabgroup__inner incidents-page">
            {topbarChrome}
            <GridViewPicker
                views={chrome.views}
                label="incidents"
                onCreate={chrome.createView}
            />

            <GridChips {...chrome.chipProps} />

            {items.length === 0 ? (
                <EmptyState
                    icon={CheckCircle2}
                    title="Nothing is wrong right now"
                    description="No monitor is down and no host is over its limit."
                />
            ) : (
                <div className="mon-card">
                    <DataTable
                        {...chrome.tableProps}
                        tableClassName="sk-dtable incidents-table"
                        columns={chrome.columns}
                        data={shown}
                        keyField="key"
                        sorts={sorts}
                        onSortsChange={setSorts}
                        onRowClick={setSelected}
                        emptyTitle="No incidents match this view."
                        emptyMessage=""
                        footer={(
                            <DataTableFooter
                                shown={shown.length}
                                total={items.length}
                                noun="incident"
                            />
                        )}
                    />
                </div>
            )}

            {/* Per-server threshold alerts across the fleet: their own system
                with its own ack/resolve lifecycle, so they keep their own panel
                rather than being flattened into the timeline above. */}
            {hasFleet && <FleetAlertsPanel />}

            <Drawer
                open={Boolean(selected)}
                onOpenChange={(open) => { if (!open) { setSelected(null); setNote(''); } }}
                title={selected?.title || ''}
                subtitle={selected ? `${selected.subject} · ${formatWhen(selected.when)}` : ''}
                icon={selected?.kind === 'incident' ? <AlertTriangle size={18} /> : <Siren size={18} />}
            >
                {selected?.kind === 'incident' && (
                    <div className="incident-detail">
                        <div className="incident-detail__pills">
                            <Pill kind={STATE_TONE[selected.raw.status] || 'gray'}>{selected.raw.status}</Pill>
                            <Pill kind={IMPACT_TONE[selected.raw.impact] || 'gray'}>{selected.raw.impact} impact</Pill>
                        </div>

                        {selected.raw.body && <p className="incident-detail__body">{selected.raw.body}</p>}

                        {selectedMonitor && (
                            <Link className="incident-detail__link" to={`/monitoring/monitors/${selectedMonitor.id}`}>
                                <Radar size={14} /> Open {selectedMonitor.name}
                            </Link>
                        )}

                        <h4 className="incident-detail__heading">Timeline</h4>
                        {selected.raw.updates?.length ? (
                            <ol className="incident-timeline">
                                {selected.raw.updates.map((update) => (
                                    <li key={update.id} className="incident-timeline__item">
                                        <span className={`incident-timeline__dot is-${STATE_TONE[update.status] || 'gray'}`} />
                                        <div>
                                            <div className="incident-timeline__head">
                                                <Pill kind={STATE_TONE[update.status] || 'gray'}>{update.status}</Pill>
                                                <span>{formatWhen(update.created_at)}</span>
                                            </div>
                                            <p>{update.body}</p>
                                        </div>
                                    </li>
                                ))}
                            </ol>
                        ) : (
                            <p className="mon-panel-hint">No updates posted yet.</p>
                        )}

                        {selected.raw.status !== 'resolved' && (
                            <div className="incident-detail__post">
                                <h4 className="incident-detail__heading">Post an update</h4>
                                <Input
                                    value={note}
                                    onChange={(e) => setNote(e.target.value)}
                                    placeholder="What changed?"
                                />
                                <div className="incident-detail__states">
                                    {INCIDENT_STATES.map((state) => (
                                        <Button
                                            key={state}
                                            variant="outline"
                                            size="sm"
                                            onClick={() => onPostUpdate(state)}
                                        >
                                            {state}
                                        </Button>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {selected?.kind === 'alert' && (
                    <div className="incident-detail">
                        <div className="incident-detail__pills">
                            <Pill kind={selected.tone}>{selected.state}</Pill>
                            <Pill kind={SEVERITY_TONE[selected.raw.severity] || 'gray'}>
                                {selected.raw.severity}
                            </Pill>
                        </div>
                        <dl className="mon-inforows">
                            <div><dt>Metric</dt><dd>{selected.raw.type || '—'}</dd></div>
                            <div><dt>Reading</dt><dd>{formatValue(selected.raw.value)}</dd></div>
                            <div><dt>Limit</dt><dd>{selected.raw.threshold ?? '—'}</dd></div>
                            <div><dt>When</dt><dd>{formatWhen(selected.when)}</dd></div>
                        </dl>
                        <p className="mon-panel-hint">
                            Host limits live on the <Link to="/monitoring/rules">Rules</Link> tab.
                        </p>
                    </div>
                )}
            </Drawer>

            <GridFilterDrawer {...chrome.drawerProps} />
        </div>
    );
}
