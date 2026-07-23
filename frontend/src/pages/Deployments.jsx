import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    CheckCircle2,
    XCircle,
    Clock,
    RefreshCw,
    Server,
    Loader2,
    PlayCircle,
    FlaskConical,
} from 'lucide-react';
import api from '../services/api';
import { StatStrip, Stat } from '../components/StatCard';
import Modal from '../components/Modal';
import Skeleton from '../components/Skeleton';
import { Button } from '@/components/ui/button';
import { useTopbarActions } from '@/hooks/useTopbarActions';

const STATUS_ICONS = {
    pending: Clock,
    running: Loader2,
    succeeded: CheckCircle2,
    failed: XCircle,
};

const KIND_LABELS = {
    app_deploy: 'App deploy',
    template_install: 'Template install',
    demo_deploy: 'Test (simulated)',
};

const formatTime = (iso) => {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
};

const StatusBadge = ({ status }) => {
    const cls = STATUS_ICONS[status] ? status : 'pending';
    const Icon = STATUS_ICONS[cls];
    return (
        <span className={`deployments-page__status-badge deployments-page__status-badge--${cls}`}>
            <Icon size={14} className={cls === 'running' ? 'deployments-page__spin' : ''} />
            {status}
        </span>
    );
};

const Deployments = () => {
    const navigate = useNavigate();
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('all');
    const [serverFilter, setServerFilter] = useState('all');
    const [servers, setServers] = useState([]);
    const [autoRefresh, setAutoRefresh] = useState(true);
    const refreshRef = useRef(null);

    // Simulated deployments (dev-only): null until the backend confirms the
    // gate is on — a 404 (production) simply keeps the trigger hidden.
    const [simInfo, setSimInfo] = useState(null);
    const [simOpen, setSimOpen] = useState(false);
    const [simSpeed, setSimSpeed] = useState('fast');
    const [simBusy, setSimBusy] = useState(null);

    const loadJobs = async () => {
        try {
            const params = {};
            if (statusFilter !== 'all') params.status = statusFilter;
            if (serverFilter !== 'all') params.serverId = serverFilter;
            const data = await api.getDeploymentJobs(params);
            setJobs(data.jobs || []);
        } catch (err) {
            console.error('Failed to load deployment jobs', err);
        } finally {
            setLoading(false);
        }
    };

    const loadServers = async () => {
        try {
            const data = await api.getAvailableServers();
            setServers(Array.isArray(data) ? data : []);
        } catch {
            setServers([]);
        }
    };

    useEffect(() => {
        loadServers();
        api.getDeploySimulateInfo()
            .then((data) => setSimInfo(data?.enabled ? data : null))
            .catch(() => setSimInfo(null));
    }, []);

    const runScenario = async (scenarioId) => {
        setSimBusy(scenarioId);
        try {
            const res = await api.simulateDeployment(scenarioId, simSpeed);
            if (res?.job_id) navigate(`/deployments/${res.job_id}`);
        } catch (err) {
            console.error('Failed to start test deployment', err);
            setSimBusy(null);
        }
    };

    useEffect(() => {
        loadJobs();
    }, [statusFilter, serverFilter]);

    useEffect(() => {
        if (refreshRef.current) clearInterval(refreshRef.current);
        if (!autoRefresh) return undefined;
        refreshRef.current = setInterval(loadJobs, 3000);
        return () => clearInterval(refreshRef.current);
    }, [autoRefresh, statusFilter, serverFilter]);

    const summary = useMemo(() => {
        const counts = { running: 0, succeeded: 0, failed: 0, pending: 0 };
        jobs.forEach((j) => {
            counts[j.status] = (counts[j.status] || 0) + 1;
        });
        return counts;
    }, [jobs]);

    useTopbarActions(() =>
        <>
            {simInfo?.enabled && (
                <Button variant="outline" size="sm" onClick={() => setSimOpen(true)}>
                    <FlaskConical size={16} />
                    Test deployment
                </Button>
            )}
            <Button
                variant={autoRefresh ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAutoRefresh((v) => !v)}
                title="Auto-refresh every 3s"
            >
                <RefreshCw size={16} className={autoRefresh ? 'spin' : ''} />
                {autoRefresh ? 'Live' : 'Paused'}
            </Button>
            <Button variant="outline" size="sm" onClick={loadJobs}>
                <RefreshCw size={16} /> Refresh
            </Button>
        </>,
        [autoRefresh, simInfo?.enabled]
    );

    return (
        <div className="sk-tabgroup__inner deployments-page">
            <StatStrip ariaLabel="Deployment summary">
                <Stat label="Running" value={summary.running} state={summary.running > 0 ? 'info' : undefined} />
                <Stat label="Succeeded" value={summary.succeeded} state={summary.succeeded > 0 ? 'success' : undefined} />
                <Stat label="Failed" value={summary.failed} state={summary.failed > 0 ? 'danger' : undefined} />
                <Stat label="Pending" value={summary.pending} />
            </StatStrip>

            <div className="deployments-page__toolbar">
                <div className="deployments-page__filter">
                    <label>Status</label>
                    <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                        <option value="all">All</option>
                        <option value="pending">Pending</option>
                        <option value="running">Running</option>
                        <option value="succeeded">Succeeded</option>
                        <option value="failed">Failed</option>
                    </select>
                </div>
                <div className="deployments-page__filter">
                    <label>Target server</label>
                    <select value={serverFilter} onChange={(e) => setServerFilter(e.target.value)}>
                        <option value="all">All servers</option>
                        {servers.map((s) => (
                            <option key={s.id} value={s.id}>
                                {s.name}{s.is_local ? ' (local)' : ''}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="deployments-page__panel deployments-page__jobs-panel">
                <div className="deployments-page__panel-header">
                    <div>
                        <h2>Jobs</h2>
                        <span>{jobs.length} visible</span>
                    </div>
                </div>
                {loading ? (
                    <div className="deployments-page__loading" aria-busy="true">
                        {[0, 1, 2, 3].map((i) => (
                            <div key={i} className="deployments-page__loading-row">
                                <Skeleton variant="line" width={96} />
                                <Skeleton variant="line" width="34%" />
                                <Skeleton variant="line" width="20%" />
                                <Skeleton variant="line" width="26%" />
                            </div>
                        ))}
                    </div>
                ) : jobs.length === 0 ? (
                    <div className="deployments-page__empty">
                        <PlayCircle size={34} />
                        <strong>No deployment jobs yet</strong>
                        <span>
                            Create a service from a repository or install a template to see activity here.
                        </span>
                    </div>
                ) : (
                    <table className="deployments-page__jobs-table">
                        <thead>
                            <tr>
                                <th>Status</th>
                                <th>Kind</th>
                                <th>Target</th>
                                <th>App</th>
                                <th>Progress</th>
                                <th>Started</th>
                            </tr>
                        </thead>
                        <tbody>
                            {jobs.map((job) => (
                                <tr
                                    key={job.id}
                                    onClick={() => navigate(`/deployments/${job.id}`)}
                                    title="Open the Deploy Console"
                                >
                                    <td><StatusBadge status={job.status} /></td>
                                    <td>{KIND_LABELS[job.kind] || job.kind}</td>
                                    <td>
                                        <span className="deployments-page__server-cell">
                                            <Server size={12} />
                                            {job.target_server_name || 'Local server'}
                                        </span>
                                    </td>
                                    <td>{job.app_name || '—'}</td>
                                    <td>
                                        <div className="deployments-page__progress">
                                            <div
                                                className={`deployments-page__progress-fill${job.status === 'failed' ? ' deployments-page__progress-fill--failed' : ''}`}
                                                style={{ width: `${job.progress_percent || 0}%` }}
                                            />
                                        </div>
                                        <div className="deployments-page__progress-meta">
                                            {job.current_step || 0}/{job.total_steps || 0}
                                        </div>
                                    </td>
                                    <td className="deployments-page__time-cell">{formatTime(job.started_at || job.created_at)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            <Modal
                open={simOpen}
                onClose={() => setSimOpen(false)}
                title="Run a test deployment"
                size="md"
            >
                <p className="deployments-page__sim-intro">
                    Streams scripted output through the real deploy pipeline — no
                    containers, files, or servers are touched. Development only.
                </p>
                <label className="deployments-page__sim-speed">
                    Speed
                    <select value={simSpeed} onChange={(e) => setSimSpeed(e.target.value)}>
                        <option value="fast">Fast</option>
                        <option value="realtime">Realtime</option>
                    </select>
                </label>
                <div className="deployments-page__sim-list">
                    {(simInfo?.scenarios || []).map((s) => (
                        <button
                            key={s.id}
                            type="button"
                            className="deployments-page__sim-scenario"
                            onClick={() => runScenario(s.id)}
                            disabled={simBusy !== null}
                        >
                            <span className="deployments-page__sim-scenario-text">
                                <strong>{s.name}</strong>
                                <span>{s.description}</span>
                            </span>
                            {simBusy === s.id && (
                                <Loader2 size={15} className="deployments-page__spin" />
                            )}
                        </button>
                    ))}
                </div>
            </Modal>
        </div>
    );
};

export default Deployments;
