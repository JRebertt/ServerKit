import { useState, useEffect } from 'react';
import { Plus, XCircle } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DataTable, DataTableFooter } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { METRIC_LABELS } from './fleetMetrics';

const DEFAULT_THRESHOLD = {
    metric: 'cpu',
    warning_threshold: 80,
    critical_threshold: 95,
    duration_seconds: 300,
};

// Per-server limits, sitting under the panel host's own limits on the Rules
// tab: same idea, wider scope. Two lists rather than one because they are two
// backends — the host's four values are a single config, these are rows.
export default function FleetThresholdsPanel({ servers = [], refreshKey = 0 }) {
    const toast = useToast();
    const [thresholds, setThresholds] = useState([]);
    const [draft, setDraft] = useState(DEFAULT_THRESHOLD);
    const [adding, setAdding] = useState(false);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        let cancelled = false;
        api.getFleetThresholds()
            .then((data) => { if (!cancelled) setThresholds(Array.isArray(data) ? data : []); })
            .catch(() => { if (!cancelled) setThresholds([]); });
        return () => { cancelled = true; };
    }, [refreshKey, reloadKey]);

    const reload = () => setReloadKey((k) => k + 1);

    const saveThreshold = async () => {
        try {
            await api.createFleetThreshold(draft);
            toast.success('Threshold saved');
            setDraft(DEFAULT_THRESHOLD);
            setAdding(false);
            reload();
        } catch {
            toast.error('Failed to save threshold');
        }
    };

    const removeThreshold = async (id) => {
        try {
            await api.deleteFleetThreshold(id);
            reload();
        } catch {
            toast.error('Failed to delete threshold');
        }
    };

    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-fleet-thresholds-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-fleet-thresholds-cols' });

    // Columns for the shared DataTable; cell markup is identical to the
    // hand-rolled table it replaces (.sk-cell-mono, .mon-row-actions).
    const thresholdColumns = [
        {
            key: 'applies',
            header: 'Applies to',
            sortable: true,
            hideable: false,
            sortValue: (t) => t.server_name || 'Every server',
            render: (t) => t.server_name || 'Every server',
        },
        {
            key: 'metric',
            header: 'Metric',
            sortable: true,
            sortValue: (t) => METRIC_LABELS[t.metric] || t.metric,
            render: (t) => METRIC_LABELS[t.metric] || t.metric,
        },
        {
            key: 'warning',
            header: 'Warning',
            sortable: true,
            sortValue: (t) => t.warning_threshold ?? null,
            cellClassName: 'sk-cell-mono',
            render: (t) => `${t.warning_threshold}%`,
        },
        {
            key: 'critical',
            header: 'Critical',
            sortable: true,
            sortValue: (t) => t.critical_threshold ?? null,
            cellClassName: 'sk-cell-mono',
            render: (t) => `${t.critical_threshold}%`,
        },
        {
            key: 'sustained',
            header: 'Sustained',
            sortable: true,
            sortValue: (t) => t.duration_seconds ?? null,
            cellClassName: 'sk-cell-mono',
            render: (t) => `${t.duration_seconds}s`,
        },
        {
            key: 'actions',
            header: '',
            sortable: false,
            hideable: false,
            cellClassName: 'mon-row-actions',
            render: (t) => (
                <Button variant="ghost" size="sm" onClick={() => removeThreshold(t.id)}>
                    <XCircle size={14} />
                </Button>
            ),
        },
    ];

    return (
        <section className="monitoring-panel">
            <div className="monitoring-panel__header">
                <div>
                    <h3>Per-server rules</h3>
                    <span className="mon-panel-sub">Limits applied to paired servers by their agents</span>
                </div>
                <div>
                    <Button size="sm" variant={adding ? 'outline' : 'default'} onClick={() => setAdding((v) => !v)}>
                        <Plus size={14} /> {adding ? 'Cancel' : 'Add rule'}
                    </Button>
                </div>
            </div>

            {adding && (
                <div className="mon-threshold-form">
                    <div className="form-group">
                        <Label htmlFor="fleet-threshold-server">Applies to</Label>
                        <select
                            id="fleet-threshold-server"
                            value={draft.server_id || ''}
                            onChange={(e) => setDraft((p) => ({ ...p, server_id: e.target.value || undefined }))}
                        >
                            <option value="">Every server (fleet default)</option>
                            {servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                        </select>
                    </div>
                    <div className="form-group">
                        <Label htmlFor="fleet-threshold-metric">Metric</Label>
                        <select
                            id="fleet-threshold-metric"
                            value={draft.metric}
                            onChange={(e) => setDraft((p) => ({ ...p, metric: e.target.value }))}
                        >
                            <option value="cpu">CPU</option>
                            <option value="memory">Memory</option>
                            <option value="disk">Disk</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <Label htmlFor="fleet-threshold-warning">Warning (%)</Label>
                        <Input
                            id="fleet-threshold-warning"
                            type="number"
                            value={draft.warning_threshold}
                            onChange={(e) => setDraft((p) => ({ ...p, warning_threshold: parseFloat(e.target.value) || 80 }))}
                        />
                    </div>
                    <div className="form-group">
                        <Label htmlFor="fleet-threshold-critical">Critical (%)</Label>
                        <Input
                            id="fleet-threshold-critical"
                            type="number"
                            value={draft.critical_threshold}
                            onChange={(e) => setDraft((p) => ({ ...p, critical_threshold: parseFloat(e.target.value) || 95 }))}
                        />
                    </div>
                    <div className="form-group">
                        <Label htmlFor="fleet-threshold-duration">Sustained for (s)</Label>
                        <Input
                            id="fleet-threshold-duration"
                            type="number"
                            value={draft.duration_seconds}
                            onChange={(e) => setDraft((p) => ({ ...p, duration_seconds: parseInt(e.target.value, 10) || 300 }))}
                        />
                    </div>
                    <Button size="sm" onClick={saveThreshold}>Save rule</Button>
                </div>
            )}

            {thresholds.length > 0 ? (
                <DataTable
                    columns={thresholdColumns}
                    data={thresholds}
                    keyField="id"
                    sorts={sorts}
                    onSortsChange={setSorts}
                    hiddenKeys={hiddenKeys}
                    onHiddenKeysChange={setHiddenKeys}
                    className="mon-table-scroll"
                    footer={(
                        <DataTableFooter
                            shown={thresholds.length}
                            total={thresholds.length}
                            noun="rule"
                        />
                    )}
                />
            ) : (
                <p className="mon-panel-hint">
                    No per-server rules yet — paired servers fall back to their agent defaults.
                </p>
            )}
        </section>
    );
}
