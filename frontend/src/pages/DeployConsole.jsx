import { useEffect, useMemo, useState, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, Loader2, CheckCircle2, XCircle, Clock, WifiOff } from 'lucide-react';
import useDeployJobStream from '../hooks/useDeployJobStream';
import api from '../services/api';
import PipelineStrip from '../components/deploy-console/PipelineStrip';
import ConsoleToolbar from '../components/deploy-console/ConsoleToolbar';
import LogPane from '../components/deploy-console/LogPane';
import ErrorCard from '../components/deploy-console/ErrorCard';
import SuccessBanner from '../components/deploy-console/SuccessBanner';
import { sourceRef } from '../utils/deployActivity';

const STATUS_META = {
    pending: { label: 'Queued', icon: Clock, cls: 'pending' },
    running: { label: 'Running', icon: Loader2, cls: 'running' },
    succeeded: { label: 'Succeeded', icon: CheckCircle2, cls: 'succeeded' },
    failed: { label: 'Failed', icon: XCircle, cls: 'failed' },
    cancelled: { label: 'Cancelled', icon: XCircle, cls: 'failed' },
};

const fmtStarted = (iso) => {
    if (!iso) return 'not started';
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
};

const fmtElapsed = (ms) => {
    if (ms == null || ms < 0) return '0:00';
    const total = Math.floor(ms / 1000);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
};

function humanizeTitle(job) {
    if (!job) return 'Deployment';
    // Kinds contributed by plugins name their own run in the plan, so the
    // console reads properly without a branch per kind here.
    if (job.plan?.title) return job.plan.title;
    if (job.kind === 'demo_deploy') {
        const scenario = job.plan?.scenario || job.result?.scenario;
        return `Test deployment${scenario ? ` — ${scenario}` : ''}`;
    }
    if (job.kind === 'template_install') {
        const name = job.plan?.template_name || job.plan?.app_name || job.app_name || 'app';
        return `Installing ${name}`;
    }
    if (job.kind === 'app_deploy') {
        const target = job.target_server_name && job.target_server_name !== 'Local server'
            ? ` on ${job.target_server_name}` : '';
        return `Deploying ${job.app_name || 'service'}${target}`;
    }
    return `Deployment · ${job.kind}`;
}

