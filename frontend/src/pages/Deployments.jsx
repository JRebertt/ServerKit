import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    CheckCircle2,
    XCircle,
    Clock,
    RefreshCw,
    Loader2,
    PlayCircle,
    FlaskConical,
    ChevronRight,
} from 'lucide-react';
import api from '../services/api';
import Modal from '../components/Modal';
import Skeleton from '../components/Skeleton';
import { Button } from '@/components/ui/button';
import { SegControl, SearchField } from '@/components/ds';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import {
    KIND_CHIP,
    stepTicks,
    sourceRef,
    formatDuration,
    relativeTime,
    groupDeploys,
} from '../utils/deployActivity';

const STATE_ICON = {
    succeeded: { Icon: CheckCircle2, cls: 'succeeded' },
    failed: { Icon: XCircle, cls: 'failed' },
    running: { Icon: Loader2, cls: 'running' },
    pending: { Icon: Clock, cls: 'pending' },
};

const STATUS_FILTERS = [
    ['all', 'All'],
    ['running', 'Running'],
    ['succeeded', 'Succeeded'],
    ['failed', 'Failed'],
];

const Deployments = () => {
    const navigate = useNavigate();
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('all');
    const [serverFilter, setServerFilter] = useState('all');
    const [search, setSearch] = useState('');
    const [servers, setServers] = useState([]);
    const [autoRefresh, setAutoRefresh] = useState(true);
    const refreshRef = useRef(null);

    // Simulated deployments (dev-only): null until the backend confirms the
    // gate is on — a 404 (production) simply keeps the trigger hidden.
    const [simInfo, setSimInfo] = useState(null);
    const [simOpen, setSimOpen] = useState(false);
    const [simSpeed, setSimSpeed] = useState('fast');
    const [simBusy, setSimBusy] = useState(null);

    // Status is filtered client-side so the segmented control can show a live
    // count per state; only the server filter narrows the query.
    const loadJobs = async () => {
        try {
            const params = { limit: 100 };
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
    }, [serverFilter]);

    useEffect(() => {
        if (refreshRef.current) clearInterval(refreshRef.current);
        if (!autoRefresh) return undefined;
        refreshRef.current = setInterval(loadJobs, 3000);
        return () => clearInterval(refreshRef.current);
    }, [autoRefresh, serverFilter]);

    // Search narrows the set the counts are taken from, so the numbers always
    // describe what a click on that filter would actually show.
    const searched = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return jobs;
        return jobs.filter((j) =>
            (j.app_name || '').toLowerCase().includes(q)
            || (sourceRef(j) || '').toLowerCase().includes(q)
            || (j.target_server_name || '').toLowerCase().includes(q)
        );
    }, [jobs, search]);

    const counts = useMemo(() => {
        const c = { all: searched.length, running: 0, succeeded: 0, failed: 0 };
        searched.forEach((j) => {
            if (c[j.status] !== undefined) c[j.status] += 1;
        });
        return c;
    }, [searched]);

    const groups = useMemo(() => {
        const shown = statusFilter === 'all'
            ? searched
            : searched.filter((j) => j.status === statusFilter);
        return groupDeploys(shown);
    }, [searched, statusFilter]);

    useTopbarActions(() =>
        <>
            {/* No "New service" button here: unlike the design mock, this tab
                group already carries a New Service tab, and a second entry
                point crowded the strip into overflow. */}
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
            <SearchField
                value={search}
                onSearch={setSearch}
                placeholder="Search deploys…"
            />
        </>,
        [autoRefresh, simInfo?.enabled, search]
    );

    return (
        <div className="sk-tabgroup__inner deployments-page">
            <div className="deployments-page__toolbar">
                <SegControl
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={STATUS_FILTERS.map(([value, label]) => ({
                        value,
                        label,
                        count: counts[value],
                    }))}
                    aria-label="Filter by status"
                />
                <select
                    className="deployments-page__server-select"
                    value={serverFilter}
                    onChange={(e) => setServerFilter(e.target.value)}
                    aria-label="Filter by target server"
                >
                    <option value="all">All servers</option>
                    {servers.map((s) => (
                        <option key={s.id} value={s.id}>
                            {s.name}{s.is_local ? ' (local)' : ''}
                        </option>
                    ))}
                </select>
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
            ) : groups.length === 0 ? (
                <div className="deployments-page__empty">
                    <PlayCircle size={34} />
                    <strong>
                        {jobs.length === 0 ? 'No deployment jobs yet' : 'No deploys match this filter'}
                    </strong>
                    <span>
                        {jobs.length === 0
                            ? 'Create a service from a repository or install a template to see activity here.'
                            : 'Try a different status, server, or search term.'}
                    </span>
                </div>
            ) : (
                <div className="deployments-page__feed">
                    <div className="deployments-page__feed-head" aria-hidden="true">
                        <span />
                        <span>Deploy</span>
                        <span>Pipeline</span>
                        <span>Target</span>
                        <span className="is-right">Took</span>
                        <span className="is-right">Started</span>
                        <span />
                    </div>

                    {groups.map(({ group, items }) => (
                        <div className="deployments-page__group" key={group}>
                            <div className="deployments-page__group-head">
                                {group}
                                <i />
                            </div>
                            {items.map((job) => {
                                const meta = STATE_ICON[job.status] || STATE_ICON.pending;
                                const { Icon } = meta;
                                const ticks = stepTicks(job);
                                return (
                                    <button
                                        type="button"
                                        key={job.id}
                                        className={`deployments-page__row deployments-page__row--${meta.cls}`}
                                        onClick={() => navigate(`/deployments/${job.id}`)}
                                        title="Open the Deploy Console"
                                    >
                                        <span className={`deployments-page__row-ico is-${meta.cls}`}>
                                            <Icon size={15} className={job.status === 'running' ? 'spin' : ''} />
                                        </span>

                                        <span className="deployments-page__row-main">
                                            <span className="deployments-page__row-name">
                                                {job.app_name || 'deployment'}
                                                <span className="deployments-page__row-kind">
                                                    {KIND_CHIP[job.kind] || job.kind}
                                                </span>
                                            </span>
                                            <span className="deployments-page__row-sub">
                                                <span className="deployments-page__row-ref">
                                                    {sourceRef(job) || job.id.slice(0, 8)}
                                                </span>
                                                <span className="deployments-page__row-sep">·</span>
                                                <span>{job.trigger || 'manual'}</span>
                                                {job.status === 'failed' && job.error_message && (
                                                    <>
                                                        <span className="deployments-page__row-sep">·</span>
                                                        <span className="deployments-page__row-error">
                                                            {job.error_message}
                                                        </span>
                                                    </>
                                                )}
                                            </span>
                                        </span>

                                        <span className="deployments-page__pipe">
                                            <span className="deployments-page__ticks">
                                                {ticks.map((state, i) => (
                                                    <i key={i} className={`is-${state}`} />
                                                ))}
                                            </span>
                                            <span className="deployments-page__pipe-count">
                                                {job.current_step || 0}/{job.total_steps || 0}
                                            </span>
                                        </span>

                                        <span className="deployments-page__row-target">
                                            {job.target_server_name || 'Local server'}
                                        </span>
                                        <span className="deployments-page__row-took">
                                            {formatDuration(job.duration)}
                                        </span>
                                        <span className="deployments-page__row-when">
                                            {job.status === 'pending'
                                                ? 'queued'
                                                : relativeTime(job.started_at || job.created_at)}
                                        </span>
                                        <ChevronRight size={15} className="deployments-page__row-chev" />
                                    </button>
                                );
                            })}
                        </div>
                    ))}
                </div>
            )}

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
                                <Loader2 size={15} className="spin" />
                            )}
                        </button>
                    ))}
                </div>
            </Modal>
        </div>
    );
};

export default Deployments;
