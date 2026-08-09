import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Pill, ColumnsMenu, DataTable, DataTableFooter, SortMenu } from '../ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import Modal from '../Modal';

const STATE_FILTERS = [
    { value: '',       label: 'All' },
    { value: 'active', label: 'Active' },
    { value: 'failed', label: 'Failed' },
    { value: 'inactive', label: 'Inactive' },
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
    const [stateFilter, setStateFilter] = useState('');
    const [search, setSearch] = useState('');
    const [busyUnit, setBusyUnit] = useState(null);
    const [logsFor, setLogsFor] = useState(null); // { unit, entries, raw }
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-sd-services-sort' });
    const {
        hiddenKeys, toggleColumn, showAllColumns,
    } = useColumnVisibility({ storageKey: 'serverkit-table-sd-services-cols' });

    const loadUnits = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getRemoteServices(serverId, { state: stateFilter || null });
            setUnits(data?.units || []);
        } catch (err) {
            toast.error(err.message || 'Failed to load services');
        } finally {
            setLoading(false);
        }
    }, [serverId, stateFilter, toast]);

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

    if (serverStatus !== 'online') {
        return (
            <div className="empty-state">
                <p>Server is offline. Reconnect to manage services.</p>
            </div>
        );
    }

    // Units table columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace so the .server-services__* SCSS keeps
    // applying (.server-services__desc, .server-services__row-actions, .mono).
    const unitColumns = [
        {
            key: 'unit',
            header: 'Unit',
            sortable: true,
            hideable: false,
            sortValue: (u) => u.unit || '',
            cellClassName: 'mono',
            render: (u) => u.unit,
        },
        {
            key: 'state',
            header: 'State',
            sortable: true,
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

    return (
        <div className="server-services">
            <div className="server-services__toolbar">
                <Input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Filter by unit name…"
                    className="server-services__search"
                />
                <div className="server-services__filters">
                    {STATE_FILTERS.map((f) => (
                        <Button
                            key={f.value || 'all'}
                            variant={stateFilter === f.value ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => setStateFilter(f.value)}
                        >
                            {f.label}
                        </Button>
                    ))}
                </div>
                <div className="server-services__actions">
                    <Button variant="outline" onClick={loadUnits}>Refresh</Button>
                    <Button
                        variant="outline"
                        onClick={reloadDaemon}
                        disabled={busyUnit === '__daemon__'}
                    >
                        Reload daemon
                    </Button>
                    <SortMenu columns={unitColumns} sorts={sorts} onChange={setSorts} />
                    <ColumnsMenu
                        columns={unitColumns}
                        hiddenKeys={hiddenKeys}
                        onToggle={toggleColumn}
                        onShowAll={showAllColumns}
                    />
                </div>
            </div>

            {loading ? (
                <p className="text-muted-foreground">Loading…</p>
            ) : filtered.length === 0 ? (
                <p className="text-muted-foreground">No matching units.</p>
            ) : (
                <DataTable
                    columns={unitColumns}
                    data={filtered}
                    keyField="unit"
                    sorts={sorts}
                    onSortsChange={setSorts}
                    hiddenKeys={hiddenKeys}
                    tableClassName="server-services__table"
                    footer={(
                        <DataTableFooter
                            shown={filtered.length}
                            total={units.length}
                            noun="unit"
                        />
                    )}
                />
            )}

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
