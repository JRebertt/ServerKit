import { useState, useEffect } from 'react';
import { Plus, XCircle } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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

    return (
        <section className="monitoring-panel">
            <div className="monitoring-panel__header">
                <div>
                    <h3>Per-server rules</h3>
                    <span className="mon-panel-sub">Limits applied to paired servers by their agents</span>
                </div>
                <Button size="sm" variant={adding ? 'outline' : 'default'} onClick={() => setAdding((v) => !v)}>
                    <Plus size={14} /> {adding ? 'Cancel' : 'Add rule'}
                </Button>
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
                <div className="mon-table-scroll">
                    <table className="sk-dtable">
                        <thead>
                            <tr>
                                <th>Applies to</th>
                                <th>Metric</th>
                                <th>Warning</th>
                                <th>Critical</th>
                                <th>Sustained</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {thresholds.map((t) => (
                                <tr key={t.id}>
                                    <td>{t.server_name || 'Every server'}</td>
                                    <td>{METRIC_LABELS[t.metric] || t.metric}</td>
                                    <td className="sk-cell-mono">{t.warning_threshold}%</td>
                                    <td className="sk-cell-mono">{t.critical_threshold}%</td>
                                    <td className="sk-cell-mono">{t.duration_seconds}s</td>
                                    <td className="mon-row-actions">
                                        <Button variant="ghost" size="sm" onClick={() => removeThreshold(t.id)}>
                                            <XCircle size={14} />
                                        </Button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : (
                <p className="mon-panel-hint">
                    No per-server rules yet — paired servers fall back to their agent defaults.
                </p>
            )}
        </section>
    );
}
