import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import Modal from '@/components/Modal';
import { Pill } from '@/components/ds';
import EmptyState from '../EmptyState';
import { ChevronDown, ChevronRight, Server, Stethoscope, Wrench } from 'lucide-react';
import { usePolling } from '@/hooks/usePolling';

const STATUS_TONE = { ok: 'green', warn: 'amber', fail: 'red', error: 'red' };

// The fleet sweep fans out across agents over the network, so it is a job
// (202 + job id) rather than a synchronous call — poll it to completion.
const SWEEP_POLL_MS = 3000;
const TERMINAL_JOB_STATUSES = ['succeeded', 'failed', 'cancelled'];

function formatRanAt(ranAt) {
    if (!ranAt) return null;
    return new Date(ranAt).toLocaleString();
}

/**
 * One finding. Rendering is driven entirely by the row's own fields
 * (`status` / `diff` / `repairable` + `repair_ref`), which is why the host
 * doctor and the fleet doctor can share it — a fleet check is the same shape,
 * its repair_ref just names a server.
 */
function DoctorCheck({ check, expanded, onToggleDiff, onRepair, disabled }) {
    return (
        <article className={`doctor-check doctor-check--${check.status}`}>
            <div className="doctor-check__row">
                <Pill kind={STATUS_TONE[check.status] || 'gray'}>{check.status}</Pill>
                <div className="doctor-check__body">
                    <span className="doctor-check__title">{check.title}</span>
                    <span className="doctor-check__detail">{check.detail}</span>
                </div>
                {check.diff && (
                    <Button
                        size="sm"
                        variant="ghost"
                        className="doctor-check__difftoggle"
                        onClick={onToggleDiff}
                    >
                        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        diff
                    </Button>
                )}
                {check.repairable && check.repair_ref && (
                    <Button size="sm" variant="outline" disabled={disabled} onClick={onRepair}>
                        <Wrench size={13} />
                        Repair
                    </Button>
                )}
            </div>
            {check.diff && expanded && <pre className="doctor-diff">{check.diff}</pre>}
        </article>
    );
}

