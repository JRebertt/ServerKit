import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Pill, DataTable, DataTableFooter, ListToolbar } from '../ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import Modal from '../Modal';

// Built-in saved views. These are the four buttons that used to sit in the
// toolbar (All / Active / Failed / Inactive) — they narrowed the AGENT query
// (`systemctl --state=…`), which meant every other control on the page was
// reasoning about a partial list. The agent already passes `--all`, so the
// unfiltered response carries every state and the same buckets are exact
// client-side rules over the whole set.
//
// Every rule matches the `state` column's `value`, which is systemd's own
// ACTIVE word — the one the Pill renders.
const NO_RULES = { match: 'all', rules: [] };
const STATE_IS = (id, ...values) => ({
    match: 'all',
    rules: [{ id, field: 'state', op: 'any', value: values }],
});

// Each view clears the search box (`page: { search: '' }`) rather than leaving
// it out: an omitted key means "leave whatever is typed", and the view would
// then read as unsaved the moment it was applied on top of a search.
const SERVICE_VIEWS = [
    {
        // The worklist. A failed unit is the only row on this page that is
        // unambiguously wrong, so it leads.
        name: 'Failed units',
        state: {
            sorts: [{ key: 'unit', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: STATE_IS('sv1', 'failed'),
            page: { search: '' },
        },
    },
    {
        // What is actually up. 'activating' rides along: it is on its way to
        // active, and burying a unit stuck mid-start under "everything else" is
        // how a slow boot gets missed.
        name: 'Running',
        state: {
            sorts: [{ key: 'unit', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: STATE_IS('sv2', 'active', 'activating'),
            page: { search: '' },
        },
    },
    {
        // Installed but not running. On a `--all` listing this is most of the
        // list, and it is the half you scan when something should be up.
        name: 'Inactive',
        state: {
            sorts: [{ key: 'unit', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: STATE_IS('sv3', 'inactive'),
            page: { search: '' },
        },
    },
    {
        // Everything the agent returned, no rules — the "nothing is filtered"
        // answer, and the view a search is usually run against.
        name: 'All units',
        state: {
            sorts: [{ key: 'unit', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: NO_RULES,
            page: { search: '' },
        },
    },
];

// systemd active/sub state → ds Pill kind
const STATE_PILL = {
    active: 'green',
    running: 'green',
    activating: 'amber',
    reloading: 'amber',
    restarting: 'amber',
    failed: 'red',
    inactive: 'gray',
    dead: 'gray',
    stopped: 'gray',
};

const ServicesTab = ({ serverId, serverStatus }) => {
    const toast = useToast();
    const [units, setUnits] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [busyUnit, setBusyUnit] = useState(null);
    const [logsFor, setLogsFor] = useState(null); // { unit, entries, raw }
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-sd-services-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-sd-services-cols' });

    // One unfiltered fetch. The state buckets are column rules now, so asking
    // the agent for a subset would only hide rows from the rules — and from the
    // count next to them.
    const loadUnits = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getRemoteServices(serverId);
            setUnits(data?.units || []);
        } catch (err) {
            toast.error(err.message || 'Failed to load services');
        } finally {
            setLoading(false);
        }
    }, [serverId, toast]);

    useEffect(() => {
        if (serverStatus !== 'online') {
            setLoading(false);
            return;
        }
        loadUnits();
    }, [serverStatus, loadUnits]);

    const filtered = useMemo(() => {
        if (!search.trim()) return units;
        const needle = search.trim().toLowerCase();
        return units.filter((u) => u.unit?.toLowerCase().includes(needle));
    }, [units, search]);

    // The page's own half of a saved view. Everything else — sorts, hidden
    // columns, rules — is captured identically on every list page.
    const viewPageState = useMemo(() => ({ search }), [search]);
    const applyViewPageState = useCallback((saved) => {
        if (saved.search !== undefined) setSearch(saved.search);
    }, []);

    async function control(unit, action) {
        setBusyUnit(unit);
        try {
            await api.controlRemoteService(serverId, unit, action);
            toast.success(`${unit}: ${action} ok`);
            // Refresh state — only the affected row needs a reload but
            // re-fetching the list is simpler and keeps the filter consistent.
            loadUnits();
        } catch (err) {
            toast.error(err.message || `Failed to ${action} ${unit}`);
        } finally {
            setBusyUnit(null);
        }
    }

    async function viewLogs(unit) {
        try {
            const data = await api.getRemoteServiceLogs(serverId, unit, 200);
            setLogsFor({ unit, entries: data?.entries || [] });
        } catch (err) {
            toast.error(err.message || 'Failed to load logs');
        }
    }

    async function reloadDaemon() {
        setBusyUnit('__daemon__');
        try {
            await api.reloadRemoteSystemdDaemon(serverId);
            toast.success('systemctl daemon-reload completed');
        } catch (err) {
            toast.error(err.message || 'daemon-reload failed');
        } finally {
            setBusyUnit(null);
        }
    }

    // Units table columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace so the .server-services__* SCSS keeps
    // applying (.server-services__desc, .server-services__row-actions, .mono).
    //
    // Declared above the offline guard: the chrome below is a hook, so it
    // cannot sit behind an early return.
    const unitColumns = [
        {
            key: 'unit',
            header: 'Unit',
            sortable: true,
            hideable: false,
            // Hundreds of distinct names on a real host — a fragment you type,
            // never a list you pick from.
            type: 'text',
            value: (u) => u.unit || '',
            sortValue: (u) => u.unit || '',
            cellClassName: 'mono',
            render: (u) => u.unit,
        },
        {
            key: 'state',
            header: 'State',
            sortable: true,
            // Declared, not inferred: systemd's ACTIVE vocabulary is six words
            // wide, but a host where every unit is active offers ONE distinct
            // value and the column would fall back to text — which turns the
            // pick-list into a typed fragment and every view above into a
            // no-op. `value` is what the rules read: the same word the Pill
            // renders, `sub` standing in only when the agent's plain-text
            // fallback left ACTIVE empty.
            type: 'enum',
            enumOrder: ['active', 'activating', 'failed', 'inactive'],
            value: (u) => u.active || u.sub || 'unknown',
            sortValue: (u) => u.active || u.sub || 'unknown',
            render: (u) => (
                <Pill kind={STATE_PILL[u.active] || STATE_PILL[u.sub] || 'gray'}>
                    {u.active || u.sub || 'unknown'}
                </Pill>
            ),
        },
        {
            key: 'description',
            header: 'Description',
            sortable: true,
            type: 'text',
            value: (u) => u.description || '',
            sortValue: (u) => u.description || '',
            cellClassName: 'server-services__desc',
            render: (u) => u.description,
        },
        {
            key: 'actions',
            header: '',
            sortable: false,
            hideable: false,
            cellClassName: 'server-services__row-actions',
            render: (u) => (
                <>
                    <Button
                        size="sm" variant="outline"
                        disabled={busyUnit === u.unit}
                        onClick={() => control(u.unit, 'start')}
                    >Start</Button>
                    <Button
                        size="sm" variant="outline"
                        disabled={busyUnit === u.unit}
                        onClick={() => control(u.unit, 'stop')}
                    >Stop</Button>
                    <Button
                        size="sm" variant="outline"
                        disabled={busyUnit === u.unit}
                        onClick={() => control(u.unit, 'restart')}
                    >Restart</Button>
                    <Button
                        size="sm" variant="outline"
                        onClick={() => viewLogs(u.unit)}
                    >Logs</Button>
                </>
            ),
        },
    ];

    // `rows` is the SEARCHED list — the column rules are applied inside
    // DataTable, and the counts below come back through `chrome.shownCount`.
    // The search box is the page's own state, so it rides `page` in the
    // envelope and a saved view carries it. No `urlScope`: the units table is
    // the only one on this tab, so its links keep the plain ?view= names.
    const chrome = useTableChrome({
        columns: unitColumns,
        rows: filtered,
        viewPageKey: 'serverdetail-services',
        builtinViews: SERVICE_VIEWS,
        noun: 'units',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        pageState: viewPageState,
        applyPage: applyViewPageState,
    });

    if (serverStatus !== 'online') {
        return (
            <div className="empty-state">
                <p>Server is offline. Reconnect to manage services.</p>
            </div>
        );
    }

    return (
        <div className="server-services">
            {/* The view name is the heading and carries the counts; the filter
                button and "⋮" ride it. The toolbar below keeps only what is
                the PAGE's rather than the table's: search, and the two systemd
                actions. */}
            <GridViewPicker
                views={chrome.views}
                label="units"
                total={`${chrome.shownCount} of ${units.length} units`}
                onCreate={chrome.createView}
                actions={(
                    <>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={loadUnits} />
                    </>
                )}
            />
            <ListToolbar
                tools={(
                    <div className="server-services__actions">
                        <Button variant="outline" onClick={loadUnits}>Refresh</Button>
                        <Button
                            variant="outline"
                            onClick={reloadDaemon}
                            disabled={busyUnit === '__daemon__'}
                        >
                            Reload daemon
                        </Button>
                    </div>
                )}
            >
                <Input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Filter by unit name…"
                    className="server-services__search"
                />
            </ListToolbar>

            <GridChips {...chrome.chipProps} />

            {loading ? (
                <p className="text-muted-foreground">Loading…</p>
            ) : filtered.length === 0 ? (
                <p className="text-muted-foreground">No matching units.</p>
            ) : (
                <DataTable
                    columns={chrome.columns}
                    data={filtered}
                    keyField="unit"
                    sorts={sorts}
                    onSortsChange={setSorts}
                    {...chrome.tableProps}
                    tableClassName="server-services__table"
                    emptyTitle="No units match this view."
                    emptyMessage=""
                    footer={(
                        <DataTableFooter
                            shown={chrome.shownCount}
                            total={units.length}
                            noun="unit"
                        />
                    )}
                />
            )}

            <GridFilterDrawer {...chrome.drawerProps} />

            <Modal
                open={!!logsFor}
                onClose={() => setLogsFor(null)}
                title={logsFor ? `Logs — ${logsFor.unit}` : ''}
                size="xl"
            >
                {logsFor && (
                    <pre className="server-services__logs">
                        {logsFor.entries.length === 0
                            ? '(no entries)'
                            : logsFor.entries.map((e, i) => (
                                <div key={i}>
                                    [{e.priority || '-'}] {e.message}
                                </div>
                            ))}
                    </pre>
                )}
            </Modal>
        </div>
    );
};

export default ServicesTab;
