import { useState, useEffect } from 'react';
import { logsToText } from '@/utils/logText';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { usePolling } from '../../hooks/usePolling';

const LOG_REFRESH_MS = 5000;

const LogsTab = ({ app }) => {
    const [logs, setLogs] = useState('');
    const [loading, setLoading] = useState(true);
    const [autoRefresh, setAutoRefresh] = useState(false);

    const isDockerApp = app.app_type === 'docker';
    const isPythonApp = ['flask', 'django'].includes(app.app_type);

    useEffect(() => {
        loadLogs();
    }, [app.id]);

    // immediate: false — the effect above already loads on mount and on app
    // change; this adds only the repeat while auto-refresh is on.
    usePolling(loadLogs, LOG_REFRESH_MS, { enabled: autoRefresh, immediate: false });

    async function loadLogs() {
        try {
            let data;
            if (isDockerApp) {
                data = await api.getDockerAppLogs(app.id, 200);
            } else if (isPythonApp) {
                data = await api.getPythonAppLogs(app.id, 200);
            } else {
                data = { logs: 'Logs not available for this app type.' };
            }
            setLogs(logsToText(data) || 'No logs available');
        } catch (err) {
            console.error('Failed to load logs:', err);
            setLogs('Failed to load logs');
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="logs-tab">
            <div className="logs-header">
                <h3>Application Logs</h3>
                <div className="logs-controls">
                    {isPythonApp && (
                        <span className="hint">Gunicorn/systemd Logs</span>
                    )}
                    {isDockerApp && (
                        <span className="hint">Docker Compose Logs</span>
                    )}
                    <label className="checkbox-inline">
                        <input
                            type="checkbox"
                            checked={autoRefresh}
                            onChange={(e) => setAutoRefresh(e.target.checked)}
                        />
                        Auto-refresh
                    </label>
                    <Button variant="outline" size="sm" onClick={loadLogs}>
                        Refresh
                    </Button>
                </div>
            </div>
            <pre className="log-viewer">{loading ? 'Loading...' : logs}</pre>
        </div>
    );
};

export default LogsTab;