const DoctorPanel = () => {
    const toast = useToast();
    const navigate = useNavigate();
    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(true);
    const [running, setRunning] = useState(false);
    const [repairing, setRepairing] = useState(false);
    const [expanded, setExpanded] = useState({});
    // { items: [repair_ref...], title, diff, scope } — pending confirmation.
    // `scope` picks the repair endpoint: 'host' (panel box) or 'fleet' (agent).
    const [confirm, setConfirm] = useState(null);

    const [fleet, setFleet] = useState(null);
    const [fleetLoading, setFleetLoading] = useState(true);
    const [sweeping, setSweeping] = useState(false);
    const [sweepJobId, setSweepJobId] = useState(null);

    const loadFleet = useCallback(async () => {
        try {
            const res = await api.getFleetDoctorReport();
            setFleet(res.report);
        } catch {
            // Admin-only endpoint; the empty state covers a missing report.
            setFleet(null);
        } finally {
            setFleetLoading(false);
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        api.getDoctorReport()
            .then((res) => { if (!cancelled) setReport(res.report); })
            .catch(() => { /* no stored report yet — the empty state covers it */ })
            .finally(() => { if (!cancelled) setLoading(false); });
        loadFleet();
        return () => { cancelled = true; };
    }, [loadFleet]);

    const runDiagnosis = async () => {
        try {
            setRunning(true);
            const res = await api.runDoctor();
            setReport(res.report);
            const bad = (res.report?.checks || []).filter((c) => c.status !== 'ok').length;
            toast[bad > 0 ? 'warning' : 'success'](
                bad > 0 ? `Diagnosis finished — ${bad} finding${bad !== 1 ? 's' : ''}` : 'Diagnosis finished — all clear'
            );
        } catch (err) {
            toast.error(err.message || 'Diagnosis failed');
        } finally {
            setRunning(false);
        }
    };

    // The job id IS the "are we polling" state, so the poll is declarative and
    // the hook owns starting, stopping, and not overlapping ticks.
    const pollSweep = useCallback((jobId) => setSweepJobId(jobId), []);

    usePolling(async () => {
        try {
            const res = await api.getJob(sweepJobId);
            const job = res.job || res;
            if (!TERMINAL_JOB_STATUSES.includes(job.status)) return;
            setSweepJobId(null);
            setSweeping(false);
            if (job.status === 'succeeded') {
                await loadFleet();
                toast.success('Fleet sweep finished');
            } else {
                toast.error(job.error_message || 'Fleet sweep did not finish');
            }
        } catch {
            // Transient poll failure — the next tick retries.
        }
    }, SWEEP_POLL_MS, { enabled: Boolean(sweepJobId), immediate: false });

    const runSweep = async () => {
        try {
            setSweeping(true);
            const res = await api.runFleetSweep();
            toast.info('Fleet sweep queued — probing every connected agent');
            pollSweep(res.job_id);
        } catch (err) {
            setSweeping(false);
            toast.error(err.message || 'Could not queue the fleet sweep');
        }
    };

    const doRepair = async ({ items, scope }) => {
        try {
            setRepairing(true);
            const res = scope === 'fleet'
                ? await api.repairFleetItems(items)
                : await api.repairDoctorItems(items);
            const results = res.results || [];
            const failed = results.filter((r) => !r.success);
            // Some repairs run as a background job rather than inline — a
            // restore drill, for one. Those have been QUEUED, not completed,
            // and reporting them as "repaired" would claim an outcome that
            // has not happened yet.
            const queued = results.filter((r) => r.success && r.job_id);
            if (failed.length > 0) {
                toast.error(`${failed.length} repair${failed.length !== 1 ? 's' : ''} failed — ${failed[0].error || 'see report'}`);
            } else if (queued.length > 0) {
                toast.success(
                    `Started ${queued.length} background job${queued.length !== 1 ? 's' : ''} — the repair finishes there`,
                    {
                        duration: 10000,
                        action: { label: 'View jobs', onClick: () => navigate('/monitoring/jobs') },
                    },
                );
            } else {
                toast.success(`Repaired ${items.length} item${items.length !== 1 ? 's' : ''}`);
            }
            if (scope === 'fleet') {
                // Rows only change when a sweep re-probes; re-read what we have.
                await loadFleet();
            } else {
                // Re-diagnose so the list reflects the new on-disk state.
                const fresh = await api.runDoctor();
                setReport(fresh.report);
            }
        } catch (err) {
            toast.error(err.message || 'Repair failed');
        } finally {
            setRepairing(false);
            setConfirm(null);
        }
    };

    const checks = report?.checks || [];
    const repairable = checks.filter((c) => c.repairable && c.repair_ref);
    const fleetServers = fleet?.servers || [];

    const toggleDiff = (key) => {
        setExpanded((cur) => ({ ...cur, [key]: !cur[key] }));
    };

    return (
        <div className="doctor-panel">
            <section className="monitoring-panel">
                <div className="monitoring-panel__header">
                    <h3>Server Doctor</h3>
                    <div className="doctor-panel__actions">
                        {repairable.length > 0 && (
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={repairing || running}
                                onClick={() => setConfirm({
                                    items: repairable.map((c) => c.repair_ref),
                                    title: `Repair all ${repairable.length} repairable items?`,
                                    diff: null,
                                    scope: 'host',
                                })}
                            >
                                <Wrench size={14} />
                                Repair all ({repairable.length})
                            </Button>
                        )}
                        <Button size="sm" onClick={runDiagnosis} disabled={running || repairing}>
                            <Stethoscope size={14} />
                            {running ? 'Diagnosing...' : 'Run diagnosis'}
                        </Button>
                    </div>
                </div>

                <p className="doctor-panel__blurb">
                    One sweep across managed configuration drift, core services, certificates,
                    disk headroom and the database. Nothing is repaired automatically — every
                    fix is a button you press.
                    {report?.ran_at && <span className="doctor-panel__ranat"> Last run {formatRanAt(report.ran_at)}.</span>}
                </p>

                {loading ? (
                    <EmptyState loading loadingVariant="detail" title="Loading last report" />
                ) : checks.length === 0 ? (
                    <EmptyState
                        icon={Stethoscope}
                        title="No diagnosis yet"
                        description="Run a diagnosis to check this server's managed configuration and core health."
                    />
                ) : (
                    <div className="doctor-check-list">
                        {checks.map((check) => (
                            <DoctorCheck
                                key={check.key}
                                check={check}
                                expanded={Boolean(expanded[check.key])}
                                disabled={repairing || running}
                                onToggleDiff={() => toggleDiff(check.key)}
                                onRepair={() => setConfirm({
                                    items: [check.repair_ref],
                                    title: `Repair "${check.title}"?`,
                                    diff: check.diff || null,
                                    scope: 'host',
                                })}
                            />
                        ))}
                    </div>
                )}
            </section>

            <section className="monitoring-panel">
                <div className="monitoring-panel__header">
                    <h3>Fleet Doctor</h3>
                    <div className="doctor-panel__actions">
                        <Button size="sm" onClick={runSweep} disabled={sweeping || repairing}>
                            <Stethoscope size={14} />
                            {sweeping ? 'Sweeping...' : 'Run fleet sweep'}
                        </Button>
                    </div>
                </div>

                <p className="doctor-panel__blurb">
                    The same health sweep across every paired server. It runs as a background
                    job because it talks to each agent over the network; a server that is
                    offline keeps its last known findings instead of dropping out.
                    {fleet?.ran_at && <span className="doctor-panel__ranat"> Last sweep {formatRanAt(fleet.ran_at)}.</span>}
                </p>

                {fleetLoading ? (
                    <EmptyState loading loadingVariant="cards" title="Loading fleet report" />
                ) : fleetServers.length === 0 ? (
                    <EmptyState
                        icon={Server}
                        title="No servers in the fleet"
                        description="Pair an agent from Servers to include that box in the fleet sweep."
                    />
                ) : (
                    fleetServers.map((entry) => (
                        <div key={entry.server_id} className="doctor-fleet-group">
                            <div className="doctor-fleet-group__head">
                                <span className="doctor-fleet-group__name">{entry.name}</span>
                                <Pill kind={entry.connected ? 'green' : 'gray'}>
                                    {entry.connected ? 'connected' : 'offline'}
                                </Pill>
                                {entry.hostname && (
                                    <span className="doctor-fleet-group__host">{entry.hostname}</span>
                                )}
                                <div className="doctor-fleet-group__counts">
                                    {['fail', 'warn', 'ok'].map((status) => (
                                        entry.counts?.[status] > 0 && (
                                            <span key={status} className="doctor-fleet-group__count">
                                                {entry.counts[status]} {status}
                                            </span>
                                        )
                                    ))}
                                </div>
                            </div>

                            {entry.checks.length === 0 ? (
                                <p className="doctor-fleet-group__hint">
                                    No sweep results yet for this server.
                                </p>
                            ) : (
                                <div className="doctor-check-list">
                                    {entry.checks.map((check) => {
                                        const rowKey = `${entry.server_id}:${check.key}`;
                                        return (
                                            <DoctorCheck
                                                key={rowKey}
                                                check={check}
                                                expanded={Boolean(expanded[rowKey])}
                                                disabled={repairing || sweeping}
                                                onToggleDiff={() => toggleDiff(rowKey)}
                                                onRepair={() => setConfirm({
                                                    items: [check.repair_ref],
                                                    title: `Repair "${check.title}" on ${entry.name}?`,
                                                    diff: check.diff || null,
                                                    scope: 'fleet',
                                                })}
                                            />
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    ))
                )}
            </section>

            <Modal
                open={Boolean(confirm)}
                onClose={() => setConfirm(null)}
                title={confirm?.title}
                className="doctor-confirm"
            >
                <p className="sk-modal__subtitle">
                    {confirm?.scope === 'fleet'
                        ? 'This restarts the service on the remote server through its agent. The action is allowlisted and written to the audit log.'
                        : 'This rewrites the managed file(s) from ServerKit\'s configuration and reloads the affected service. Manual edits to those files will be lost.'}
                </p>
                {confirm?.diff && (
                    <pre className="doctor-diff doctor-diff--modal">{confirm.diff}</pre>
                )}
                <div className="doctor-confirm__actions">
                    <Button variant="outline" onClick={() => setConfirm(null)} disabled={repairing}>
                        Cancel
                    </Button>
                    <Button onClick={() => doRepair(confirm)} disabled={repairing}>
                        <Wrench size={14} />
                        {repairing ? 'Repairing...' : 'Repair'}
                    </Button>
                </div>
            </Modal>
        </div>
    );
};

export default DoctorPanel;
