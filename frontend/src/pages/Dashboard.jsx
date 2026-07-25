import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
    HardDrive, Activity,
    RefreshCw, Zap,
    Database, Container, Globe, Code, Layers, Server, Terminal,
    ChevronDown, Check, ChevronRight,
    Plus, Trash2, Pencil, LogIn, Power, Shield, AlertTriangle, History
} from 'lucide-react';
import api from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { useMetrics } from '../hooks/useMetrics';
import MetricsGraph from '../components/MetricsGraph';
import useDashboardLayout from '../hooks/useDashboardLayout';
import { Button } from '@/components/ui/button';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover';
import { MetricCard, Pill, Feed, FeedItem } from '@/components/ds';
import { formatRelativeTime } from '@/utils/time';
import EmptyState from '../components/EmptyState';
import PluginSlot from '../components/PluginSlot';

// Map an audit action verb to a tinted icon + semantic tone token.
// Falls back to a neutral history icon for unrecognised actions.
function getActivityVisual(action = '') {
    const a = action.toLowerCase();
    if (a.includes('login_failed')) return { tone: 'red', icon: <AlertTriangle size={15} /> };
    if (a.includes('login') || a.includes('logout') || a.includes('auth')) return { tone: 'cyan', icon: <LogIn size={15} /> };
    if (a.includes('delete') || a.includes('remove') || a.includes('disable')) return { tone: 'red', icon: <Trash2 size={15} /> };
    if (a.includes('create') || a.includes('add') || a.includes('enable')) return { tone: 'green', icon: <Plus size={15} /> };
    if (a.includes('update') || a.includes('edit') || a.includes('permission')) return { tone: 'amber', icon: <Pencil size={15} /> };
    if (a.includes('start') || a.includes('restart') || a.includes('stop')) return { tone: 'violet', icon: <Power size={15} /> };
    if (a.includes('security') || a.includes('firewall') || a.includes('ssl') || a.includes('cert')) return { tone: 'accent', icon: <Shield size={15} /> };
    return { tone: 'accent', icon: <History size={15} /> };
}

// Build a readable "actor verb target" sentence from an audit-log item.
// action is dotted (e.g. "user.create"); we humanise the verb and append the
// target_type/id when present.
function describeActivity(item) {
    const actor = item.username || (item.user_id ? `user #${item.user_id}` : 'System');
    const verb = (item.action || '').split('.').slice(1).join(' ').replace(/_/g, ' ') || (item.action || 'activity');
    const target = item.target_type
        ? `${item.target_type}${item.target_id ? ` #${item.target_id}` : ''}`
        : '';
    return { actor, verb, target };
}

// Refresh interval options in seconds
const REFRESH_OPTIONS = [
    { label: 'Off', value: 0 },
    { label: '5s', value: 5 },
    { label: '10s', value: 10 },
    { label: '30s', value: 30 },
    { label: '1m', value: 60 },
];

