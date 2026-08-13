import { useState, useEffect } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { Button } from '@/components/ui/button';
import { DataTable, DataTableFooter, Pill } from '../ds';
import EmptyState from '../EmptyState';
import { Boxes, Container } from 'lucide-react';
import {
    OfflineIcon,
    RefreshIcon,
    StopIcon,
    PlayIcon,
    TrashIcon,
} from './serverDetailShared';

// The /servers/<id>/docker/* endpoints return raw arrays from Flask
// (route extracts result.get('data') before jsonify). The agent envelope's
// {success, data} shape is gone by the time it reaches the client, so unwrap
// both forms defensively.
const unwrapList = (response) => {
    if (Array.isArray(response)) return response;
    if (response?.success && Array.isArray(response.data)) return response.data;
    return [];
};

// Docker exposes container ports as an array of {ip, private_port,
// public_port, type} objects. Render a compact "host:container/proto"
// string per binding, or fall back to "container/proto" when the port
// isn't mapped to the host. Older agents may already send a string.
const formatPorts = (ports) => {
    if (!ports) return '-';
    if (typeof ports === 'string') return ports || '-';
    if (!Array.isArray(ports) || ports.length === 0) return '-';
    const parts = ports.map((p) => {
        if (!p || typeof p !== 'object') return String(p);
        const proto = p.type || 'tcp';
        if (p.public_port) {
            const host = p.ip && p.ip !== '0.0.0.0' && p.ip !== '::' ? `${p.ip}:` : '';
            return `${host}${p.public_port}->${p.private_port}/${proto}`;
        }
        return `${p.private_port}/${proto}`;
    });
    return parts.join(', ');
};

// docker prints image sizes as strings ("25.5MB", "1.2GB") — parse to bytes
// so the Size column sorts numerically instead of lexicographically.
const SIZE_UNITS = { b: 1, kb: 1e3, mb: 1e6, gb: 1e9, tb: 1e12 };
const parseDockerSize = (size) => {
    const match = /^([\d.]+)\s*(b|kb|mb|gb|tb)$/i.exec(size || '');
    if (!match) return null;
    return parseFloat(match[1]) * (SIZE_UNITS[match[2].toLowerCase()] || 1);
};

// Images table columns. Cell markup and classNames are identical to the
// hand-rolled table they replace so the .data-table SCSS keeps applying.
const IMAGE_COLUMNS = [
    {
        key: 'repository',
        header: 'Repository',
        sortable: true,
        hideable: false,
        sortValue: (image) => image.repository || '<none>',
        render: (image) => image.repository || '<none>',
    },
    {
        key: 'tag',
        header: 'Tag',
        sortable: true,
        sortValue: (image) => image.tag || '<none>',
        render: (image) => image.tag || '<none>',
    },
    {
        key: 'id',
        header: 'Image ID',
        cellClassName: 'mono',
        render: (image) => image.id?.substring(0, 12),
    },
    {
        key: 'size',
        header: 'Size',
        sortable: true,
        sortValue: (image) => parseDockerSize(image.size),
        render: (image) => image.size,
    },
    {
        key: 'created',
        header: 'Created',
        sortable: true,
        sortValue: (image) => image.created || null,
        render: (image) => image.created,
    },
];

