import { useEffect, useState } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import Modal from '@/components/Modal';
import { Pill } from '@/components/ds';
import EmptyState from '../EmptyState';
import { ChevronDown, ChevronRight, Stethoscope, Wrench } from 'lucide-react';

const STATUS_TONE = { ok: 'green', warn: 'amber', fail: 'red' };

function formatRanAt(ranAt) {
    if (!ranAt) return null;
    return new Date(ranAt).toLocaleString();
}

const DoctorPanel = () => {
    const toast = useToast();
    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(true);
    const [running, setRunning] = useState(false);
    const [repairing, setRepairing] = useState(false);
    const [expanded, setExpanded] = useState({});
    // { items: [repair_ref...], title, diff } — pending confirmation.
    const [confirm, setConfirm] = useState(null);

    useEffect(() => {
        let cancelled = false;
        api.getDoctorReport()
            .then((res) => { if (!cancelled) setReport(res.report); })
            .catch(() => { /* no stored report yet — the empty state covers it */ })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, []);

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

    const doRepair = async (items) => {
        try {
            setRepairing(true);
            const res = await api.repairDoctorItems(items);
            const failed = (res.results || []).filter((r) => !r.success);
            if (failed.length > 0) {
                toast.error(`${failed.length} repair${failed.length !== 1 ? 's' : ''} failed — ${failed[0].error || 'see report'}`);
            } else {
                toast.success(`Repaired ${items.length} item${items.length !== 1 ? 's' : ''}`);
            }
            // Re-diagnose so the list reflects the new on-disk state.
            const fresh = await api.runDoctor();
            setReport(fresh.report);
        } catch (err) {
            toast.error(err.message || 'Repair failed');
        } finally {
            setRepairing(false);
            setConfirm(null);
        }
    };

    const checks = report?.checks || [];
    const repairable = checks.filter((c) => c.repairable && c.repair_ref);

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
                            <article key={check.key} className={`doctor-check doctor-check--${check.status}`}>
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
                                            onClick={() => toggleDiff(check.key)}
                                        >
                                            {expanded[check.key] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                            diff
                                        </Button>
                                    )}
                                    {check.repairable && check.repair_ref && (
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            disabled={repairing || running}
                                            onClick={() => setConfirm({
                                                items: [check.repair_ref],
                                                title: `Repair "${check.title}"?`,
                                                diff: check.diff || null,
                                            })}
                                        >
                                            <Wrench size={13} />
                                            Repair
                                        </Button>
                                    )}
                                </div>
                                {check.diff && expanded[check.key] && (
                                    <pre className="doctor-diff">{check.diff}</pre>
                                )}
                            </article>
                        ))}
                    </div>
                )}
            </section>

            <Modal
                open={Boolean(confirm)}
                onClose={() => setConfirm(null)}
                title={confirm?.title}
                className="doctor-confirm"
            >
                <p className="sk-modal__subtitle">
                    This rewrites the managed file(s) from ServerKit&apos;s configuration and
                    reloads the affected service. Manual edits to those files will be lost.
                </p>
                {confirm?.diff && (
                    <pre className="doctor-diff doctor-diff--modal">{confirm.diff}</pre>
                )}
                <div className="doctor-confirm__actions">
                    <Button variant="outline" onClick={() => setConfirm(null)} disabled={repairing}>
                        Cancel
                    </Button>
                    <Button onClick={() => doRepair(confirm.items)} disabled={repairing}>
                        <Wrench size={14} />
                        {repairing ? 'Repairing...' : 'Repair'}
                    </Button>
                </div>
            </Modal>
        </div>
    );
};

export default DoctorPanel;
