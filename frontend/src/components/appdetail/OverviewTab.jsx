import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { formatBytes } from '@/utils/formatBytes';
import { useConfirm } from '../../hooks/useConfirm';
import PrivateURLSection from '../PrivateURLSection';
import LinkedAppsSection from '../LinkedAppsSection';
import LinkAppModal from '../LinkAppModal';
import TagsPanel from '../shared/TagsPanel';
import EnvironmentVariablesPanel from '../shared/EnvironmentVariablesPanel';
import { Button } from '@/components/ui/button';

// Overview Tab with new grid layout
const OverviewTab = ({ app, onUpdate }) => {
    const navigate = useNavigate();
    const { confirm: confirmOverview } = useConfirm();
    const [status, setStatus] = useState(null);
    const [appStatus, setAppStatus] = useState(null);
    const [linkedApps, setLinkedApps] = useState([]);
    const [showLinkModal, setShowLinkModal] = useState(false);
    const [linkLoading, setLinkLoading] = useState(false);
    const [containerStats, setContainerStats] = useState(null);

    useEffect(() => {
        if (['flask', 'django'].includes(app.app_type)) {
            loadStatus();
        }
        loadAppStatus();
        loadLinkedApps();
        if (app.app_type === 'docker') {
            loadContainerStats();
        }
    }, [app]);

    async function loadStatus() {
        try {
            const data = await api.getPythonAppStatus(app.id);
            setStatus(data);
        } catch (err) {
            console.error('Failed to load status:', err);
        }
    }

    async function loadAppStatus() {
        try {
            const data = await api.getAppStatus(app.id);
            setAppStatus(data);
        } catch (err) {
            console.error('Failed to load app status:', err);
        }
    }

    async function loadLinkedApps() {
        try {
            const data = await api.getLinkedApps(app.id);
            setLinkedApps(data.linked_apps || []);
        } catch (err) {
            console.error('Failed to load linked apps:', err);
        }
    }

    async function loadContainerStats() {
        try {
            // Try to get container stats for docker apps
            const containers = await api.getContainers(true);
            const appContainer = containers.containers?.find(c =>
                c.name?.includes(app.name) || c.name?.includes(app.slug)
            );
            if (appContainer && appContainer.state === 'running') {
                const stats = await api.getContainerStats(appContainer.id);
                setContainerStats(stats.stats);
            }
        } catch (err) {
            console.error('Failed to load container stats:', err);
        }
    }

    async function handleUnlink() {
        const confirmed = await confirmOverview({ title: 'Unlink Apps', message: 'Are you sure you want to unlink these apps? Database credentials will remain unchanged.', variant: 'warning' });
        if (!confirmed) {
            return;
        }
        setLinkLoading(true);
        try {
            await api.unlinkApp(app.id);
            onUpdate();
            loadLinkedApps();
        } catch (err) {
            console.error('Failed to unlink apps:', err);
        } finally {
            setLinkLoading(false);
        }
    }

    function handleLinked() {
        onUpdate();
        loadLinkedApps();
    }

    function parseResourceValue(value) {
        if (!value) return 0;
        return parseFloat(value.replace('%', '')) || 0;
    }

    return (
        <div className="app-overview-grid">
            {/* Left Column */}
            <div className="app-overview-left">
                {/* Application Info Panel */}
                <div className="app-panel">
                    <div className="app-panel-header">Application Info</div>
                    <div className="app-panel-body">
                        <div className="app-info-grid">
                            <div className="app-info-item">
                                <span className="app-info-label">Type</span>
                                <span className="app-info-value">{app.app_type === 'docker' ? 'Docker Container' : app.app_type.toUpperCase()}</span>
                            </div>
                            <div className="app-info-item">
                                <span className="app-info-label">Port</span>
                                <span className="app-info-value">
                                    {app.port || '-'}
                                    {appStatus && app.port && (
                                        <span className={`port-indicator ${appStatus.port_accessible ? 'accessible' : ''}`}>
                                            {appStatus.port_accessible ? ' (accessible)' : ' (not accessible)'}
                                        </span>
                                    )}
                                </span>
                            </div>
                            {app.python_version && (
                                <div className="app-info-item">
                                    <span className="app-info-label">Python Version</span>
                                    <span className="app-info-value">{app.python_version}</span>
                                </div>
                            )}
                            {app.php_version && (
                                <div className="app-info-item">
                                    <span className="app-info-label">PHP Version</span>
                                    <span className="app-info-value">{app.php_version}</span>
                                </div>
                            )}
                            <div className="app-info-item full-width">
                                <span className="app-info-label">Root Path</span>
                                <div><span className="app-path-value">{app.root_path || `/var/serverkit/apps/${app.name}`}</span></div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Routing Diagnostics Panel (Docker apps only) */}
                {app.app_type === 'docker' && (
                    <RoutingDiagnosticsPanel appId={app.id} />
                )}

                {/* Environment Linking Panel */}
                <div className="app-panel">
                    <div className="app-panel-header">Environment Linking</div>
                    <div className="app-panel-body">
                        <p className="app-panel-hint">
                            Link this app to another to create a production/development pair. Linked apps can share database credentials.
                        </p>
                        <LinkedAppsSection
                            app={app}
                            linkedApps={linkedApps}
                            onLink={() => setShowLinkModal(true)}
                            onUnlink={handleUnlink}
                            onNavigate={(appId) => navigate(`/apps/${appId}`)}
                            loading={linkLoading}
                            compact
                        />
                    </div>
                </div>

                {/* Process Status (Python apps) */}
                {status && (
                    <div className="app-panel">
                        <div className="app-panel-header">Process Status</div>
                        <div className="app-panel-body">
                            <div className="app-info-grid">
                                <div className="app-info-item">
                                    <span className="app-info-label">Service</span>
                                    <span className="app-info-value mono">{status.service_name}</span>
                                </div>
                                <div className="app-info-item">
                                    <span className="app-info-label">State</span>
                                    <span className="app-info-value">{status.active_state} ({status.sub_state})</span>
                                </div>
                                {status.main_pid !== '0' && (
                                    <div className="app-info-item">
                                        <span className="app-info-label">PID</span>
                                        <span className="app-info-value mono">{status.main_pid}</span>
                                    </div>
                                )}
                                {status.memory && status.memory !== '0' && (
                                    <div className="app-info-item">
                                        <span className="app-info-label">Memory</span>
                                        <span className="app-info-value">{formatBytes(parseInt(status.memory))}</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {/* Domains Panel */}
                {app.domains && app.domains.length > 0 && (
                    <div className="app-panel">
                        <div className="app-panel-header">Domains</div>
                        <div className="app-panel-body">
                            <div className="domains-list">
                                {app.domains.map(domain => (
                                    <div key={domain.id} className="domain-item">
                                        <a href={`https://${domain.name}`} target="_blank" rel="noopener noreferrer">
                                            {domain.name}
                                        </a>
                                        {domain.ssl_enabled && (
                                            <span className="ssl-badge">SSL</span>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* Right Column */}
            <div className="app-overview-right">
                {/* Private URL Panel (Docker apps with port) */}
                {app.app_type === 'docker' && app.port && (
                    <PrivateURLSection app={app} onUpdate={onUpdate} />
                )}

                {/* Live Resources Panel */}
                {app.app_type === 'docker' && (
                    <div className="app-panel">
                        <div className="app-panel-header">Live Resources</div>
                        <div className="app-panel-body">
                            <div className="resource-bar-container">
                                <div className="resource-bar-header">
                                    <span className="resource-bar-label">CPU Load</span>
                                    <span className="resource-bar-value">
                                        {containerStats ? `${parseResourceValue(containerStats.CPUPerc).toFixed(0)}%` : '-'}
                                    </span>
                                </div>
                                <div className="resource-bar-track">
                                    <div
                                        className="resource-bar-fill cpu"
                                        style={{ width: `${containerStats ? parseResourceValue(containerStats.CPUPerc) : 0}%` }}
                                    />
                                </div>
                            </div>
                            <div className="resource-bar-container">
                                <div className="resource-bar-header">
                                    <span className="resource-bar-label">RAM Usage</span>
                                    <span className="resource-bar-value">
                                        {containerStats?.MemUsage || '-'}
                                    </span>
                                </div>
                                <div className="resource-bar-track">
                                    <div
                                        className="resource-bar-fill ram"
                                        style={{ width: `${containerStats ? parseResourceValue(containerStats.MemPerc) : 0}%` }}
                                    />
                                </div>
                            </div>
                            {!containerStats && app.status !== 'running' && (
                                <p className="resource-hint">Start the container to see live resources.</p>
                            )}
                        </div>
                    </div>
                )}

                {/* Tags Panel (polymorphic shared resource) */}
                <div className="app-panel">
                    <div className="app-panel-header">Tags</div>
                    <div className="app-panel-body">
                        <TagsPanel resourceType="application" resourceId={app.id} />
                    </div>
                </div>

                {/* Shared Variables Panel (resolved from attached groups) */}
                <div className="app-panel">
                    <div className="app-panel-body">
                        <EnvironmentVariablesPanel resourceType="application" resourceId={app.id} />
                    </div>
                </div>
            </div>

            {showLinkModal && (
                <LinkAppModal
                    app={app}
                    onClose={() => setShowLinkModal(false)}
                    onLinked={handleLinked}
                />
            )}
        </div>
    );
};

// Routing Diagnostics Panel
const RoutingDiagnosticsPanel = ({ appId }) => {
    const [diagnostics, setDiagnostics] = useState(null);
    const [loading, setLoading] = useState(false);
    const [lastChecked, setLastChecked] = useState(null);

    async function runDiagnostics() {
        setLoading(true);
        try {
            const data = await api.getDomainRoutingDiagnostics(appId);
            setDiagnostics(data);
            setLastChecked(new Date());
        } catch (err) {
            console.error('Failed to run diagnostics:', err);
        } finally {
            setLoading(false);
        }
    }

    const isHealthy = diagnostics?.health?.overall;

    return (
        <div className="app-panel">
            <div className="app-panel-header">
                <span>Routing Diagnostics</span>
                <span className="app-panel-header-actions">
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={runDiagnostics}
                        disabled={loading}
                    >
                        {loading ? 'Checking...' : 'Run Diagnostics'}
                    </Button>
                </span>
            </div>
            <div className="app-panel-body">
                {diagnostics ? (
                    <>
                        <div className={`diag-status ${isHealthy ? 'healthy' : 'unhealthy'}`}>
                            <div className={`diag-icon ${isHealthy ? 'healthy' : 'unhealthy'}`}>
                                {isHealthy ? '✓' : '✗'}
                            </div>
                            <div className="diag-text">
                                <h4>{isHealthy ? 'Configuration Healthy' : 'Issues Detected'}</h4>
                                <p>
                                    {lastChecked && `Last checked: ${Math.round((Date.now() - lastChecked) / 60000)} minutes ago. `}
                                    {isHealthy ? 'No routing issues detected.' : 'Some checks failed.'}
                                </p>
                            </div>
                        </div>
                        {diagnostics.health?.issues?.length > 0 && (
                            <ul className="diag-issues">
                                {diagnostics.health.issues.map((issue, i) => (
                                    <li key={i}>{issue}</li>
                                ))}
                            </ul>
                        )}
                    </>
                ) : (
                    <p className="app-panel-hint">
                        Click &quot;Run Diagnostics&quot; to check routing configuration and identify issues.
                    </p>
                )}
            </div>
        </div>
    );
};

export default OverviewTab;
