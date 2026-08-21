import { useState, useEffect } from 'react';
import useTabParam from '../hooks/useTabParam';
import api from '../services/api';
import EmptyState from '../components/EmptyState';
import { Button } from '@/components/ui/button';
import { MetricCard, KpiBand } from '@/components/ds';
import {
    Box, Layers, HardDrive, Network as NetworkIcon,
    Trash2, Activity, Package, Server as ServerIcon,
} from 'lucide-react';
import {
    ServerContext,
    VALID_TABS,
    LOCAL_DOCKER_TARGET,
    normalizeListResponse,
} from '../components/docker/dockerHelpers';
import ContainersTab, { RunContainerButton } from '../components/docker/ContainersTab';
import ComposeTab from '../components/docker/ComposeTab';
import ImagesTab, { PullImageButton } from '../components/docker/ImagesTab';
import NetworksTab, { CreateNetworkButton } from '../components/docker/NetworksTab';
import VolumesTab, { CreateVolumeButton } from '../components/docker/VolumesTab';
import PruneButton from '../components/docker/PruneButton';
import RequiresDocker from '../components/RequiresDocker';
import { useTranslation } from 'react-i18next';

const Docker = () => {
    const { t } = useTranslation();
    const [activeTab, setActiveTab] = useTabParam('/docker', VALID_TABS);
    const [dockerStatus, setDockerStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [selectedServer, setSelectedServer] = useState(LOCAL_DOCKER_TARGET);
    const [availableServers, setAvailableServers] = useState([LOCAL_DOCKER_TARGET]);
    const [stats, setStats] = useState({
        containers: { total: 0, running: 0, stopped: 0 },
        images: { total: 0, size: '0 B' },
        volumes: { total: 0 },
        networks: { total: 0 }
    });

    useEffect(() => {
        checkDockerStatus();
    }, [selectedServer]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        let cancelled = false;

        async function loadAvailableServers() {
            try {
                const data = await api.getAvailableServers();
                const servers = Array.isArray(data) && data.length > 0 ? data : [LOCAL_DOCKER_TARGET];
                if (cancelled) return;
                setAvailableServers(servers);
                setSelectedServer(prev => (
                    servers.some(server => server.id === prev.id)
                        ? prev
                        : (servers[0] || LOCAL_DOCKER_TARGET)
                ));
            } catch {
                if (cancelled) return;
                setAvailableServers([LOCAL_DOCKER_TARGET]);
                setSelectedServer(LOCAL_DOCKER_TARGET);
            }
        }

        loadAvailableServers();
        return () => { cancelled = true; };
    }, []);

    async function checkDockerStatus() {
        setLoading(true);
        try {
            if (selectedServer.id === 'local') {
                const status = await api.getDockerStatus();
                setDockerStatus(status);
                if (status.installed) {
                    loadStats();
                } else {
                    setLoading(false);
                }
            } else {
                // For remote servers, check if the agent is online
                const serverData = await api.getServer(selectedServer.id);
                if (serverData.status === 'online' || serverData.server?.status === 'online') {
                    setDockerStatus({ installed: true, running: true });
                    loadStats();
                } else {
                    setDockerStatus({ installed: false, error: 'Server agent is offline' });
                    setLoading(false);
                }
            }
        } catch (err) {
            setDockerStatus({ installed: false, error: err.message });
            setLoading(false);
        }
    }

    async function loadStats() {
        try {
            let containersData, imagesData, volumesData, networksData;

            if (selectedServer.id === 'local') {
                [containersData, imagesData, volumesData, networksData] = await Promise.all([
                    api.getContainers(true),
                    api.getImages(),
                    api.getVolumes(),
                    api.getNetworks()
                ]);
            } else {
                [containersData, imagesData, volumesData, networksData] = await Promise.all([
                    api.getRemoteContainers(selectedServer.id, true),
                    api.getRemoteImages(selectedServer.id),
                    api.getRemoteVolumes(selectedServer.id),
                    api.getRemoteNetworks(selectedServer.id)
                ]);

            }

            const containers = selectedServer.id === 'local'
                ? containersData.containers || []
                : normalizeListResponse(containersData, 'containers');
            const images = selectedServer.id === 'local'
                ? imagesData.images || []
                : normalizeListResponse(imagesData, 'images');
            const volumes = selectedServer.id === 'local'
                ? volumesData.volumes || []
                : normalizeListResponse(volumesData, 'volumes');
            const networks = selectedServer.id === 'local'
                ? networksData.networks || []
                : normalizeListResponse(networksData, 'networks');

            const running = containers.filter(c => c.state === 'running').length;

            setStats({
                containers: {
                    total: containers.length,
                    running,
                    stopped: containers.length - running
                },
                images: {
                    total: images.length,
                    size: formatTotalImageSize(images)
                },
                volumes: { total: volumes.length },
                networks: { total: networks.length }
            });
        } catch (err) {
            console.error('Failed to load stats:', err);
        } finally {
            setLoading(false);
        }
    }

    function formatTotalImageSize(images) {
        const sizes = images.map(img => {
            const size = img.size || '0 B';
            const match = size.match(/^([\d.]+)\s*(B|KB|MB|GB|TB)?$/i);
            if (!match) return 0;
            const [, num, unit = 'B'] = match;
            const multipliers = { B: 1, KB: 1024, MB: 1024**2, GB: 1024**3, TB: 1024**4 };
            return parseFloat(num) * (multipliers[unit.toUpperCase()] || 1);
        });
        const total = sizes.reduce((a, b) => a + b, 0);
        if (total >= 1024**3) return `${(total / 1024**3).toFixed(1)} GB`;
        if (total >= 1024**2) return `${(total / 1024**2).toFixed(1)} MB`;
        if (total >= 1024) return `${(total / 1024).toFixed(1)} KB`;
        return `${total} B`;
    }

    if (loading) {
        return <EmptyState loading loadingVariant="table" title={t('app.docker.checkingDockerStatus', 'Checking Docker status...')} />;
    }

    // No page header here: the unavailable panel below is its own heading, and
    // the workspace this falls back from carries no top bar either.
    if (!dockerStatus?.installed) {
        return (
            <div className="page-container docker-page">
                <div className="docker-unavailable">
                    <div className="docker-unavailable-icon">
                        <svg viewBox="0 0 24 24" width="64" height="64" stroke="currentColor" fill="none" strokeWidth="1">
                            <rect x="2" y="7" width="5" height="5" rx="1"/>
                            <rect x="9" y="7" width="5" height="5" rx="1"/>
                            <rect x="16" y="7" width="5" height="5" rx="1"/>
                            <rect x="2" y="14" width="5" height="5" rx="1"/>
                            <rect x="9" y="14" width="5" height="5" rx="1"/>
                            <path d="M21 12c0 4-3 7-8 7s-8-3-8-7" strokeDasharray="2 2"/>
                        </svg>
                    </div>
                    <h2>{t('app.docker.dockerNotAvailable', 'Docker Not Available')}</h2>
                    <p className="docker-unavailable-message">
                        {t('app.docker.dockerIsNotInstalledOrNot', 'Docker is not installed or not running on this system.')}
                    </p>
                    <div className="docker-unavailable-details">
                        <code>{dockerStatus?.error || 'Unable to connect to Docker daemon'}</code>
                    </div>
                    <div className="docker-unavailable-help">
                        <h4>{t('app.docker.toUseDockerManagement', 'To use Docker management:')}</h4>
                        <ul>
                            <li>{t('app.docker.ensureDockerDesktopIsInstalledAnd', 'Ensure Docker Desktop is installed and running')}</li>
                            <li>{t('app.docker.onLinuxMakeSureTheDocker', 'On Linux, make sure the Docker daemon is started')}</li>
                            <li>{t('app.docker.verifyTheUserHasPermissionsTo', 'Verify the user has permissions to access Docker')}</li>
                        </ul>
                    </div>
                    <Button onClick={checkDockerStatus}>
                        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                            <path d="M23 4v6h-6M1 20v-6h6"/>
                            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                        </svg>
                        {t('app.docker.retryConnection', 'Retry Connection')}
                    </Button>
                </div>
            </div>
        );
    }

    const tabs = [
        { id: 'containers', labelKey: 'app.docker.containers', label: 'Containers', icon: Box, count: stats.containers.total },
        { id: 'compose', labelKey: 'app.docker.compose', label: 'Compose', icon: Package, count: null },
        { id: 'images', labelKey: 'app.docker.images', label: 'Images', icon: Layers, count: stats.images.total },
        { id: 'volumes', labelKey: 'app.docker.volumes', label: 'Volumes', icon: HardDrive, count: stats.volumes.total },
        { id: 'networks', labelKey: 'app.docker.networks', label: 'Networks', icon: NetworkIcon, count: stats.networks.total }
    ];

    const activeTabMeta = tabs.find(tab => tab.id === activeTab) || tabs[0];
    const hasMultipleTargets = availableServers.length > 1;

    const serverContextValue = {
        serverId: selectedServer.id,
        serverName: selectedServer.name,
        isRemote: selectedServer.id !== 'local'
    };

    return (
        <RequiresDocker what="Container management">
        <ServerContext.Provider value={serverContextValue}>
        <div className="page-container page-container--full-bleed docker-page-new dx-page">
            <div className="dx-workspace">
                <aside className="dx-docker-sidebar">
                    {hasMultipleTargets && (
                        <section className="dx-sidebar-section">
                            <div className="dx-sidebar-section-header">
                                <ServerIcon size={14} />
                                <span>{t('app.docker.targets', 'Targets')}</span>
                            </div>
                            <div className="dx-resource-nav">
                                {availableServers.map(server => (
                                    <button type="button"
                                        key={server.id}
                                        className={`dx-resource-nav-item ${selectedServer.id === server.id ? 'active' : ''}`}
                                        onClick={() => setSelectedServer(server)}
                                    >
                                        <ServerIcon size={15} />
                                        <span>{server.name || server.hostname || server.id}</span>
                                        <strong>{server.status || 'online'}</strong>
                                    </button>
                                ))}
                            </div>
                        </section>
                    )}

                    <section className="dx-sidebar-section">
                        <div className="dx-sidebar-section-header">
                            <Box size={14} />
                            <span>{t('app.docker.resources', 'Resources')}</span>
                        </div>
                        <div className="dx-resource-nav">
                            {tabs.map(tab => {
                                const Icon = tab.icon;
                                return (
                                    <button type="button"
                                        key={tab.id}
                                        className={`dx-resource-nav-item ${activeTab === tab.id ? 'active' : ''}`}
                                        onClick={() => setActiveTab(tab.id)}
                                    >
                                        <Icon size={15} />
                                        <span>{tab.label}</span>
                                        {tab.count !== null && <strong>{tab.count}</strong>}
                                    </button>
                                );
                            })}
                        </div>
                    </section>

                    <section className="dx-sidebar-section">
                        <div className="dx-sidebar-section-header">
                            <Activity size={14} />
                            <span>{t('app.docker.inventory', 'Inventory')}</span>
                        </div>
                        <div className="dx-inventory-list">
                            <div className="dx-inventory-item">
                                <span>{t('app.docker.running', 'Running')}</span>
                                <strong>{stats.containers.running}</strong>
                            </div>
                            <div className="dx-inventory-item">
                                <span>{t('app.docker.stopped', 'Stopped')}</span>
                                <strong>{stats.containers.stopped}</strong>
                            </div>
                            <div className="dx-inventory-item">
                                <span>{t('app.docker.images2', 'Images')}</span>
                                <strong>{stats.images.size}</strong>
                            </div>
                            <div className="dx-inventory-item">
                                <span>{t('app.docker.volumes2', 'Volumes')}</span>
                                <strong>{stats.volumes.total}</strong>
                            </div>
                        </div>
                    </section>

                    <section className="dx-sidebar-section">
                        <div className="dx-sidebar-section-header">
                            <Trash2 size={14} />
                            <span>{t('app.docker.maintenance', 'Maintenance')}</span>
                        </div>
                        <div className="dx-sidebar-section-content">
                            <PruneButton onPruned={loadStats} />
                        </div>
                    </section>
                </aside>

                <main className="dx-main">
                    <KpiBand>
                        <MetricCard tone="accent" icon={<Box size={16} />} value={stats.containers.total} label={t('app.docker.containers2', 'Containers')}>
                            <div className="sk-kpi__sub"><span>{stats.containers.running} running</span></div>
                        </MetricCard>
                        <MetricCard tone="cyan" icon={<Layers size={16} />} value={stats.images.total} label={t('app.docker.images3', 'Images')}>
                            <div className="sk-kpi__sub"><span>{stats.images.size}</span></div>
                        </MetricCard>
                        <MetricCard tone="violet" icon={<HardDrive size={16} />} value={stats.volumes.total} label={t('app.docker.volumes3', 'Volumes')} />
                        <MetricCard tone="green" icon={<NetworkIcon size={16} />} value={stats.networks.total} label={t('app.docker.networks2', 'Networks')} />
                    </KpiBand>
                    <div className="dx-workbar">
                        <div className="dx-workbar-title">
                            <span>{t('app.docker.docker', 'Docker')}</span>
                            <strong>{activeTabMeta.label}</strong>
                            {hasMultipleTargets && <em>{selectedServer.name || selectedServer.id}</em>}
                        </div>
                        <div className="dx-workbar-actions">
                            {activeTab === 'containers' && <RunContainerButton />}
                            {activeTab === 'images' && <PullImageButton />}
                            {activeTab === 'networks' && <CreateNetworkButton />}
                            {activeTab === 'volumes' && <CreateVolumeButton />}
                        </div>
                    </div>

                    <div className="dx-panel">
                        {activeTab === 'containers' && <ContainersTab onStatsChange={loadStats} />}
                        {activeTab === 'compose' && <ComposeTab onStatsChange={loadStats} />}
                        {activeTab === 'images' && <ImagesTab onStatsChange={loadStats} />}
                        {activeTab === 'networks' && <NetworksTab onStatsChange={loadStats} />}
                        {activeTab === 'volumes' && <VolumesTab onStatsChange={loadStats} />}
                    </div>
                </main>
            </div>
        </div>
        </ServerContext.Provider>
        </RequiresDocker>
    );
};

export default Docker;
