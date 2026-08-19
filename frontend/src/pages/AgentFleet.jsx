import { useState, useEffect, useCallback } from 'react';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import {
    Shield,
    Activity,
    Download,
    RefreshCw,
    CheckCircle,
    AlertCircle,
    Clock,
    Zap,
    Search,
    ChevronRight,
    Server,
    Layers,
    Package,
    Play,
    Pause,
    XCircle,
    Wifi,
    WifiOff,
    RotateCcw,
    Info
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { MetricCard, KpiBand, Pill, Gauge, DataTable, DataTableFooter, statusKind } from '@/components/ds';

const AgentFleet = () => {
    const [activeTab, setActiveTab] = useState('dashboard');
    const [loading, setLoading] = useState(true);
    const [health, setHealth] = useState(null);
    const [versions, setVersions] = useState([]);
    const [discoveredAgents, setDiscoveredAgents] = useState([]);
    const [pendingServers, setPendingServers] = useState([]);
    const [rollouts, setRollouts] = useState([]);
    const [queuedCommands, setQueuedCommands] = useState([]);
    const [diagnostics, setDiagnostics] = useState(null);
    const [diagnosticsServerId, setDiagnosticsServerId] = useState('');
    const [isScanning, setIsScanning] = useState(false);
    const [selectedVersion, setSelectedVersion] = useState('');
    const [rolloutStrategy, setRolloutStrategy] = useState('all');
    const [rolloutBatchSize, setRolloutBatchSize] = useState(5);
    const [rolloutDelay, setRolloutDelay] = useState(10);
    const toast = useToast();
    const { user } = useAuth();

    useEffect(() => {
        fetchData();
    }, [activeTab]);

    // Publish the Refresh button to the shared tab-group top bar; re-registers
    // on `loading` so the spinner/disabled state stays in sync.
    useTopbarActions(() =>
        <Button size="sm" onClick={fetchData} disabled={loading}>
            <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
            Refresh
        </Button>,
        [loading]
    );

    const fetchData = async () => {
        setLoading(true);
        try {
            if (activeTab === 'dashboard') {
                const data = await api.getFleetHealth();
                setHealth(data);
            } else if (activeTab === 'versions') {
                const data = await api.getAgentVersions();
                setVersions(data);
            } else if (activeTab === 'rollouts') {
                const [rolloutData, versionData] = await Promise.all([
                    api.getRollouts(),
                    api.getAgentVersions()
                ]);
                setRollouts(rolloutData);
                setVersions(versionData);
                if (versionData.length > 0 && !selectedVersion) {
                    setSelectedVersion(versionData[0].id);
                }
            } else if (activeTab === 'discovery') {
                const data = await api.getDiscoveredAgents();
                setDiscoveredAgents(data);
            } else if (activeTab === 'approvals') {
                const data = await api.getServers();
                setPendingServers((data.servers || data).filter(s => s.status === 'pending'));
            } else if (activeTab === 'queue') {
                const data = await api.getQueuedCommands();
                setQueuedCommands(data);
            }
        } catch (error) {
            console.error('Error fetching fleet data:', error);
            toast.error('Failed to fetch fleet data');
        } finally {
            setLoading(false);
        }
    };

    const startDiscovery = async () => {
        setIsScanning(true);
        try {
            toast.info('Scanning network for agents...');
            await api.startDiscovery(10);
            const data = await api.getDiscoveredAgents();
            setDiscoveredAgents(data);
            toast.success(`Discovered ${data.length} agents`);
        } catch (error) {
            toast.error('Discovery scan failed');
        } finally {
            setIsScanning(false);
        }
    };

    const approveAgent = async (serverId) => {
        try {
            await api.approveRegistration(serverId);
            toast.success('Agent registration approved');
            fetchData();
        } catch (error) {
            toast.error('Failed to approve agent');
        }
    };

    const rejectAgent = async (serverId) => {
        try {
            await api.rejectRegistration(serverId);
            toast.success('Agent registration rejected');
            fetchData();
        } catch (error) {
            toast.error('Failed to reject agent');
        }
    };

    const triggerUpgrade = async () => {
        if (!selectedVersion) {
            toast.error('Select a target version');
            return;
        }

        try {
            if (rolloutStrategy === 'all') {
                await api.upgradeFleet([], selectedVersion);
                toast.success('Upgrade triggered for all online agents');
            } else {
                const data = {
                    version_id: selectedVersion,
                    strategy: rolloutStrategy,
                    batch_size: rolloutStrategy === 'canary' ? 1 : rolloutBatchSize,
                    delay_minutes: rolloutDelay
                };
                await api.startRollout(data);
                toast.success('Staged rollout started');
            }
            fetchData();
        } catch (error) {
            toast.error('Failed to trigger upgrade');
        }
    };

    const cancelRollout = async (rolloutId) => {
        try {
            await api.cancelRollout(rolloutId);
            toast.success('Rollout cancelled');
            fetchData();
        } catch (error) {
            toast.error('Failed to cancel rollout');
        }
    };

    const retryCommand = async (commandId) => {
        try {
            await api.retryCommand(commandId);
            toast.success('Command retry triggered');
            fetchData();
        } catch (error) {
            toast.error('Failed to retry command');
        }
    };

    const loadDiagnostics = async (serverId) => {
        try {
            const data = await api.getServerDiagnostics(serverId);
            setDiagnostics(data);
            setDiagnosticsServerId(serverId);
        } catch (error) {
            toast.error('Failed to load diagnostics');
        }
    };

    // Columns for the shared DataTable. Cell markup and classNames are
    // identical to the hand-rolled tables they replace. No in-page toolbar
    // rows on this page (Refresh lives in the shared top bar), so each table
    // runs uncontrolled with a storageKey instead of SortMenu/ColumnsMenu.
    const versionColumns = [
        {
            key: 'version',
            header: 'Version',
            sortable: true,
            hideable: false,
            sortValue: (v) => v.version || '',
            cellClassName: 'font-semibold',
            render: (v) => `v${v.version}`,
        },
        {
            key: 'channel',
            header: 'Channel',
            sortable: true,
            sortValue: (v) => v.channel || '',
            render: (v) => (
                <Pill kind={v.channel === 'stable' ? 'green' : 'amber'}>{v.channel}</Pill>
            ),
        },
        {
            key: 'published',
            header: 'Published',
            sortable: true,
            sortValue: (v) => (v.published_at ? new Date(v.published_at).getTime() : null),
            render: (v) => new Date(v.published_at).toLocaleDateString(),
        },
        {
            key: 'compat',
            header: 'Panel Compatibility',
            render: (v) => `${v.min_panel_version || 'Any'} - ${v.max_panel_version || 'Latest'}`,
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (v) => (v.is_active ? 'Active' : 'Inactive'),
            render: (v) => (
                <Pill kind={v.is_active ? 'green' : 'gray'}>
                    {v.is_active ? 'Active' : 'Inactive'}
                </Pill>
            ),
        },
    ];

    const rolloutColumns = [
        {
            key: 'version',
            header: 'Version',
            sortable: true,
            hideable: false,
            sortValue: (r) => r.version || '',
            cellClassName: 'font-semibold',
            render: (r) => `v${r.version}`,
        },
        {
            key: 'strategy',
            header: 'Strategy',
            sortable: true,
            sortValue: (r) => r.strategy || '',
            render: (r) => r.strategy,
        },
        {
            key: 'progress',
            header: 'Progress',
            sortable: true,
            sortValue: (r) => (r.total_servers > 0 ? (r.processed_servers / r.total_servers * 100) : 0),
            render: (r) => (
                <div className="flex items-center gap-3">
                    <Gauge
                        className="w-24"
                        value={r.total_servers > 0 ? (r.processed_servers / r.total_servers * 100) : 0}
                        color={r.status === 'failed' ? 'var(--red)' : r.status === 'completed' ? 'var(--green)' : 'var(--accent-bright)'}
                    />
                    <span className="text-sm text-gray-500">
                        {r.processed_servers}/{r.total_servers}
                        {r.failed_servers > 0 && (
                            <span className="text-red-500 ml-1">({r.failed_servers} failed)</span>
                        )}
                    </span>
                </div>
            ),
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (r) => r.status || '',
            render: (r) => (
                <Pill kind={statusKind(r.status)}>{r.status}</Pill>
            ),
        },
        {
            key: 'started',
            header: 'Started',
            sortable: true,
            sortValue: (r) => (r.started_at ? new Date(r.started_at).getTime() : null),
            cellClassName: 'text-sm',
            render: (r) => (r.started_at ? new Date(r.started_at).toLocaleString() : '-'),
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            cellClassName: 'actions',
            render: (r) => (
                <>
                    {r.status === 'running' && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="text-red-600"
                            onClick={() => cancelRollout(r.id)}
                            title="Cancel Rollout"
                        >
                            <XCircle size={14} /> Cancel
                        </Button>
                    )}
                    {r.error && (
                        <span className="text-xs text-red-500" title={r.error}>
                            <AlertCircle size={14} />
                        </span>
                    )}
                </>
            ),
        },
    ];

    const queueColumns = [
        {
            key: 'server',
            header: 'Server',
            sortable: true,
            hideable: false,
            sortValue: (cmd) => cmd.server_id || '',
            render: (cmd) => `${cmd.server_id?.slice(0, 8)}...`,
        },
        {
            key: 'command',
            header: 'Command',
            sortable: true,
            sortValue: (cmd) => cmd.command_type || '',
            cellClassName: 'font-mono text-sm',
            render: (cmd) => cmd.command_type,
        },
        {
            key: 'retries',
            header: 'Retries',
            sortable: true,
            sortValue: (cmd) => cmd.retry_count ?? null,
            render: (cmd) => (
                <span className={cmd.retry_count > 0 ? 'text-yellow-600' : ''}>
                    {cmd.retry_count}/{cmd.max_retries}
                </span>
            ),
        },
        {
            key: 'queued',
            header: 'Queued At',
            sortable: true,
            sortValue: (cmd) => (cmd.created_at ? new Date(cmd.created_at).getTime() : null),
            cellClassName: 'text-sm',
            render: (cmd) => new Date(cmd.created_at).toLocaleString(),
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            cellClassName: 'actions',
            render: (cmd) => (
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => retryCommand(cmd.id)}
                    title="Retry now"
                >
                    <RotateCcw size={14} /> Retry
                </Button>
            ),
        },
    ];

    const approvalColumns = [
        {
            key: 'name',
            header: 'Server Name',
            sortable: true,
            hideable: false,
            sortValue: (server) => server.name || '',
            cellClassName: 'font-semibold',
            render: (server) => server.name,
        },
        {
            key: 'ip',
            header: 'IP Address',
            sortable: true,
            sortValue: (server) => server.ip_address || '',
            render: (server) => server.ip_address || 'N/A',
        },
        {
            key: 'requested',
            header: 'Requested',
            sortable: true,
            sortValue: (server) => (server.created_at ? new Date(server.created_at).getTime() : null),
            render: (server) => new Date(server.created_at).toLocaleString(),
        },
        {
            key: 'agent',
            header: 'Agent Version',
            sortable: true,
            sortValue: (server) => server.agent_version || '',
            render: (server) => `v${server.agent_version || 'Unknown'}`,
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            cellClassName: 'actions',
            render: (server) => (
                <>
                    <Button
                        size="sm"
                        className="flex items-center gap-1"
                        onClick={() => approveAgent(server.id)}
                    >
                        <CheckCircle size={14} /> Approve
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-600"
                        onClick={() => rejectAgent(server.id)}
                    >
                        <XCircle size={14} /> Reject
                    </Button>
                </>
            ),
        },
    ];

    return (
        <div className="sk-tabgroup__inner">
            <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList>
                    {[
                        { key: 'dashboard', icon: Activity, label: 'Dashboard' },
                        { key: 'versions', icon: Package, label: 'Versions' },
                        { key: 'rollouts', icon: Zap, label: 'Rollouts' },
                        { key: 'queue', icon: Clock, label: 'Command Queue' },
                        { key: 'discovery', icon: Search, label: 'Discovery' },
                        { key: 'approvals', icon: Shield, label: 'Approvals' },
                    ].map(tab => (
                        <TabsTrigger key={tab.key} value={tab.key}>
                            <tab.icon size={18} />
                            {tab.label}
                            {tab.key === 'approvals' && pendingServers.length > 0 && (
                                <Badge variant="destructive" className="ml-2">{pendingServers.length}</Badge>
                            )}
                            {tab.key === 'queue' && queuedCommands.length > 0 && (
                                <Badge variant="warning" className="ml-2">{queuedCommands.length}</Badge>
                            )}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>

            <div className="tab-content mt-6">
                {/* ==================== Dashboard ==================== */}
                {activeTab === 'dashboard' && health && (
                    <div className="space-y-6">
                        <KpiBand>
                            <MetricCard icon={<Server size={16} />} tone="accent" label="Total Agents" value={health.total_servers} />
                            <MetricCard icon={<CheckCircle size={16} />} tone="green" label="Online" value={health.online_servers} />
                            <MetricCard icon={<AlertCircle size={16} />} tone="red" label="Offline" value={health.offline_servers} />
                            <MetricCard icon={<Zap size={16} />} tone="cyan" label="Success Rate" value={`${health.command_success_rate}%`} />
                        </KpiBand>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            <div className="card">
                                <div className="card-header">
                                    <h2>Fleet Health Summary</h2>
                                </div>
                                <div className="card-body">
                                    <div className="space-y-4">
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-600">Overall Uptime</span>
                                            <span className="font-semibold text-green-600">{health.uptime_percentage?.toFixed(2)}%</span>
                                        </div>
                                        <Gauge value={health.uptime_percentage} color="var(--green)" />

                                        <div className="flex justify-between items-center mt-6">
                                            <span className="text-gray-600">Avg Heartbeat Latency</span>
                                            <span className="font-semibold">{health.avg_heartbeat_latency} ms</span>
                                        </div>
                                        <Gauge value={Math.min(100, health.avg_heartbeat_latency / 2)} color="var(--cyan)" />

                                        {health.queued_commands > 0 && (
                                            <div className="fleet-warnrow mt-4">
                                                <span className="flex items-center gap-2">
                                                    <Clock size={16} /> Queued Commands
                                                </span>
                                                <span className="font-semibold">{health.queued_commands}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="card">
                                <div className="card-header">
                                    <h2>Version Distribution</h2>
                                </div>
                                <div className="card-body">
                                    <div className="space-y-4">
                                        {Object.entries(health.version_distribution || {}).map(([version, count]) => (
                                            <div key={version} className="space-y-1">
                                                <div className="flex justify-between text-sm">
                                                    <span>v{version}</span>
                                                    <span className="text-gray-500">{count} agents ({(count / health.total_servers * 100).toFixed(0)}%)</span>
                                                </div>
                                                <Gauge value={count / health.total_servers * 100} color="var(--accent-bright)" />
                                            </div>
                                        ))}
                                        {Object.keys(health.version_distribution || {}).length === 0 && (
                                            <p className="text-gray-500 text-center py-4">No agents registered yet.</p>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ==================== Versions ==================== */}
                {activeTab === 'versions' && (
                    <div className="card">
                        <div className="card-header">
                            <h2>Agent Versions</h2>
                        </div>
                        <DataTable
                            columns={versionColumns}
                            data={versions}
                            keyField="id"
                            storageKey="serverkit-table-fleet-versions"
                            className="overflow-x-auto"
                            emptyState={(
                                <div className="text-center py-8 text-gray-500">
                                    No agent versions registered in database.
                                </div>
                            )}
                            footer={(
                                <DataTableFooter
                                    shown={versions.length}
                                    total={versions.length}
                                    noun="version"
                                />
                            )}
                        />
                        {versions.length > 0 && versions[0].release_notes && (
                            <div className="card-body border-t">
                                <h3 className="text-sm font-semibold mb-2">Latest Release Notes (v{versions[0].version})</h3>
                                <p className="text-sm text-gray-600 whitespace-pre-wrap">{versions[0].release_notes}</p>
                            </div>
                        )}
                    </div>
                )}

                {/* ==================== Rollouts ==================== */}
                {activeTab === 'rollouts' && (
                    <div className="space-y-6">
                        <div className="card">
                            <div className="card-header">
                                <h2>Trigger Fleet Upgrade</h2>
                            </div>
                            <div className="card-body">
                                <p className="text-gray-600 mb-4">
                                    Push a specific agent version to multiple servers at once.
                                </p>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                                    <div className="form-group">
                                        <label>Target Version</label>
                                        <select
                                            className="form-select w-full"
                                            value={selectedVersion}
                                            onChange={e => setSelectedVersion(e.target.value)}
                                        >
                                            <option value="">Select version...</option>
                                            {versions.map(v => (
                                                <option key={v.id} value={v.id}>v{v.version} ({v.channel})</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label>Rollout Strategy</label>
                                        <select
                                            className="form-select w-full"
                                            value={rolloutStrategy}
                                            onChange={e => setRolloutStrategy(e.target.value)}
                                        >
                                            <option value="all">All At Once</option>
                                            <option value="staged">Staged (Batch by Batch)</option>
                                            <option value="canary">Canary (1 server first)</option>
                                        </select>
                                    </div>
                                    {rolloutStrategy === 'staged' && (
                                        <>
                                            <div className="form-group">
                                                <label>Batch Size</label>
                                                <Input
                                                    type="number"
                                                    value={rolloutBatchSize}
                                                    onChange={e => setRolloutBatchSize(parseInt(e.target.value) || 5)}
                                                    min={1}
                                                />
                                            </div>
                                            <div className="form-group">
                                                <label>Delay (minutes)</label>
                                                <Input
                                                    type="number"
                                                    value={rolloutDelay}
                                                    onChange={e => setRolloutDelay(parseInt(e.target.value) || 10)}
                                                    min={1}
                                                />
                                            </div>
                                        </>
                                    )}
                                </div>
                                <div className="mt-6 flex justify-end">
                                    <Button onClick={triggerUpgrade} disabled={!selectedVersion}>
                                        <Play size={18} /> Start Rollout
                                    </Button>
                                </div>
                            </div>
                        </div>

                        <div className="card">
                            <div className="card-header">
                                <h2>Rollout History</h2>
                            </div>
                            {rollouts.length > 0 ? (
                                <DataTable
                                    columns={rolloutColumns}
                                    data={rollouts}
                                    keyField="id"
                                    storageKey="serverkit-table-fleet-rollouts"
                                    className="overflow-x-auto"
                                    footer={(
                                        <DataTableFooter
                                            shown={rollouts.length}
                                            total={rollouts.length}
                                            noun="rollout"
                                        />
                                    )}
                                />
                            ) : (
                                <div className="card-body py-12 text-center text-gray-500">
                                    <Zap size={48} className="mx-auto text-gray-300 mb-4" />
                                    <p>No rollouts have been started yet.</p>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* ==================== Command Queue ==================== */}
                {activeTab === 'queue' && (
                    <div className="card">
                        <div className="card-header flex justify-between items-center">
                            <h2>Queued Commands</h2>
                            <p className="text-sm text-gray-500">Commands waiting to be delivered when agents reconnect</p>
                        </div>
                        {queuedCommands.length > 0 ? (
                            <DataTable
                                columns={queueColumns}
                                data={queuedCommands}
                                keyField="id"
                                storageKey="serverkit-table-fleet-queue"
                                className="overflow-x-auto"
                                footer={(
                                    <DataTableFooter
                                        shown={queuedCommands.length}
                                        total={queuedCommands.length}
                                        noun="command"
                                    />
                                )}
                            />
                        ) : (
                            <div className="card-body py-12 text-center text-gray-500">
                                <CheckCircle size={48} className="mx-auto text-gray-300 mb-4" />
                                <p>No queued commands. All agents are up to date.</p>
                            </div>
                        )}
                    </div>
                )}

                {/* ==================== Discovery ==================== */}
                {activeTab === 'discovery' && (
                    <div className="space-y-6">
                        <div className="flex justify-between items-center">
                            <h2>Network Discovery</h2>
                            <Button onClick={startDiscovery} disabled={isScanning}>
                                {isScanning ? <RefreshCw size={18} className="animate-spin" /> : <Search size={18} />}
                                {isScanning ? 'Scanning...' : 'Start Scan'}
                            </Button>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {discoveredAgents.map(agent => (
                                <div key={agent.agent_id} className="card p-4 flex flex-col justify-between">
                                    <div>
                                        <div className="flex justify-between items-start mb-2">
                                            <div className="fleet-ico">
                                                <Server size={20} />
                                            </div>
                                            {agent.is_registered ? (
                                                <Pill kind="green">Registered</Pill>
                                            ) : (
                                                <Pill kind="amber">New</Pill>
                                            )}
                                        </div>
                                        <h3 className="font-bold">{agent.hostname}</h3>
                                        <p className="text-sm text-gray-500">{agent.ip_address}</p>
                                        <div className="mt-4 space-y-2 text-sm">
                                            <div className="flex justify-between">
                                                <span className="text-gray-500">OS:</span>
                                                <span>{agent.os} ({agent.arch})</span>
                                            </div>
                                            <div className="flex justify-between">
                                                <span className="text-gray-500">Agent Version:</span>
                                                <span>v{agent.agent_version}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="mt-4 pt-4 border-t">
                                        {agent.is_registered ? (
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="w-full"
                                                onClick={() => {
                                                    setActiveTab('dashboard');
                                                    loadDiagnostics(agent.server_id);
                                                }}
                                            >
                                                View Details
                                            </Button>
                                        ) : (
                                            <Button size="sm" className="w-full">Add to Fleet</Button>
                                        )}
                                    </div>
                                </div>
                            ))}
                            {discoveredAgents.length === 0 && !isScanning && (
                                <div className="col-span-full py-12 text-center card">
                                    <Search size={48} className="mx-auto text-gray-300 mb-4" />
                                    <p className="text-gray-500">No agents discovered yet. Start a scan to find agents on your local network.</p>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* ==================== Approvals ==================== */}
                {activeTab === 'approvals' && (
                    <div className="card">
                        <div className="card-header">
                            <h2>Pending Registrations</h2>
                        </div>
                        <DataTable
                            columns={approvalColumns}
                            data={pendingServers}
                            keyField="id"
                            storageKey="serverkit-table-fleet-approvals"
                            className="overflow-x-auto"
                            emptyState={(
                                <div className="text-center py-8 text-gray-500">
                                    No pending agent registrations.
                                </div>
                            )}
                            footer={(
                                <DataTableFooter
                                    shown={pendingServers.length}
                                    total={pendingServers.length}
                                    noun="registration"
                                />
                            )}
                        />
                    </div>
                )}

                {/* ==================== Diagnostics Modal ==================== */}
                {diagnostics && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setDiagnostics(null)}>
                        <div className="fleet-modal w-full max-w-2xl max-h-[80vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()}>
                            <div className="p-6 border-b flex justify-between items-center">
                                <h2 className="text-lg font-semibold">
                                    Agent Diagnostics - {diagnostics.server_name}
                                </h2>
                                <Button variant="ghost" size="sm" onClick={() => setDiagnostics(null)}>
                                    <XCircle size={18} />
                                </Button>
                            </div>
                            <div className="p-6 space-y-6">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="text-sm text-gray-500">Status</label>
                                        <p className="font-semibold flex items-center gap-2">
                                            {diagnostics.connection.is_connected ? (
                                                <><Wifi size={16} className="text-green-500" /> Connected</>
                                            ) : (
                                                <><WifiOff size={16} className="text-red-500" /> Disconnected</>
                                            )}
                                        </p>
                                    </div>
                                    <div>
                                        <label className="text-sm text-gray-500">Agent Version</label>
                                        <p className="font-semibold">v{diagnostics.agent_version || 'Unknown'}</p>
                                    </div>
                                    <div>
                                        <label className="text-sm text-gray-500">Current Latency</label>
                                        <p className="font-semibold">
                                            {diagnostics.connection.current_latency_ms != null
                                                ? `${diagnostics.connection.current_latency_ms.toFixed(1)} ms`
                                                : 'N/A'}
                                        </p>
                                    </div>
                                    <div>
                                        <label className="text-sm text-gray-500">Avg Latency</label>
                                        <p className="font-semibold">
                                            {diagnostics.connection.avg_latency_ms != null
                                                ? `${diagnostics.connection.avg_latency_ms.toFixed(1)} ms`
                                                : 'N/A'}
                                        </p>
                                    </div>
                                    <div>
                                        <label className="text-sm text-gray-500">IP Address</label>
                                        <p className="font-semibold">{diagnostics.connection.ip_address || 'N/A'}</p>
                                    </div>
                                    <div>
                                        <label className="text-sm text-gray-500">Connected Since</label>
                                        <p className="font-semibold">
                                            {diagnostics.connection.connected_since
                                                ? new Date(diagnostics.connection.connected_since).toLocaleString()
                                                : 'N/A'}
                                        </p>
                                    </div>
                                </div>

                                <div>
                                    <h3 className="font-semibold mb-3">Command Stats (24h)</h3>
                                    <div className="grid grid-cols-4 gap-3">
                                        <div className="fleet-statbox">
                                            <div className="text-lg font-bold">{diagnostics.commands_24h.total}</div>
                                            <div className="text-xs text-gray-500">Total</div>
                                        </div>
                                        <div className="fleet-statbox is-green">
                                            <div className="text-lg font-bold text-green-600">{diagnostics.commands_24h.success}</div>
                                            <div className="text-xs text-gray-500">Success</div>
                                        </div>
                                        <div className="fleet-statbox is-red">
                                            <div className="text-lg font-bold text-red-600">{diagnostics.commands_24h.failed}</div>
                                            <div className="text-xs text-gray-500">Failed</div>
                                        </div>
                                        <div className="fleet-statbox is-amber">
                                            <div className="text-lg font-bold text-yellow-600">{diagnostics.commands_24h.timeout}</div>
                                            <div className="text-xs text-gray-500">Timeout</div>
                                        </div>
                                    </div>
                                </div>

                                {diagnostics.queued_commands > 0 && (
                                    <div className="fleet-warnrow">
                                        <span className="flex items-center gap-2">
                                            <Clock size={16} />
                                            <span className="text-sm">{diagnostics.queued_commands} commands queued for delivery</span>
                                        </span>
                                    </div>
                                )}

                                <div>
                                    <h3 className="font-semibold mb-3">Recent Sessions</h3>
                                    <div className="space-y-2 max-h-48 overflow-y-auto">
                                        {diagnostics.recent_sessions.map(session => (
                                            <div key={session.id} className="fleet-statrow flex justify-between items-center text-sm p-2 rounded">
                                                <div className="flex items-center gap-2">
                                                    {session.is_active ? (
                                                        <Wifi size={14} className="text-green-500" />
                                                    ) : (
                                                        <WifiOff size={14} className="text-gray-400" />
                                                    )}
                                                    <span>{session.ip_address}</span>
                                                </div>
                                                <div className="text-gray-500">
                                                    {new Date(session.connected_at).toLocaleString()}
                                                    {session.disconnect_reason && (
                                                        <span className="ml-2 text-red-500">({session.disconnect_reason})</span>
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default AgentFleet;
