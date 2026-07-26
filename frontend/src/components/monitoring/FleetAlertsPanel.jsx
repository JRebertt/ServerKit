import { useState, useEffect } from 'react';
import { CheckCircle, Eye } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Pill, SegControl } from '@/components/ds';
import { METRIC_LABELS } from './fleetMetrics';

const ALERT_FILTERS = [
    { value: 'active', label: 'Active' },
    { value: 'acknowledged', label: 'Acknowledged' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'all', label: 'All' },
];

// Alerts raised by per-server thresholds across the fleet. The panel host's own
// alerts are a different system (a single set of limits, delivered by the
// monitoring scheduler) and sit above this on the Alerts tab; the limits behind
// these rows are edited on the Rules tab.
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

    return (
        <section className="monitoring-panel">
            <div className="monitoring-panel__header">
                <h3>Fleet alerts</h3>
                <SegControl value={filter} onChange={setFilter} options={ALERT_FILTERS} />
            </div>

            {alerts.length > 0 ? (
                <div className="mon-table-scroll">
                    <table className="sk-dtable">
                        <thead>
                            <tr>
                                <th>Server</th>
                                <th>Metric</th>
                                <th>Value</th>
                                <th>Threshold</th>
                                <th>Severity</th>
                                <th>Status</th>
                                <th>Time</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {alerts.map((a) => (
                                <tr key={a.id}>
                                    <td>{a.server_name}</td>
                                    <td>{METRIC_LABELS[a.metric] || a.metric}</td>
                                    <td className="sk-cell-mono">{a.value}%</td>
                                    <td className="sk-cell-mono">{a.threshold}%</td>
                                    <td><Pill kind={a.severity === 'critical' ? 'red' : 'amber'}>{a.severity}</Pill></td>
                                    <td>
                                        <Pill kind={a.status === 'active' ? 'red' : a.status === 'acknowledged' ? 'amber' : 'green'}>
                                            {a.status}
                                        </Pill>
                                    </td>
                                    <td>{new Date(a.created_at).toLocaleString()}</td>
                                    <td className="mon-row-actions">
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
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
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