const ServerDockerTab = ({ serverId, serverStatus, server }) => {
    const [containers, setContainers] = useState([]);
    const [images, setImages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);
    const [subTab, setSubTab] = useState('containers');
    const toast = useToast();
    const { confirm: confirmDocker } = useConfirm();

    useEffect(() => {
        if (serverStatus === 'online') {
            loadDockerData();
        } else {
            setLoading(false);
        }
    }, [serverId, serverStatus]);

    async function loadDockerData() {
        setLoading(true);
        setLoadError(null);
        try {
            const [containersRes, imagesRes] = await Promise.all([
                api.getRemoteContainers(serverId, true),
                api.getRemoteImages(serverId)
            ]);

            setContainers(unwrapList(containersRes));
            setImages(unwrapList(imagesRes));
        } catch (err) {
            console.error('Failed to load Docker data:', err);
            setLoadError(err.message || 'Failed to load Docker data');
        } finally {
            setLoading(false);
        }
    }

    // If the agent reports docker capability false (Docker daemon not
    // reachable from the agent process — common on Windows when the
    // service hasn't been started, or on hosts where the agent user
    // isn't in the docker group), explain that instead of pretending
    // there are no containers.
    const dockerCapability = server?.capabilities?.docker;
    if (serverStatus === 'online' && server && dockerCapability === false) {
        return (
            <div className="docker-empty-state">
                <EmptyState
                    icon={Container}
                    title="Docker not reachable from this agent"
                    description="The agent connected but could not talk to a Docker daemon. Make sure Docker is running on the host (and the agent user is in the docker group on Linux), then click Refresh on the Overview tab to re-probe capabilities."
                />
                <ul className="docker-empty-state__causes">
                    <li>Docker Desktop / dockerd is not running on the host</li>
                    <li>The agent user isn&apos;t in the <code>docker</code> group (Linux)</li>
                    <li>The npipe socket <code>{'//./pipe/docker_engine'}</code> isn&apos;t accessible (Windows)</li>
                </ul>
            </div>
        );
    }

    async function handleContainerAction(containerId, action) {
        try {
            let result;
            if (action === 'start') {
                result = await api.startRemoteContainer(serverId, containerId);
                toast.success('Container started');
            } else if (action === 'stop') {
                result = await api.stopRemoteContainer(serverId, containerId);
                toast.success('Container stopped');
            } else if (action === 'restart') {
                result = await api.restartRemoteContainer(serverId, containerId);
                toast.success('Container restarted');
            } else if (action === 'remove') {
                const removeConfirmed = await confirmDocker({ title: 'Remove Container', message: 'Remove this container?' });
                if (!removeConfirmed) return;
                result = await api.removeRemoteContainer(serverId, containerId, true);
                toast.success('Container removed');
            }
            loadDockerData();
        } catch (err) {
            toast.error(err.message || `Failed to ${action} container`);
        }
    }

    if (serverStatus !== 'online') {
        return (
            <div className="offline-notice">
                <OfflineIcon />
                <h4>Server Offline</h4>
                <p>Docker management requires the server to be online.</p>
            </div>
        );
    }

    if (loading) {
        return <EmptyState loading title="Loading Docker data" />;
    }

    // Containers table columns. Cell markup and classNames are identical to
    // the hand-rolled table they replace so the .data-table SCSS (and the
    // .server-detail-page dense-table overrides) keeps applying.
    const containerColumns = [
        {
            key: 'name',
            header: 'Name',
            sortable: true,
            hideable: false,
            sortValue: (container) => container.name || '',
            render: (container) => (
                <>
                    <span className="container-name">{container.name}</span>
                    <span className="container-id">{container.id?.substring(0, 12)}</span>
                </>
            ),
        },
        {
            key: 'image',
            header: 'Image',
            sortable: true,
            sortValue: (container) => container.image || '',
            render: (container) => container.image,
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (container) => container.state || '',
            render: (container) => {
                const isRunning = container.state === 'running';
                return (
                    <Pill kind={isRunning ? 'green' : container.state === 'paused' || container.state === 'restarting' ? 'amber' : 'gray'}>
                        {container.state}
                    </Pill>
                );
            },
        },
        {
            key: 'ports',
            header: 'Ports',
            sortable: true,
            sortValue: (container) => {
                const text = formatPorts(container.ports);
                return text === '-' ? null : text;
            },
            render: (container) => formatPorts(container.ports),
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            cellClassName: 'actions-cell',
            render: (container) => {
                const isRunning = container.state === 'running';
                return isRunning ? (
                    <>
                        <button type="button"
                            className="btn-icon"
                            onClick={() => handleContainerAction(container.id, 'restart')}
                            title="Restart"
                        >
                            <RefreshIcon />
                        </button>
                        <button type="button"
                            className="btn-icon danger"
                            onClick={() => handleContainerAction(container.id, 'stop')}
                            title="Stop"
                        >
                            <StopIcon />
                        </button>
                    </>
                ) : (
                    <>
                        <button type="button"
                            className="btn-icon success"
                            onClick={() => handleContainerAction(container.id, 'start')}
                            title="Start"
                        >
                            <PlayIcon />
                        </button>
                        <button type="button"
                            className="btn-icon danger"
                            onClick={() => handleContainerAction(container.id, 'remove')}
                            title="Remove"
                        >
                            <TrashIcon />
                        </button>
                    </>
                );
            },
        },
    ];

    return (
        <div className="docker-tab">
            {loadError && (
                <div className="docker-tab__error">
                    <strong>Couldn&apos;t load Docker data:</strong> {loadError}
                    <Button size="sm" variant="outline" onClick={loadDockerData}>Retry</Button>
                </div>
            )}
            <div className="docker-sub-tabs">
                <button type="button"
                    className={`sub-tab ${subTab === 'containers' ? 'active' : ''}`}
                    onClick={() => setSubTab('containers')}
                >
                    Containers ({containers.length})
                </button>
                <button type="button"
                    className={`sub-tab ${subTab === 'images' ? 'active' : ''}`}
                    onClick={() => setSubTab('images')}
                >
                    Images ({images.length})
                </button>
            </div>

            {subTab === 'containers' && (
                <div className="containers-list">
                    {containers.length === 0 ? (
                        <EmptyState icon={Container} title="No containers" description="No containers are running on this server." />
                    ) : (
                        <DataTable
                            columns={containerColumns}
                            data={containers}
                            keyField="id"
                            storageKey="serverkit-table-sd-docker-containers"
                            tableClassName="data-table"
                            footer={(
                                <DataTableFooter
                                    shown={containers.length}
                                    total={containers.length}
                                    noun="container"
                                />
                            )}
                        />
                    )}
                </div>
            )}

            {subTab === 'images' && (
                <div className="images-list">
                    {images.length === 0 ? (
                        <EmptyState icon={Boxes} title="No images" description="No Docker images are present on this server." />
                    ) : (
                        <DataTable
                            columns={IMAGE_COLUMNS}
                            data={images}
                            keyField="id"
                            storageKey="serverkit-table-sd-docker-images"
                            tableClassName="data-table"
                            footer={(
                                <DataTableFooter
                                    shown={images.length}
                                    total={images.length}
                                    noun="image"
                                />
                            )}
                        />
                    )}
                </div>
            )}
        </div>
    );
};

export default ServerDockerTab;
