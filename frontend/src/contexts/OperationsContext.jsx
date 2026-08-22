import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react';

import { usePolling } from '../hooks/usePolling';
import useRunStream from '../hooks/useRunStream';
import useServiceLogStream from '../hooks/useServiceLogStream';
import { SOCKET_EVENTS } from '../constants/events';
import api from '../services/api';
import {
    boundOperationHistory,
    isActiveOperation,
    normalizeOperations,
    operationKey,
    operationNeedsAttention,
    reconcileOperationStatus,
} from '../services/operations';
import socketService from '../services/socket';
import { useAuth } from './AuthContext';

const OperationsContext = createContext(null);
const REFRESH_MS = 6000;
const HISTORY_LIMIT = 25;

export function OperationsProvider({ children }) {
    const { user } = useAuth();
    const canReadJobs = user?.role === 'admin';
    const [operations, setOperations] = useState([]);
    const [selectedKey, setSelectedKey] = useState(null);
    const [collapsed, setCollapsed] = useState(true);
    const [unreadKeys, setUnreadKeys] = useState(() => new Set());
    const [loading, setLoading] = useState(true);
    const [logSession, setLogSession] = useState(null);
    const selectedKeyRef = useRef(selectedKey);
    const operationsRef = useRef(operations);
    selectedKeyRef.current = selectedKey;
    operationsRef.current = operations;

    const refresh = useCallback(async () => {
        const [deploymentsResult, jobsResult] = await Promise.allSettled([
            api.getDeploymentJobs({ limit: 30 }),
            canReadJobs ? api.getJobs({ limit: 50 }) : Promise.resolve({ jobs: [] }),
        ]);
        if (deploymentsResult.status === 'rejected' && jobsResult.status === 'rejected') {
            setLoading(false);
            return;
        }
        const deployments = deploymentsResult.status === 'fulfilled'
            ? deploymentsResult.value?.jobs || []
            : [];
        const jobs = jobsResult.status === 'fulfilled' ? jobsResult.value?.jobs || [] : [];
        const normalized = normalizeOperations({ deployments, jobs });
        const bounded = boundOperationHistory(normalized, HISTORY_LIMIT, selectedKeyRef.current);
        operationsRef.current = bounded;
        setOperations(bounded);
        setLoading(false);
    }, [canReadJobs]);

    usePolling(refresh, REFRESH_MS);

    useEffect(() => {
        socketService.connect();
        const offStatus = socketService.on(SOCKET_EVENTS.RUN_STATUS, (payload) => {
            const reconciled = reconcileOperationStatus(operationsRef.current, payload);
            if (!reconciled.matched) {
                refresh();
                return;
            }
            operationsRef.current = reconciled.operations;
            setOperations(reconciled.operations);
            if (reconciled.attentionKey) {
                setUnreadKeys((keys) => new Set(keys).add(reconciled.attentionKey));
            }
        });
        const offConnect = socketService.on(SOCKET_EVENTS.CONNECTED, refresh);
        return () => {
            offStatus();
            offConnect();
        };
    }, [refresh]);

    useEffect(() => {
        operationsRef.current = [];
        setOperations([]);
        setUnreadKeys(new Set());
        setSelectedKey(null);
        setCollapsed(true);
        setLoading(true);
        setLogSession(null);
    }, [user?.id]);

    const activeOperations = useMemo(
        () => operations.filter(isActiveOperation),
        [operations],
    );
    const history = useMemo(
        () => operations.filter((operation) => !isActiveOperation(operation)),
        [operations],
    );
    const attentionOperations = useMemo(
        () => operations.filter(operationNeedsAttention),
        [operations],
    );
    const selectedOperation = useMemo(
        () => operations.find((operation) => operationKey(operation) === selectedKey) || null,
        [operations, selectedKey],
    );
    const selectedRunKind = selectedOperation?.runKind;
    const selectedRunId = selectedOperation?.id;
    const selectedRunStatus = selectedOperation?.status;
    const initialSelectedRun = useMemo(() => (
        selectedRunId == null ? null : { id: selectedRunId, status: selectedRunStatus }
    ), [selectedRunId, selectedRunStatus]);
    const selectedStream = useRunStream(selectedRunKind, selectedRunId, {
        enabled: !collapsed && !!selectedRunKind && selectedRunId != null,
        initialRun: initialSelectedRun,
    });
    const serviceStream = useServiceLogStream(logSession, {
        enabled: !collapsed && !!logSession,
    });

    const markRead = useCallback((key) => {
        setUnreadKeys((current) => {
            if (!current.has(key)) return current;
            const next = new Set(current);
            next.delete(key);
            return next;
        });
    }, []);

    const openOperation = useCallback((operation) => {
        const key = typeof operation === 'string' ? operation : operationKey(operation);
        setLogSession(null);
        setSelectedKey(key);
        setCollapsed(false);
        markRead(key);
    }, [markRead]);

    const openRun = useCallback((runKind, runId) => {
        if (!runKind || runId == null) return;
        if (runKind === 'job' && !canReadJobs) return;
        const key = `${runKind}:${runId}`;
        setLogSession(null);
        setSelectedKey(key);
        setCollapsed(false);
        markRead(key);
        // Creation responses carry only an id. Refresh immediately so the
        // selected detail replaces its short loading state before the poll.
        refresh();
    }, [canReadJobs, markRead, refresh]);

    const openLogSession = useCallback((session) => {
        setSelectedKey(null);
        setLogSession(session);
        setCollapsed(false);
    }, []);

    const closeLogSession = useCallback(() => {
        setLogSession(null);
        setCollapsed(true);
    }, []);

    const value = useMemo(() => ({
        operations,
        activeOperations,
        history,
        attentionOperations,
        selectedOperation,
        selectedLines: selectedStream.lines,
        selectedTransport: selectedStream.transport,
        selectedStreamError: selectedStream.error,
        refreshSelected: selectedStream.refetch,
        logSession,
        serviceLines: serviceStream.lines,
        serviceStreamError: serviceStream.error,
        clearServiceLines: serviceStream.clear,
        selectedKey,
        collapsed,
        unreadKeys,
        unreadCount: unreadKeys.size,
        loading,
        refresh,
        openOperation,
        openRun,
        openLogSession,
        closeLogSession,
        selectOperation: setSelectedKey,
        setCollapsed,
        markRead,
    }), [
        operations,
        activeOperations,
        history,
        attentionOperations,
        selectedOperation,
        selectedStream.lines,
        selectedStream.transport,
        selectedStream.error,
        selectedStream.refetch,
        logSession,
        serviceStream.lines,
        serviceStream.error,
        serviceStream.clear,
        selectedKey,
        collapsed,
        unreadKeys,
        loading,
        refresh,
        openOperation,
        openRun,
        openLogSession,
        closeLogSession,
        markRead,
    ]);

    return <OperationsContext.Provider value={value}>{children}</OperationsContext.Provider>;
}

// Context modules intentionally export their hook beside the provider.
// eslint-disable-next-line react-refresh/only-export-components
export function useOperations() {
    const context = useContext(OperationsContext);
    if (!context) throw new Error('useOperations must be used within OperationsProvider');
    return context;
}