const Dashboard = () => {
    const navigate = useNavigate();
    const { isAdmin } = useAuth();
    const { metrics: localMetrics, loading: metricsLoading, connected, refresh: refreshMetrics } = useMetrics(true);
    const { widgets } = useDashboardLayout();
    const [apps, setApps] = useState([]);
    const [systemInfo, setSystemInfo] = useState(null);
    const [loading, setLoading] = useState(true);

    // Recent activity feed (admin-only — endpoint is /admin/activity/feed)
    const [activity, setActivity] = useState([]);
    const [activityLoading, setActivityLoading] = useState(true);
    const [refreshInterval, setRefreshInterval] = useState(() => {
        const saved = localStorage.getItem('dashboard_refresh_interval');
        return saved ? parseInt(saved, 10) : 10;
    });
    const [localUptime, setLocalUptime] = useState(null);
    const [localTime, setLocalTime] = useState(null);
    const lastServerUptime = React.useRef(null);
    const lastServerTime = React.useRef(null);

    // Server selector state
    const [servers, setServers] = useState([]);
    const [selectedServer, setSelectedServer] = useState({ id: 'local', name: 'Local (this server)' });
    const [serverMenuOpen, setServerMenuOpen] = useState(false);
    const isRemote = selectedServer.id !== 'local';

    // Remote metrics (when a non-local server is selected)
    const [remoteMetrics, setRemoteMetrics] = useState(null);
    const [remoteSystemInfo, setRemoteSystemInfo] = useState(null);
    const [remoteLoading, setRemoteLoading] = useState(false);

    // Active metrics: remote when a remote server is selected, local otherwise
    const metrics = isRemote ? remoteMetrics : localMetrics;

    const fetchRemote = useCallback(async () => {
        if (!isRemote) return;
        setRemoteLoading(true);
        try {
            const [metricsData, sysInfo] = await Promise.all([
                api.getRemoteSystemMetrics(selectedServer.id),
                api.getRemoteSystemInfo(selectedServer.id).catch(() => null)
            ]);
            setRemoteMetrics(metricsData);
            setRemoteSystemInfo(sysInfo);
        } catch (err) {
            console.error('Failed to load remote metrics:', err);
        } finally {
            setRemoteLoading(false);
        }
    }, [selectedServer.id, isRemote]);

    // Load servers list on mount
    useEffect(() => {
        api.getAvailableServers()
            .then(data => setServers(Array.isArray(data) ? data : []))
            .catch(() => setServers([{ id: 'local', name: 'Local (this server)', status: 'online' }]));
    }, []);

    // Fetch remote metrics when a remote server is selected
    useEffect(() => {
        if (!isRemote) {
            setRemoteMetrics(null);
            setRemoteSystemInfo(null);
            return;
        }

        fetchRemote();
        const interval = refreshInterval > 0
            ? setInterval(fetchRemote, refreshInterval * 1000)
            : null;

        return () => { if (interval) clearInterval(interval); };
    }, [fetchRemote, refreshInterval, isRemote]);

    // Sync local counters when server data arrives
    useEffect(() => {
        const serverUptime = metrics?.system?.uptime_seconds;
        const serverTimeStr = metrics?.time?.current_time_formatted;

        if (serverUptime && serverUptime !== lastServerUptime.current) {
            lastServerUptime.current = serverUptime;
            setLocalUptime(serverUptime);
        }

        if (serverTimeStr && serverTimeStr !== lastServerTime.current) {
            lastServerTime.current = serverTimeStr;
            try {
                const parsed = new Date(serverTimeStr);
                if (!isNaN(parsed)) {
                    setLocalTime(parsed);
                }
            } catch {
                // If parsing fails, skip
            }
        }
    }, [metrics?.system?.uptime_seconds, metrics?.time?.current_time_formatted]);

    // Tick every second - increment uptime and time locally
    useEffect(() => {
        const tick = setInterval(() => {
            if (localUptime !== null) {
                setLocalUptime(prev => prev + 1);
            }
            if (localTime !== null) {
                setLocalTime(prev => new Date(prev.getTime() + 1000));
            }
        }, 1000);

        return () => clearInterval(tick);
    }, [localUptime !== null, localTime !== null]);

    // Load initial data
    useEffect(() => {
        loadData();
    }, []);

    // Load the recent-activity feed — admins only (avoids a 403 for others)
    useEffect(() => {
        if (!isAdmin) {
            setActivityLoading(false);
            return;
        }
        let cancelled = false;
        setActivityLoading(true);
        api.getActivityFeed({ per_page: 8 })
            .then(data => {
                if (!cancelled) setActivity(data?.logs || []);
            })
            .catch(err => {
                if (!cancelled) console.error('Failed to load activity feed:', err);
            })
            .finally(() => {
                if (!cancelled) setActivityLoading(false);
            });
        return () => { cancelled = true; };
    }, [isAdmin]);

    // Polling fallback when WebSocket is not connected (local only)
    useEffect(() => {
        if (refreshInterval > 0 && !connected && !isRemote) {
            const interval = setInterval(() => {
                refreshMetrics();
            }, refreshInterval * 1000);
            return () => clearInterval(interval);
        }
    }, [refreshInterval, connected, refreshMetrics, isRemote]);

    // Save refresh interval preference
    const handleRefreshIntervalChange = useCallback((value) => {
        setRefreshInterval(value);
        localStorage.setItem('dashboard_refresh_interval', value.toString());
    }, []);

    function handleServerChange(serverId) {
        const server = servers.find(s => s.id === serverId) || { id: 'local', name: 'Local (this server)' };
        setSelectedServer(server);
        // Reset ticking counters when switching servers
        lastServerUptime.current = null;
        lastServerTime.current = null;
        setLocalUptime(null);
        setLocalTime(null);
    }

    async function loadData() {
        try {
            const [appsData, sysInfoData] = await Promise.all([
                api.getApps(),
                api.getSystemInfo().catch(() => null)
            ]);
            setApps(appsData.apps || []);
            setSystemInfo(sysInfoData);
        } catch (err) {
            console.error('Failed to load data:', err);
        } finally {
            setLoading(false);
        }
    }

    function handleRefreshAll() {
        if (isRemote) {
            fetchRemote();
        } else {
            refreshMetrics();
        }
        loadData();
    }

    function formatUptime(seconds) {
        if (!seconds) return { days: 0, hours: 0, minutes: 0 };
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return { days, hours, minutes };
    }

    function getStackIcon(type) {
        switch (type) {
            case 'docker': return <Container size={16} />;
            case 'wordpress':
            case 'php': return <Code size={16} />;
            case 'flask':
            case 'django': return <Layers size={16} />;
            default: return <Globe size={16} />;
        }
    }

    // Get uptime from local ticking counter (synced with server)
    const uptimeFormatted = formatUptime(localUptime ?? metrics?.system?.uptime_seconds);
    const activeSysInfo = isRemote ? remoteSystemInfo : systemInfo;
    const hostname = metrics?.system?.hostname || activeSysInfo?.hostname || 'server';
    const kernelVersion = metrics?.system?.kernel || activeSysInfo?.kernel || '-';
    const ipAddress = metrics?.system?.ip_address || activeSysInfo?.ip_address || '-';
    const serverTime = metrics?.time;

    // Format the local ticking clock
    const displayTime = localTime
        ? localTime.toLocaleTimeString('en-US', { hour12: false })
        : serverTime?.current_time_formatted?.split(' ')[1] || '--:--:--';

    // Show green if we have metrics data (regardless of transport — WS or HTTP poll)
    const isConnected = isRemote ? !remoteLoading && !!remoteMetrics : !!localMetrics;

    if (loading && metricsLoading) {
        return <EmptyState loading loadingVariant="chart" title="Loading dashboard..." />;
    }

    return (
        <div className="page-container dashboard-page">
            {/* Top Bar */}
            <div className="top-bar">
                <div className="server-identity">
                    <Popover open={serverMenuOpen} onOpenChange={setServerMenuOpen}>
                        <PopoverTrigger asChild>
                            <button
                                type="button"
                                className={`srv-switch${serverMenuOpen ? ' srv-switch--open' : ''}`}
                                aria-label="Switch server"
                            >
                                <span className="srv-switch__name">{hostname}</span>
                                <ChevronDown size={18} className="srv-switch__chev" aria-hidden="true" />
                            </button>
                        </PopoverTrigger>
                        <PopoverContent
                            align="start"
                            sideOffset={7}
                            className="env-menu"
                        >
                            <div className="env-menu__head">Connected servers · {servers.length}</div>
                            {servers.map(server => {
                                const online = server.status === 'online';
                                const active = server.id === selectedServer.id;
                                return (
                                    <button
                                        type="button"
                                        key={server.id}
                                        className="env-opt"
                                        onClick={() => { handleServerChange(server.id); setServerMenuOpen(false); }}
                                    >
                                        <span
                                            className={`env-opt__dot env-opt__dot--${online ? 'online' : 'offline'}`}
                                            aria-hidden="true"
                                        ></span>
                                        <span className="env-opt__body">
                                            <span className="env-opt__name">{server.name}</span>
                                            <span className="env-opt__meta">
                                                {server.group_name || (server.is_local ? 'local' : server.id)}
                                                {' · '}
                                                {online ? 'online' : 'offline'}
                                            </span>
                                        </span>
                                        {active && (
                                            <span className="env-opt__check" aria-hidden="true">
                                                <Check size={15} />
                                            </span>
                                        )}
                                    </button>
                                );
                            })}
                        </PopoverContent>
                    </Popover>
                    <div className="server-details">
                        <span
                            className={`conn-status conn-status--${isConnected ? 'live' : 'down'}`}
                            role="status"
                        >
                            <span className="conn-status__dot" aria-hidden="true"></span>
                            {isConnected ? 'Live' : 'Reconnecting'}
                        </span>
                        <span className="detail-separator">·</span>
                        <span>IP: {ipAddress}</span>
                        <span className="detail-separator">·</span>
                        <span>KERNEL: {kernelVersion}</span>
                        <span className="detail-separator">·</span>
                        <span>UPTIME: {uptimeFormatted.days}d {String(uptimeFormatted.hours).padStart(2, '0')}h {String(uptimeFormatted.minutes).padStart(2, '0')}m</span>
                    </div>
                </div>
                <div className="top-bar-right">
                    <div className="clock-widget">
                        <span className="clock-time">{displayTime}</span>
                        <span className="clock-zone">{serverTime?.timezone_id || 'UTC'}</span>
                    </div>
                    <div className="refresh-control">
                        <button type="button"
                            className="btn-refresh"
                            onClick={handleRefreshAll}
                            title="Refresh now"
                        >
                            <RefreshCw size={14} />
                        </button>
                        <select
                            value={refreshInterval}
                            onChange={(e) => handleRefreshIntervalChange(parseInt(e.target.value, 10))}
                            className="refresh-select"
                            title="Auto-refresh interval"
                        >
                            {REFRESH_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                        </select>
                    </div>
                </div>
            </div>

            {/* Extension slot: widgets contributed to the top of the dashboard */}
            <PluginSlot name="dashboard.top" />

            {/* Grid Container */}
            <div className="grid-container">
                {widgets.filter(w => w.visible).map(w => {
                    const WIDGET_RENDERERS = {
                        cpu: () => (
                            <MetricCard
                                key="cpu"
                                className="dash-kpi"
                                tone="accent"
                                icon={<Zap size={16} />}
                                value={(metrics?.cpu?.percent || 0).toFixed(1)}
                                unit="%"
                                label="CPU"
                            >
                                <div className="sk-kpi__sub">
                                    <span>Cores {metrics?.cpu?.count_logical || 0}</span>
                                </div>
                            </MetricCard>
                        ),
                        ram: () => (
                            <MetricCard
                                key="ram"
                                className="dash-kpi"
                                tone="green"
                                icon={<Database size={16} />}
                                value={metrics?.memory?.ram?.used_human || '0 GB'}
                                label="RAM"
                            >
                                <div className="sk-kpi__sub">
                                    <span>Total {metrics?.memory?.ram?.total_human || '0 GB'}</span>
                                    <span>Cached {metrics?.memory?.ram?.cached_human || '0 GB'}</span>
                                </div>
                            </MetricCard>
                        ),
                        network: () => (
                            <MetricCard
                                key="network"
                                className="dash-kpi"
                                tone="cyan"
                                icon={<Activity size={16} />}
                                value={metrics?.network?.io?.bytes_sent_human || '0 B'}
                                unit="sent"
                                label="Network"
                            >
                                <div className="sk-kpi__sub">
                                    <span>In {metrics?.network?.io?.bytes_recv_human || '0 B'}</span>
                                    <span>Out {metrics?.network?.io?.bytes_sent_human || '0 B'}</span>
                                </div>
                            </MetricCard>
                        ),
                        disk: () => (
                            <MetricCard
                                key="disk"
                                className="dash-kpi"
                                tone="amber"
                                icon={<HardDrive size={16} />}
                                value={(metrics?.disk?.partitions?.[0]?.percent || 0).toFixed(1)}
                                unit="%"
                                label="Disk"
                            >
                                <div className="sk-kpi__sub">
                                    <span>Used {metrics?.disk?.partitions?.[0]?.used_human || '0 GB'}</span>
                                    <span>Free {metrics?.disk?.partitions?.[0]?.free_human || '0 GB'}</span>
                                </div>
                            </MetricCard>
                        ),
                        chart: () => (
                            <div key="chart" className="chart-panel">
                                <MetricsGraph timezone={serverTime?.timezone_id} />
                            </div>
                        ),
                        specs: () => (
                            <div key="specs" className="spec-panel">
                                <h3 className="spec-panel-title">Quick Actions</h3>
                                <button type="button" className="btn-action" onClick={() => navigate('/servers')}>
                                    <span>Manage Servers</span>
                                    <span><Server size={14} /></span>
                                </button>
                                <button type="button" className="btn-action" onClick={() => navigate('/docker')}>
                                    <span>Docker Containers</span>
                                    <span><Container size={14} /></span>
                                </button>
                                <button type="button" className="btn-action" onClick={() => navigate('/terminal')}>
                                    <span>Open Terminal</span>
                                    <span><Terminal size={14} /></span>
                                </button>

                                <h3 className="spec-panel-title mt-6">Hardware Specs</h3>
                                <div className="spec-row">
                                    <span className="spec-label">Processor</span>
                                    <span className="spec-data">{activeSysInfo?.cpu?.model || 'N/A'}</span>
                                </div>
                                <div className="spec-row">
                                    <span className="spec-label">Architecture</span>
                                    <span className="spec-data">{activeSysInfo?.cpu?.architecture || 'N/A'}</span>
                                </div>
                                <div className="spec-row">
                                    <span className="spec-label">Swap Memory</span>
                                    <span className="spec-data">{metrics?.memory?.swap?.total_human || 'N/A'}</span>
                                </div>
                            </div>
                        ),
                        processes: () => (
                            <div key="processes" className="table-panel">
                                <div className="table-header">
                                    <span>Applications</span>
                                    <Button variant="outline" size="sm" onClick={loadData}>
                                        <RefreshCw size={14} />
                                    </Button>
                                </div>
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>ID</th>
                                            <th>Name</th>
                                            <th>Type</th>
                                            <th>Status</th>
                                            <th>Domain</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {apps.length === 0 ? (
                                            <tr>
                                                <td colSpan="5" className="text-center text-gray-400">
                                                    No applications found
                                                </td>
                                            </tr>
                                        ) : (
                                            apps.slice(0, 6).map(app => (
                                                <tr key={app.id} onClick={() => navigate(`/apps/${app.id}`)} className="cursor-pointer">
                                                    <td>{app.id}</td>
                                                    <td>
                                                        <div className="app-name-cell">
                                                            <span className="app-icon-mini" aria-hidden="true">{getStackIcon(app.app_type)}</span>
                                                            <Link
                                                                to={`/apps/${app.id}`}
                                                                className="app-name-link"
                                                                onClick={(e) => e.stopPropagation()}
                                                            >
                                                                {app.name}
                                                            </Link>
                                                        </div>
                                                    </td>
                                                    <td>{app.app_type}</td>
                                                    <td>
                                                        <Pill kind={app.status === 'running' ? 'green' : 'amber'}>
                                                            {app.status?.toUpperCase()}
                                                        </Pill>
                                                    </td>
                                                    <td>{app.domains?.[0]?.name || '-'}</td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        ),
                    };
                    return WIDGET_RENDERERS[w.id]?.();
                })}

                {/* Recent activity — admin-only audit feed, paired with Applications */}
                {isAdmin && (
                    <div className="activity-panel">
                        <div className="activity-panel__head">
                            <h3 className="activity-panel__title">Recent Activity</h3>
                            <Link to="/security/audit" className="activity-panel__link">
                                Audit log <ChevronRight size={14} aria-hidden="true" />
                            </Link>
                        </div>
                        {activityLoading ? (
                            <div className="activity-panel__empty">Loading activity…</div>
                        ) : activity.length === 0 ? (
                            <div className="activity-panel__empty">No recent activity</div>
                        ) : (
                            <Feed>
                                {activity.map(item => {
                                    const { tone, icon } = getActivityVisual(item.action);
                                    const { actor, verb, target } = describeActivity(item);
                                    return (
                                        <FeedItem
                                            key={item.id}
                                            icon={icon}
                                            tone={tone}
                                            time={formatRelativeTime(item.created_at)}
                                        >
                                            <b>{actor}</b> {verb}
                                            {target && <> · {target}</>}
                                        </FeedItem>
                                    );
                                })}
                            </Feed>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default Dashboard;
