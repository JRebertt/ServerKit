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
import { Drawer, KpiBand, ListToolbar, MetricCard, Pill, SegControl } from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { IMPACT_TONE, INCIDENT_STATES } from '../components/monitoring/monitorShared';

const FILTERS = [
    { value: 'active', label: 'Active' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'all', label: 'All' },
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
    const [filter, setFilter] = useState('active');
    const [incidents, setIncidents] = useState([]);
    const [activeAlerts, setActiveAlerts] = useState([]);
    const [alertHistory, setAlertHistory] = useState([]);
    const [monitors, setMonitors] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState(null);
    const [note, setNote] = useState('');
    const [checking, setChecking] = useState(false);
    const [hasFleet, setHasFleet] = useState(false);

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
        </>
    ), [checking, load]);

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

    const shown = items.filter((item) => (
        filter === 'all' || (filter === 'active' ? !item.resolved : item.resolved)
    ));

    const activeCount = items.filter((i) => !i.resolved).length;
    const openIncidents = incidents.filter((i) => i.status !== 'resolved').length;

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
            <KpiBand>
                <MetricCard
                    label="Active" value={activeCount} tone={activeCount ? 'red' : 'green'} compact
                    icon={<AlertTriangle size={17} />} onClick={() => setFilter('active')}
                />
                <MetricCard
                    label="Open incidents" value={openIncidents} tone="amber" compact
                    icon={<Radar size={17} />}
                />
                <MetricCard
                    label="Host alerts firing" value={activeAlerts.length} tone="cyan" compact
                    icon={<Siren size={17} />}
                />
                <MetricCard
                    label="Resolved (recent)" value={items.filter((i) => i.resolved).length} tone="green" compact
                    icon={<CheckCircle2 size={17} />} onClick={() => setFilter('resolved')}
                />
            </KpiBand>

            <ListToolbar
                filters={<SegControl value={filter} onChange={setFilter} options={FILTERS} />}
                count={<>{shown.length} shown · monitor outages and host threshold alerts</>}
            />

            {shown.length === 0 ? (
                <EmptyState
                    icon={CheckCircle2}
                    title={filter === 'active' ? 'Nothing is wrong right now' : 'Nothing here'}
                    description={filter === 'active'
                        ? 'No monitor is down and no host is over its limit.'
                        : `No ${filter} incidents or alerts recorded.`}
                />
            ) : (
                <div className="incidents-list">
                    {shown.map((item) => (
                        <button
                            key={item.key}
                            type="button"
                            className="incident-row"
                            onClick={() => setSelected(item)}
                        >
                            <span className={`incident-row__sev incident-row__sev--${item.tone}`} />
                            <span className="incident-row__body">
                                <span className="incident-row__title">
                                    {item.title}
                                    <Pill kind={item.tone}>{item.state}</Pill>
                                </span>
                                <span className="incident-row__sub">
                                    {item.subject} · {formatWhen(item.when)}
                                    {item.kind === 'alert' && item.raw.type
                                        ? ` · ${item.raw.type} ${formatValue(item.raw.value)} / ${item.raw.threshold}`
                                        : ''}
                                </span>
                            </span>
                            <ChevronRight size={16} className="incident-row__chev" />
                        </button>
                    ))}
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
        </div>
    );
}