export default function DeployConsole() {
    const { jobId } = useParams();
    const navigate = useNavigate();
    const { job, lines, isLive, transport, error, loading } = useDeployJobStream(jobId, { includePlan: true });

    const [follow, setFollow] = useState(true);
    const [wrap, setWrap] = useState(true);
    const [timestamps, setTimestamps] = useState(false);
    const [level, setLevel] = useState('all');
    const [search, setSearch] = useState('');
    const [scrollToStep, setScrollToStep] = useState(null);
    const [selectedStep, setSelectedStep] = useState(null);
    const [retrying, setRetrying] = useState(false);
    const [now, setNow] = useState(Date.now());

    const status = job?.status || 'pending';

    // Live elapsed timer while running.
    useEffect(() => {
        if (status !== 'running' && status !== 'pending') return undefined;
        const t = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(t);
    }, [status]);

    const steps = useMemo(() => {
        const planSteps = job?.plan?.steps || [];
        const timingByIndex = {};
        (job?.result?.step_timings || []).forEach((t) => { timingByIndex[t.index] = t; });
        const current = job?.current_step || 0;
        return planSteps.map((s, i) => {
            const index = i + 1;
            const name = s.name || s.type || `Step ${index}`;
            let state;
            if (status === 'failed' && index === current) state = 'failed';
            else if (status === 'succeeded' || timingByIndex[index] || index < current) state = 'done';
            else if (index === current && status === 'running') state = 'running';
            else state = 'pending';
            return { index, name, state, seconds: timingByIndex[index]?.seconds };
        });
    }, [job, status]);

    const visibleLines = useMemo(() => {
        const q = search.trim().toLowerCase();
        return lines.filter((l) =>
            (level === 'all' || (l.level || 'info') === level)
            && (!q || (l.message || '').toLowerCase().includes(q))
        );
    }, [lines, level, search]);

    const elapsedMs = useMemo(() => {
        if (!job?.started_at) return job?.created_at ? now - new Date(job.created_at).getTime() : 0;
        const end = job.completed_at ? new Date(job.completed_at).getTime() : now;
        return end - new Date(job.started_at).getTime();
    }, [job, now]);

    const copyLogs = useCallback(() => {
        const text = lines.map((l) => l.message).join('\n');
        navigator.clipboard?.writeText(text);
    }, [lines]);

    const downloadLogs = useCallback(() => {
        const text = lines.map((l) => {
            const ts = l.ts || l.created_at || '';
            return `${ts ? `[${ts}] ` : ''}${(l.level || 'info').toUpperCase()} ${l.message}`;
        }).join('\n');
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `deploy-${jobId}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }, [lines, jobId]);

    const onStepClick = useCallback((index) => {
        setFollow(false);
        setSelectedStep(index);
        setScrollToStep(index);
        // reset so a repeat click on the same step re-triggers the effect
        setTimeout(() => setScrollToStep(null), 100);
    }, []);

    const onRetry = useCallback(async () => {
        setRetrying(true);
        try {
            const res = await api.retryDeploymentJob(jobId);
            if (res?.job_id) navigate(`/deployments/${res.job_id}`);
        } catch {
            setRetrying(false);
        }
    }, [jobId, navigate]);

    const meta = STATUS_META[status] || STATUS_META.pending;
    const StatusIcon = meta.icon;
    const failedStepName = status === 'failed'
        ? (job?.current_step_name || steps.find((s) => s.state === 'failed')?.name)
        : null;
    const appUrl = job?.result?.auto_domain?.url || null;
    const degraded = (status === 'running' || status === 'pending') && transport === 'poll';
    const sourceLabel = job ? sourceRef(job) : null;

    if (loading && !job) {
        return (
            <div className="deploy-console deploy-console--loading">
                <Loader2 size={22} className="deploy-console__spin" />
                <span>Loading deployment…</span>
            </div>
        );
    }

    if (error && !job) {
        return (
            <div className="deploy-console deploy-console--error-page">
                <XCircle size={22} />
                <strong>Deployment not found</strong>
                <p>{error}</p>
                <Link to="/deployments" className="deploy-console__btn">
                    <ArrowLeft size={14} /> Back to deployments
                </Link>
            </div>
        );
    }

    return (
        <div className="deploy-console">
            <header className="deploy-console__header">
                <Link to="/deployments" className="deploy-console__back" title="Back to deployments">
                    <ArrowLeft size={18} />
                </Link>
                <h1 className="deploy-console__title">{humanizeTitle(job)}</h1>
                <div className="deploy-console__meta">
                    {job?.kind === 'demo_deploy' && (
                        <span className="deploy-console__pill deploy-console__pill--demo" title="Scripted test deployment — no real resources were touched">
                            Simulated
                        </span>
                    )}
                    <span className={`deploy-console__pill deploy-console__pill--${meta.cls}`}>
                        <StatusIcon size={14} className={status === 'running' ? 'deploy-console__spin' : ''} />
                        {meta.label}
                    </span>
                    {job?.total_steps > 0 && (
                        <span className="deploy-console__step-count">
                            step {Math.min(job.current_step || 0, job.total_steps)}/{job.total_steps}
                        </span>
                    )}
                    <span className="deploy-console__elapsed">{fmtElapsed(elapsedMs)}</span>
                </div>
            </header>

            {degraded && (
                <div className="deploy-console__degraded">
                    <WifiOff size={14} /> Live updates unavailable — refreshing every 2s.
                </div>
            )}

            {status === 'pending' && (
                <div className="deploy-console__queued">
                    <Loader2 size={16} className="deploy-console__spin" /> Waiting for a worker to pick up this deployment…
                </div>
            )}

            {status === 'failed' && (
                <ErrorCard
                    failedStepName={failedStepName}
                    failureTail={job?.result?.failure_tail}
                    hint={job?.result?.hint}
                    errorMessage={job?.error_message}
                    onRetry={onRetry}
                    retrying={retrying}
                />
            )}

            {status === 'succeeded' && (
                <SuccessBanner job={job} appUrl={appUrl} />
            )}

            <PipelineStrip steps={steps} selected={selectedStep} onStepClick={onStepClick} />

            <div className="deploy-console__runmeta">
                <span><b>{jobId}</b></span>
                <span>trigger <b>{job?.trigger || 'manual'}</b></span>
                {sourceLabel && <span>source <b>{sourceLabel}</b></span>}
                <span>target <b>{job?.target_server_name || 'Local server'}</b></span>
                <span>started <b>{fmtStarted(job?.started_at || job?.created_at)}</b></span>
            </div>

            <div className="deploy-console__body">
                <div className="deploy-console__main">
                    <ConsoleToolbar
                        follow={follow} onToggleFollow={() => setFollow((v) => !v)}
                        wrap={wrap} onToggleWrap={() => setWrap((v) => !v)}
                        timestamps={timestamps} onToggleTimestamps={() => setTimestamps((v) => !v)}
                        level={level} onLevelChange={setLevel}
                        search={search} onSearchChange={setSearch}
                        onCopy={copyLogs} onDownload={downloadLogs}
                    />
                    <LogPane
                        lines={visibleLines}
                        wrap={wrap}
                        timestamps={timestamps}
                        follow={follow && isLive}
                        onFollowChange={setFollow}
                        scrollToStep={scrollToStep}
                    />
                </div>
            </div>
        </div>
    );
}
