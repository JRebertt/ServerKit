import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Pill } from '@/components/ds';
import api from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useDeployments } from '../../hooks/useDeployments';
import { getDeployStatus, formatRelativeTime, formatDuration } from '../../utils/serviceTypes';
import EmptyState from '../EmptyState';

// Deployment status → semantic tone (ds Pill kind / dot modifier)
const DEPLOY_TONE = {
    success: 'green',
    failed: 'red',
    in_progress: 'amber',
    rolled_back: 'gray',
    pending: 'cyan',
};

// Env-var change action → tone (mirrors the history modal's Badge variants).
const ENV_TONE = { created: 'green', updated: 'amber', deleted: 'red' };

// One timeline for everything that happened to this service (the CRM record
// timeline): deployments, environment-variable changes, and — for admins —
// audit-log entries targeting this app. Newest first.
const EventsTab = ({ appId }) => {
    const { deployments, loading, error, reload } = useDeployments(appId);
    const { isAdmin } = useAuth();
    const [envHistory, setEnvHistory] = useState([]);
    const [auditLogs, setAuditLogs] = useState([]);
    const [expandedId, setExpandedId] = useState(null);

    useEffect(() => {
        let cancelled = false;
        api.getEnvVarHistory(appId, 30)
            .then((res) => { if (!cancelled) setEnvHistory(res?.history || []); })
            .catch(() => { /* history is supplemental — the timeline works without it */ });
        if (isAdmin) {
            api.getActivityFeed({ target_type: 'app', target_id: appId, per_page: 50 })
                .then((res) => { if (!cancelled) setAuditLogs(res?.logs || []); })
                .catch(() => { /* non-admin / feed unavailable — deploys still show */ });
        }
        return () => { cancelled = true; };
    }, [appId, isAdmin]);

    // Merge every source into one newest-first stream.
    const events = useMemo(() => {
        const items = [];
        deployments.forEach((deploy, idx) => items.push({
            kind: 'deploy',
            ts: new Date(deploy.timestamp).getTime() || 0,
            deploy,
            deployIndex: idx,
        }));
        envHistory.forEach((entry, idx) => items.push({
            kind: 'env',
            ts: new Date(entry.changed_at).getTime() || 0,
            entry,
            key: `env-${idx}-${entry.changed_at}`,
        }));
        auditLogs.forEach((log) => items.push({
            kind: 'audit',
            ts: new Date(log.created_at).getTime() || 0,
            log,
        }));
        return items.sort((a, b) => b.ts - a.ts);
    }, [deployments, envHistory, auditLogs]);

    if (loading) {
        return <EmptyState loading title="Loading activity..." />;
    }

    if (error) {
        return (
            <div className="events-tab__empty">
                <h3>Failed to load activity</h3>
                <p>{error}</p>
                <Button variant="outline" onClick={reload}>Retry</Button>
            </div>
        );
    }

    if (events.length === 0) {
        return (
            <div className="events-tab__empty">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ opacity: 0.4 }}>
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                </svg>
                <h3>No activity yet</h3>
                <p>Deployments, config changes and edits to this service will show up here.</p>
            </div>
        );
    }

    const latestSuccessIdx = deployments.findIndex((d) => d.status === 'success');

    return (
        <div className="events-tab">
            <div className="events-tab__header">
                <h3 className="svc-eyebrow">
                    Activity <span className="svc-eyebrow__count">&middot; {events.length}</span>
                </h3>
                <Button variant="outline" size="sm" onClick={reload}>Refresh</Button>
            </div>

            <div className="events-tab__timeline">
                {events.map((event) => {
                    if (event.kind !== 'deploy') {
                        const isEnv = event.kind === 'env';
                        const tone = isEnv ? (ENV_TONE[event.entry.action] || 'cyan') : 'violet';
                        const text = isEnv
                            ? <><b>{event.entry.key}</b> {event.entry.action}</>
                            : <>{(event.log.action || '').replace(/[._]/g, ' ')}</>;
                        const detail = !isEnv && event.log.details?.name
                            ? <span>{event.log.details.name}</span>
                            : null;
                        return (
                            <div
                                key={isEnv ? event.key : `audit-${event.log.id}`}
                                className="events-tab__event events-tab__event--compact"
                            >
                                <div className={`events-tab__event-status events-tab__event-status--${tone}`} />
                                <div className="events-tab__event-body">
                                    <div className="events-tab__event-header">
                                        <span className="events-tab__event-message">{text}</span>
                                        <Pill kind={tone}>{isEnv ? 'config' : 'audit'}</Pill>
                                    </div>
                                    <div className="events-tab__event-meta">
                                        {detail}
                                        <span>{formatRelativeTime(isEnv ? event.entry.changed_at : event.log.created_at)}</span>
                                    </div>
                                </div>
                            </div>
                        );
                    }

                    const deploy = event.deploy;
                    const statusInfo = getDeployStatus(deploy.status);
                    const tone = DEPLOY_TONE[deploy.status] || 'cyan';
                    const isExpanded = expandedId === deploy.id;
                    const isLatest = event.deployIndex === latestSuccessIdx;

                    return (
                        <div
                            key={`deploy-${deploy.id}`}
                            className={`events-tab__event ${isExpanded ? 'events-tab__event--expanded' : ''}`}
                            onClick={() => setExpandedId(isExpanded ? null : deploy.id)}
                        >
                            <div className={`events-tab__event-status events-tab__event-status--${tone}`} />
                            <div className="events-tab__event-body">
                                <div className="events-tab__event-header">
                                    <div className="events-tab__event-commit">
                                        {deploy.commitSha && (
                                            <span className="events-tab__event-sha">
                                                {deploy.commitSha.substring(0, 7)}
                                            </span>
                                        )}
                                        <span className="events-tab__event-message">
                                            {deploy.commitMessage || deploy.version || `Deployment #${deployments.length - event.deployIndex}`}
                                        </span>
                                    </div>
                                    <Pill kind={isLatest ? 'green' : tone}>
                                        {isLatest ? 'Live' : statusInfo.label}
                                    </Pill>
                                </div>
                                <div className="events-tab__event-meta">
                                    {deploy.duration && <span>{formatDuration(deploy.duration)}</span>}
                                    {deploy.trigger && <span>{deploy.trigger}</span>}
                                    {deploy.branch && <span>{deploy.branch}</span>}
                                    <span>{formatRelativeTime(deploy.timestamp)}</span>
                                </div>
                                {isExpanded && deploy.logs && (
                                    <div className="events-tab__event-logs">
                                        <pre>{deploy.logs}</pre>
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default EventsTab;
