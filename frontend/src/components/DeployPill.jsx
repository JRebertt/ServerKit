import { useEffect, useState, useCallback, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import api from '../services/api';
import socketService from '../services/socket';
import { usePolling } from '../hooks/usePolling';
import { useTranslation } from 'react-i18next';

// A small global "deploy in progress" pill: while any deployment job is
// pending/running it appears (bottom-left) so you can navigate away mid-deploy
// and always find your way back to the live Deploy Console (plan 51 §1.3).
// Driven by a lightweight poll of GET /deployment-jobs?status=running, refreshed
// on socket reconnect and on any deploy_status event that flows through.
//
// It is a shortcut *back* to Deploy Activity, so it has nothing to offer while
// you are already there: on /deployments and /deployments/:jobId it stays out
// of the way entirely (and stops polling). Installing a database engine sends
// you straight to that console, which is how a floating "1 deploy running" tag
// ended up shouting at the page it links to.
const POLL_MS = 6000;

export default function DeployPill() {
    const { t } = useTranslation();
    const { pathname } = useLocation();
    const [active, setActive] = useState([]);
    // Deploy Activity and the console are the surface this pill points at.
    const onDeploySurface = pathname === '/deployments' || pathname.startsWith('/deployments/');

    // A tick must never start while the previous one is outstanding. This pill
    // lives in the global shell, so it polls on EVERY authenticated route; when
    // the backend is slow a 6s interval with no guard stacks a new pair of
    // requests every 6s on top of the ones already waiting. A 30s response time
    // means five concurrent `status=running` calls — which is exactly what a
    // DevTools capture of /domains showed, alongside a wall of pending rows.
    const inFlight = useRef(false);

    const refresh = useCallback(async () => {
        if (inFlight.current) return;
        inFlight.current = true;
        try {
            // One request, not two. The endpoint returns the job's status, so
            // asking for each status separately doubled the request count to
            // learn the same thing.
            const res = await api.getDeploymentJobs({ limit: 20 });
            setActive((res?.jobs || []).filter(
                (job) => job.status === 'running' || job.status === 'pending',
            ));
        } catch {
            // Silent — the pill is a convenience, not critical chrome.
        } finally {
            inFlight.current = false;
        }
    }, []);

    // The interval, the hidden-tab pause, and the catch-up on return are the
    // shared convention now; this component was where they were first worked
    // out by hand.
    usePolling(refresh, POLL_MS, { enabled: !onDeploySurface });

    useEffect(() => {
        if (onDeploySurface) return undefined;
        // React quickly to live status changes when a console elsewhere is
        // streaming — but a burst of deploy_status events must not become a
        // burst of requests, so the in-flight guard covers these too.
        const unsubStatus = socketService.on('deploy_status', refresh);
        const unsubConnect = socketService.on('connected', refresh);
        return () => {
            unsubStatus();
            unsubConnect();
        };
    }, [refresh, onDeploySurface]);

    if (onDeploySurface || active.length === 0) return null;

    const count = active.length;
    const to = count === 1 ? `/deployments/${active[0].id}` : '/deployments';
    const label = count === 1 ? '1 deploy running' : `${count} deploys running`;

    return (
        <Link to={to} className="deploy-pill" title={t('app.deployPill.openTheDeployConsole', 'Open the Deploy Console')}>
            <Loader2 size={14} className="deploy-pill__spin" />
            <span>{label}</span>
        </Link>
    );
}
