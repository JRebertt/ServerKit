import { useState, useEffect, useRef, useCallback } from 'react';
import { useLogsDrawer } from '../contexts/LogsDrawerContext';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import socketService from '../services/socket';
import api from '../services/api';
import { useTranslation } from 'react-i18next';

const MAX_LINES = 1000;
const MIN_HEIGHT = 120;
const DEFAULT_HEIGHT = 300;

const LogsDrawer = () => {
    const { t } = useTranslation();
    const { drawerState, service, closeDrawer, collapseDrawer, expandDrawer } = useLogsDrawer();
    const [lines, setLines] = useState([]);
    const [autoScroll, setAutoScroll] = useState(true);
    const [height, setHeight] = useState(DEFAULT_HEIGHT);
    const logRef = useRef(null);
    const dragging = useRef(false);
    const startY = useRef(0);
    const startHeight = useRef(0);

    // Load initial logs and subscribe to real-time updates
    useEffect(() => {
        if (!service || drawerState === 'closed') return;

        setLines([]);
        let cancelled = false;

        async function loadInitial() {
            try {
                let data;
                if (service.appType === 'docker' && service.containerId) {
                    data = await api.getDockerAppLogs(service.containerId, 200);
                } else if (service.logPath) {
                    data = await api.getLogs(service.logPath, 200);
                }
                if (!cancelled && data?.logs) {
                    const initial = data.logs.split('\n').filter(Boolean);
                    setLines(initial.slice(-MAX_LINES));
                }
            } catch { /* initial snapshot is best-effort; live stream still attaches */ }
        }
        loadInitial();

        socketService.connect();
        if (service.logPath) {
            socketService.subscribeLogs(service.logPath);
        }

        const unsubscribe = socketService.on('log_line', (data) => {
            if (cancelled) return;
            const line = typeof data === 'string' ? data : data?.line || data?.message || JSON.stringify(data);
            setLines(prev => {
                const next = [...prev, line];
                return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
            });
        });

        return () => {
            cancelled = true;
            socketService.unsubscribeLogs();
            unsubscribe();
        };
    }, [service, drawerState]);

    // Auto-scroll
    useEffect(() => {
        if (autoScroll && logRef.current && drawerState === 'expanded') {
            logRef.current.scrollTop = logRef.current.scrollHeight;
        }
    }, [lines, autoScroll, drawerState]);

    // Resize drag handlers
    const handleDragStart = useCallback((e) => {
        e.preventDefault();
        dragging.current = true;
        startY.current = e.clientY;
        startHeight.current = height;
        document.addEventListener('mousemove', handleDragMove);
        document.addEventListener('mouseup', handleDragEnd);
    }, [height]);

    const handleDragMove = useCallback((e) => {
        if (!dragging.current) return;
        const diff = startY.current - e.clientY;
        const newHeight = Math.max(MIN_HEIGHT, Math.min(window.innerHeight * 0.7, startHeight.current + diff));
        setHeight(newHeight);
    }, []);

    const handleDragEnd = useCallback(() => {
        dragging.current = false;
        document.removeEventListener('mousemove', handleDragMove);
        document.removeEventListener('mouseup', handleDragEnd);
    }, [handleDragMove]);

    function getLineClass(line) {
        const lower = line.toLowerCase();
        if (lower.includes('error') || lower.includes('critical') || lower.includes('fatal')) return 'logs-drawer__line--error';
        if (lower.includes('warn')) return 'logs-drawer__line--warn';
        return '';
    }

    if (drawerState === 'closed' || !service) return null;

    const lastLine = lines.length > 0 ? lines[lines.length - 1] : 'Waiting for logs...';
    const sourceLabel = service.logPath
        || (service.containerId ? `docker · ${String(service.containerId).slice(0, 12)}` : null)
        || service.appType
        || 'live stream';

    if (drawerState === 'collapsed') {
        return (
            <div className="logs-drawer logs-drawer--collapsed" onClick={expandDrawer}>
                <div className="logs-drawer__collapsed-bar">
                    <span className="logs-drawer__live-dot" />
                    <span className="logs-drawer__service-name">{service.name}</span>
                    <span className="logs-drawer__last-line">{lastLine}</span>
                    <div className="logs-drawer__collapsed-actions">
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={(e) => { e.stopPropagation(); closeDrawer(); }}
                            title={t('app.logsDrawer.close', 'Close')}
                        >
                            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                        </Button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="logs-drawer logs-drawer--expanded" style={{ height }}>
            {/* Resize handle */}
            <div className="logs-drawer__resize-handle" onMouseDown={handleDragStart} />

            {/* Header */}
            <div className="logs-drawer__header">
                <div className="logs-drawer__header-left">
                    <span className="logs-drawer__ico">
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                            <polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>
                        </svg>
                    </span>
                    <div className="logs-drawer__titles">
                        <span className="logs-drawer__service-name">{service.name}</span>
                        <span className="logs-drawer__source">{sourceLabel}</span>
                    </div>
                </div>
                <div className="logs-drawer__header-right">
                    <span className="logs-drawer__live">
                        <span className="logs-drawer__live-dot" />
                        {lines.length} lines
                    </span>
                    <label className="logs-drawer__toggle">
                        <Switch checked={autoScroll} onCheckedChange={setAutoScroll} />
                        <span>{t('app.logsDrawer.autoScroll', 'Auto-scroll')}</span>
                    </label>
                    <Button variant="ghost" size="icon" onClick={() => setLines([])} title={t('app.logsDrawer.clear', 'Clear')}>
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                    </Button>
                    <Button variant="ghost" size="icon" onClick={collapseDrawer} title={t('app.logsDrawer.collapse', 'Collapse')}>
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                            <polyline points="6 9 12 15 18 9"/>
                        </svg>
                    </Button>
                    <Button variant="ghost" size="icon" onClick={closeDrawer} title={t('app.logsDrawer.close2', 'Close')}>
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </Button>
                </div>
            </div>

            {/* Log content */}
            <div className="logs-drawer__content" ref={logRef}>
                {lines.length === 0 ? (
                    <div className="logs-drawer__empty">{t('app.logsDrawer.waitingForLogs', 'Waiting for logs...')}</div>
                ) : (
                    lines.map((line, i) => (
                        <div key={i} className={`logs-drawer__line ${getLineClass(line)}`}>{line}</div>
                    ))
                )}
            </div>
        </div>
    );
};

export default LogsDrawer;
