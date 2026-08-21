import { useCallback, useEffect, useState } from 'react';

import { SOCKET_EVENTS } from '../constants/events';
import api from '../services/api';
import socketService from '../services/socket';
import {
    appendServiceLogLines,
    MAX_SERVICE_LOG_LINES,
    normalizeServiceLogSnapshot,
} from './serviceLogStream';

export default function useServiceLogStream(session, { enabled = true } = {}) {
    const [lines, setLines] = useState([]);
    const [error, setError] = useState(null);

    const clear = useCallback(() => setLines([]), []);

    useEffect(() => {
        if (!session || !enabled) return undefined;
        let cancelled = false;
        setLines([]);
        setError(null);

        const isContainer = session.appType === 'docker' && session.containerId != null;
        const loadSnapshot = async () => {
            try {
                let response;
                if (isContainer) response = await api.getDockerAppLogs(session.containerId, 200);
                else if (session.logPath) response = await api.getLogs(session.logPath, 200);
                if (!cancelled) {
                    setLines(normalizeServiceLogSnapshot(response?.logs).slice(-MAX_SERVICE_LOG_LINES));
                    setError(null);
                }
            } catch (nextError) {
                if (!cancelled) setError(nextError?.data?.error || nextError?.message || null);
            }
        };

        const subscribe = () => {
            loadSnapshot();
            if (isContainer) {
                socketService.subscribeContainerLogs(session.containerId, {
                    service: session.service,
                    tail: 200,
                });
            } else if (session.logPath) {
                socketService.subscribeLogs(session.logPath);
            }
        };

        socketService.connect();
        if (socketService.socket?.connected) subscribe();
        const offConnect = socketService.on(SOCKET_EVENTS.CONNECTED, subscribe);
        const offFileLine = socketService.on(SOCKET_EVENTS.LOG_LINE, (payload) => {
            if (isContainer || cancelled) return;
            const line = typeof payload === 'string'
                ? payload
                : payload?.line || payload?.message || JSON.stringify(payload);
            setLines((previous) => appendServiceLogLines(previous, line));
        });
        const offContainerLine = socketService.on(SOCKET_EVENTS.CONTAINER_LOG, (payload) => {
            if (!isContainer || cancelled || String(payload?.app_id) !== String(session.containerId)) return;
            setLines((previous) => appendServiceLogLines(previous, payload?.line));
        });
        const offContainerError = socketService.on(SOCKET_EVENTS.CONTAINER_LOG_ERROR, (payload) => {
            if (isContainer && String(payload?.app_id) === String(session.containerId)) {
                setError(payload?.message || null);
            }
        });
        const offContainerEnded = socketService.on(SOCKET_EVENTS.CONTAINER_LOG_ENDED, (payload) => {
            if (isContainer && String(payload?.app_id) === String(session.containerId) && payload?.message) {
                setLines((previous) => appendServiceLogLines(previous, payload.message));
            }
        });

        return () => {
            cancelled = true;
            offConnect();
            offFileLine();
            offContainerLine();
            offContainerError();
            offContainerEnded();
            if (isContainer) socketService.unsubscribeContainerLogs();
            else if (session.logPath) socketService.unsubscribeLogs();
        };
    }, [session, enabled]);

    return { lines, error, clear };
}
