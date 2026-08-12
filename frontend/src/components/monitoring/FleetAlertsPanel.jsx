import { useState, useEffect } from 'react';
import { CheckCircle, Eye } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { DataTable, DataTableFooter, Pill, SegControl } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { METRIC_LABELS } from './fleetMetrics';

const ALERT_FILTERS = [
    { value: 'active', label: 'Active' },
    { value: 'acknowledged', label: 'Acknowledged' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'all', label: 'All' },
];

// Alerts raised by per-server thresholds across the fleet. The panel host's own
// alerts are a different system (a single set of limits, delivered by the
// monitoring scheduler) and sit above this in the Incidents timeline; the limits
// behind these rows are edited on the Rules tab.
export default function FleetAlertsPanel({ scope, refreshKey = 0 }) {
    const toast = useToast();
    const [alerts, setAlerts] = useState([]);
    const [filter, setFilter] = useState('active');
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        let cancelled = false;
        api.getFleetAlerts({
            status: filter !== 'all' ? filter : undefined,
            // Following the top-bar scope keeps every section answering the
            // same question about the same host.
            server_id: scope && scope !== 'host' ? scope : undefined,
        })
            .then((data) => { if (!cancelled) setAlerts(Array.isArray(data) ? data : []); })
            .catch(() => { if (!cancelled) setAlerts([]); });
        return () => { cancelled = true; };
    }, [filter, scope, refreshKey, reloadKey]);

    const runAction = async (fn, failure) => {
        try {
            await fn();
            setReloadKey((k) => k + 1);
        } catch {
            toast.error(failure);
        }
    };

    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-fleet-alerts-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-fleet-alerts-cols' });

    // Columns for the shared DataTable; cell markup is identical to the
    // hand-rolled table it replaces (.sk-cell-mono, .mon-row-actions).
    const alertColumns = [
        {
            key: 'server',
            header: 'Server',
            sortable: true,
            hideable: false,
            sortValue: (a) => a.server_name || '',
            render: (a) => a.server_name,
        },
        {
            key: 'metric',
            header: 'Metric',
            sortable: true,
            sortValue: (a) => METRIC_LABELS[a.metric] || a.metric,
            render: (a) => METRIC_LABELS[a.metric] || a.metric,
        },
        {
            key: 'value',
            header: 'Value',
            sortable: true,
            sortValue: (a) => a.value ?? null,
            cellClassName: 'sk-cell-mono',
            render: (a) => `${a.value}%`,
        },
        {
            key: 'threshold',
            header: 'Threshold',
            sortable: true,
            sortValue: (a) => a.threshold ?? null,
            cellClassName: 'sk-cell-mono',
            render: (a) => `${a.threshold}%`,
        },
        {
            key: 'severity',
            header: 'Severity',
            sortable: true,
            sortValue: (a) => a.severity || '',
            render: (a) => <Pill kind={a.severity === 'critical' ? 'red' : 'amber'}>{a.severity}</Pill>,
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (a) => a.status || '',
            render: (a) => (
                <Pill kind={a.status === 'active' ? 'red' : a.status === 'acknowledged' ? 'amber' : 'green'}>
                    {a.status}
                </Pill>
            ),
        },
        {
            key: 'time',
            header: 'Time',
            sortable: true,
            sortValue: (a) => (a.created_at ? new Date(a.created_at).getTime() : null),
            render: (a) => new Date(a.created_at).toLocaleString(),
        },
        {
            key: 'actions',
            header: '',
            sortable: false,
            hideable: false,
            cellClassName: 'mon-row-actions',
            render: (a) => (
                <>
                    {a.status === 'active' && (
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => runAction(
                                () => api.acknowledgeFleetAlert(a.id),
                                'Failed to acknowledge alert',
                            )}
                        >
                            <Eye size={14} /> Ack
                        </Button>
                    )}
                    {a.status !== 'resolved' && (
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => runAction(
                                () => api.resolveFleetAlert(a.id),
                                'Failed to resolve alert',
                            )}
                        >
                            <CheckCircle size={14} /> Resolve
                        </Button>
                    )}
                </>
            ),
        },
    ];

    return (
        <section className="monitoring-panel">
            <div className="monitoring-panel__header">
                <h3>Fleet alerts</h3>
                <div>
                    <SegControl value={filter} onChange={setFilter} options={ALERT_FILTERS} />
                </div>
            </div>

            {alerts.length > 0 ? (
                <DataTable
                    columns={alertColumns}
                    data={alerts}
                    keyField="id"
                    sorts={sorts}
                    onSortsChange={setSorts}
                    hiddenKeys={hiddenKeys}
                    onHiddenKeysChange={setHiddenKeys}
                    className="mon-table-scroll"
                    footer={(
                        <DataTableFooter
                            shown={alerts.length}
                            total={alerts.length}
                            noun="alert"
                        />
                    )}
                />
            ) : (
                <p className="mon-panel-hint">
                    <CheckCircle size={14} />
                    {filter === 'all'
                        ? 'No fleet alerts have ever been raised.'
                        : `No ${filter} fleet alerts.`}
                </p>
            )}
        </section>
    );
}
