import { useCallback, useEffect, useRef, useState } from 'react';

import { SOCKET_EVENTS } from '../constants/events';
import api from '../services/api';
import socketService from '../services/socket';
import { isTerminalRunStatus, mergeRunLogLines } from './runStream';
import usePolling from './usePolling';

const SOCKET_GRACE_MS = 2500;

function runFromResponse(response) {
    return response?.run || response?.job || response || null;
}

/**
 * Generalized browser transport for the backend run envelope.
 *
 * Every run kind shares persisted after_id log catch-up and run_log/run_status
 * socket events. Callers may supply loadRun when their domain has a richer
 * status/snapshot endpoint; logs always fall back to the common /runs twin.
 */
export default function useRunStream(runKind, runId, options = {}) {
    const {
        enabled = true,
        pollInterval = 2000,
        loadRun,
        initialRun = null,
    } = options;

    const [run, setRun] = useState(initialRun);
    const [lines, setLines] = useState([]);
    const [transport, setTransport] = useState('poll');
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(true);
    const [pollingEnabled, setPollingEnabled] = useState(false);

    const maxIdRef = useRef(0);
    const seenRef = useRef(new Set());
    const stoppedRef = useRef(false);

    const mergeLines = useCallback((incoming) => {
        setLines((previous) => {
            const merged = mergeRunLogLines(previous, incoming, seenRef.current);
            maxIdRef.current = Math.max(maxIdRef.current, merged.maxId);
            return merged.lines;
        });
    }, []);

    const applyRun = useCallback((next) => {
        if (!next) return;
        setRun((previous) => ({ ...(previous || {}), ...next }));
        if (isTerminalRunStatus(next.status)) stoppedRef.current = true;
    }, []);

    const stopPolling = useCallback(() => {
        setPollingEnabled(false);
    }, []);

    const pollOnce = useCallback(async ({ force = false } = {}) => {
        if ((!force && stoppedRef.current) || !runKind || runId == null) return;
        try {
            const requests = [api.getRunLogs(runKind, runId, maxIdRef.current || null)];
            if (loadRun) requests.push(loadRun({ includeLogs: false }));
            const [logsResponse, runResponse] = await Promise.all(requests);
            mergeLines(logsResponse?.logs || []);
            applyRun(runFromResponse(runResponse));
            setError(null);
            if (isTerminalRunStatus(runFromResponse(runResponse)?.status)) stopPolling();
        } catch (nextError) {
            setError(nextError?.data?.error || nextError?.message || null);
        }
    }, [runKind, runId, loadRun, mergeLines, applyRun, stopPolling]);

    const startPolling = useCallback(() => {
        if (stoppedRef.current || pollInterval <= 0) return;
        setTransport('poll');
        setPollingEnabled(true);
    }, [pollInterval]);

    usePolling(pollOnce, pollInterval, {
        enabled: enabled && pollingEnabled && !isTerminalRunStatus(run?.status),
        immediate: false,
    });

    const refetch = useCallback(() => pollOnce({ force: true }), [pollOnce]);

    useEffect(() => {
        if (!runKind || runId == null || !enabled) {
            setLoading(false);
            return undefined;
        }

        stoppedRef.current = isTerminalRunStatus(initialRun?.status);
        maxIdRef.current = 0;
        seenRef.current = new Set();
        setRun(initialRun);
        setLines([]);
        setError(null);
        setLoading(true);
        setPollingEnabled(false);

        let cancelled = false;

        const boot = async () => {
            try {
                if (loadRun) {
                    const response = await loadRun({ includeLogs: true });
                    if (cancelled) return;
                    const snapshot = runFromResponse(response);
                    mergeLines(snapshot?.logs || response?.logs || []);
                    applyRun(snapshot);
                    if (isTerminalRunStatus(snapshot?.status)) {
                        socketService.unsubscribeRun(runKind, runId);
                        stopPolling();
                    }
                } else {
                    await pollOnce({ force: true });
                }
            } catch (nextError) {
                if (!cancelled) {
                    setError(nextError?.data?.error || nextError?.message || null);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        boot();

        socketService.connect();

        const resyncAndSubscribe = () => {
            if (stoppedRef.current) return;
            setTransport('socket');
            stopPolling();
            api.getRunLogs(runKind, runId, maxIdRef.current || null)
                .then((response) => mergeLines(response?.logs || []))
                .catch(() => {});
            socketService.subscribeRun(runKind, runId);
        };

        const matchesRun = (payload) => (
            payload?.run_kind === runKind && String(payload?.run_id) === String(runId)
        );
        const onRunLog = (payload) => {
            if (matchesRun(payload)) mergeLines(payload?.lines || []);
        };
        const onRunStatus = (payload) => {
            if (!matchesRun(payload) || !payload?.status) return;
            applyRun(payload.status);
            if (isTerminalRunStatus(payload.status.status)) {
                socketService.unsubscribeRun(runKind, runId);
                stopPolling();
            }
        };

        if (socketService.socket?.connected) resyncAndSubscribe();
        const offConnect = socketService.on(SOCKET_EVENTS.CONNECTED, resyncAndSubscribe);
        const offDisconnect = socketService.on('disconnected', startPolling);
        const offLog = socketService.on(SOCKET_EVENTS.RUN_LOG, onRunLog);
        const offStatus = socketService.on(SOCKET_EVENTS.RUN_STATUS, onRunStatus);
        const grace = setTimeout(() => {
            if (!socketService.socket?.connected && !stoppedRef.current) startPolling();
        }, SOCKET_GRACE_MS);

        return () => {
            cancelled = true;
            clearTimeout(grace);
            offConnect();
            offDisconnect();
            offLog();
            offStatus();
            socketService.unsubscribeRun(runKind, runId);
        };
    }, [runKind, runId, enabled, initialRun, loadRun, mergeLines, applyRun, pollOnce, startPolling, stopPolling]);

    return {
        run,
        lines,
        isLive: !!run && !isTerminalRunStatus(run.status),
        transport,
        error,
        loading,
        refetch,
    };
}
