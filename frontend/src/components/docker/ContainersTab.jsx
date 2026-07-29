import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import LogToolbar from '../log-viewer/LogToolbar';
import LogContent from '../log-viewer/LogContent';
import EmptyState from '../EmptyState';
import Modal from '@/components/Modal';
import { Drawer } from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
    Box, Search, X, RefreshCw, Trash2, Play, Square, RotateCw,
    Terminal as TerminalLucide, FileText, Activity, Clock3, Copy,
    Database, Gauge, Package, Server as ServerIcon, ArrowUpDown, Lock,
} from 'lucide-react';
import {
    useServer,
    unwrapRemoteData,
    formatPorts,
    normalizeListResponse,
    shortId,
    getContainerId,
    getContainerName,
    getContainerImage,
    getContainerStatus,
    isContainerRunning,
    isProtectedContainer,
    getContainerStatusLabel,
    containerHue,
    getContainerProjectName,
} from './dockerHelpers';
import { ContainerResourceBars } from './dockerShared';

// Action Buttons
export const RunContainerButton = () => {
    const [showModal, setShowModal] = useState(false);
    const { isRemote } = useServer();
    return (
        <>
            <Button
                onClick={() => setShowModal(true)}
                disabled={isRemote}
                title={isRemote ? 'Running new containers is only available on the local Docker target right now' : 'Run container'}
            >
                <span>+</span> Run Container
            </Button>
            {showModal && <RunContainerModal onClose={() => setShowModal(false)} onCreated={() => window.location.reload()} />}
        </>
    );
};

// Containers Tab
const ContainersTab = ({ onStatsChange }) => {
    const toast = useToast();
    const { serverId, isRemote } = useServer();
    const { confirm: confirmContainer } = useConfirm();
    const [containers, setContainers] = useState([]);
    const [containerStats, setContainerStats] = useState({});
    const [loading, setLoading] = useState(true);
    const [showAll, setShowAll] = useState(true);
    const [selectedContainer, setSelectedContainer] = useState(null);
    const [logsContainer, setLogsContainer] = useState(null);
    const [execContainer, setExecContainer] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState('all');
    const [sortKey, setSortKey] = useState('status');
    const [sortDirection, setSortDirection] = useState('asc');
    const statsRequestSeq = useRef(0);

    useEffect(() => {
        loadContainers();
    }, [showAll, serverId]); // eslint-disable-line react-hooks/exhaustive-deps

    const fetchContainerStats = useCallback(async (container) => {
        const containerId = getContainerId(container);
        if (!containerId) return null;

        if (isRemote) {
            const result = await api.getRemoteContainerStats(serverId, containerId);
            const payload = unwrapRemoteData(result);
            return payload?.stats || payload;
        }

        const statsData = await api.getContainerStats(containerId);
        return statsData.stats;
    }, [isRemote, serverId]);

    const refreshContainerStats = useCallback(async (containerList, requestSeq = statsRequestSeq.current) => {
        const runningContainers = containerList.filter(isContainerRunning);
        if (runningContainers.length === 0) return;

        if (!isRemote) {
            const containerIds = runningContainers.map(getContainerId).filter(Boolean);
            if (containerIds.length === 0) return;

            const resolveStats = (statsMap, container) => {
                const containerId = getContainerId(container);
                const containerName = getContainerName(container);
                return statsMap[containerId] ||
                    statsMap[containerName] ||
                    statsMap[`/${containerName}`] ||
                    null;
            };

            try {
                const statsData = await api.getContainersStats(containerIds);
                if (requestSeq !== statsRequestSeq.current) return;
                const statsMap = statsData?.stats || {};
                setContainerStats(prev => {
                    const next = { ...prev };
                    runningContainers.forEach(container => {
                        next[getContainerId(container)] = resolveStats(statsMap, container);
                    });
                    return next;
                });
            } catch {
                if (requestSeq !== statsRequestSeq.current) return;
                setContainerStats(prev => {
                    const next = { ...prev };
                    runningContainers.forEach(container => {
                        next[getContainerId(container)] = null;
                    });
                    return next;
                });
            }
            return;
        }

        await Promise.all(runningContainers.map(async (container) => {
            const containerId = getContainerId(container);
            try {
                const stats = await fetchContainerStats(container);
                if (requestSeq !== statsRequestSeq.current || !stats) return;
                setContainerStats(prev => ({ ...prev, [containerId]: stats }));
            } catch {
                if (requestSeq !== statsRequestSeq.current) return;
                setContainerStats(prev => ({ ...prev, [containerId]: null }));
            }
        }));
    }, [fetchContainerStats, isRemote]);

    useEffect(() => {
        if (loading || containers.length === 0) return undefined;

        const timer = window.setInterval(() => {
            refreshContainerStats(containers, statsRequestSeq.current);
        }, 10000);

        return () => window.clearInterval(timer);
    }, [containers, loading, refreshContainerStats]);

    async function loadContainers() {
        setLoading(true);
        try {
            let data;
            if (isRemote) {
                const result = await api.getRemoteContainers(serverId, showAll);
                data = { containers: normalizeListResponse(result, 'containers') };
            } else {
                data = await api.getContainers(showAll);
            }
            const containerList = data.containers || [];
            const requestSeq = ++statsRequestSeq.current;
            setContainers(containerList);
            setContainerStats({});
            setSelectedContainer(prev => {
                if (!containerList.length || !prev) return null;
                return containerList.find(c => getContainerId(c) === getContainerId(prev)) || null;
            });
            setLoading(false);
            refreshContainerStats(containerList, requestSeq);
        } catch (err) {
            console.error('Failed to load containers:', err);
            setLoading(false);
        }
    }

    async function handleAction(containerId, action) {
        try {
            if (action === 'start') {
                if (isRemote) {
                    await api.startRemoteContainer(serverId, containerId);
                } else {
                    await api.startContainer(containerId);
                }
                toast.success('Container started');
            } else if (action === 'stop') {
                if (isRemote) {
                    await api.stopRemoteContainer(serverId, containerId);
                } else {
                    await api.stopContainer(containerId);
                }
                toast.success('Container stopped');
            } else if (action === 'restart') {
                if (isRemote) {
                    await api.restartRemoteContainer(serverId, containerId);
                } else {
                    await api.restartContainer(containerId);
                }
                toast.success('Container restarted');
            } else if (action === 'remove') {
                const removeConfirmed = await confirmContainer({ title: 'Remove Container', message: 'Remove this container?' });
                if (!removeConfirmed) return;
                if (isRemote) {
                    await api.removeRemoteContainer(serverId, containerId, true);
                } else {
                    await api.removeContainer(containerId, true);
                }
                toast.success('Container removed');
            }
            loadContainers();
            onStatsChange?.();
        } catch (err) {
            console.error(`Failed to ${action} container:`, err);
            toast.error(err.message || `Failed to ${action} container`);
        }
    }

    function parseStats(stats) {
        if (!stats) return { cpu: 0, memory: 0, available: false };
        const source = stats.stats || stats;
        const parsePercent = (value) => {
            if (typeof value === 'number') return value;
            if (value === null || value === undefined) return 0;
            return parseFloat(String(value).replace('%', '')) || 0;
        };

        const cpu = parsePercent(source.CPUPerc ?? source.cpu_percent ?? source.cpu?.percent);
        const memory = parsePercent(source.MemPerc ?? source.memory_percent ?? source.memory?.percent);

        return { cpu, memory, available: true };
    }

    const counts = useMemo(() => {
        const c = { all: containers.length, running: 0, stopped: 0 };
        containers.forEach(x => { if (isContainerRunning(x)) c.running++; else c.stopped++; });
        return c;
    }, [containers]);

    const filteredContainers = useMemo(() => {
        const search = searchTerm.toLowerCase();
        const filtered = containers.filter(c => {
            if (statusFilter === 'running' && !isContainerRunning(c)) return false;
            if (statusFilter === 'stopped' && isContainerRunning(c)) return false;
            if (!search) return true;
            return getContainerName(c).toLowerCase().includes(search) ||
                   getContainerId(c).toLowerCase().includes(search) ||
                   getContainerImage(c).toLowerCase().includes(search);
        });

        const direction = sortDirection === 'asc' ? 1 : -1;
        const statusRank = (container) => isContainerRunning(container) ? 0 : 1;
        const createdTime = (container) => {
            const raw = container.created || container.CreatedAt || '';
            const parsed = Date.parse(raw);
            return Number.isNaN(parsed) ? 0 : parsed;
        };

        return [...filtered].sort((a, b) => {
            const statsA = parseStats(containerStats[getContainerId(a)]);
            const statsB = parseStats(containerStats[getContainerId(b)]);
            let result = 0;

            if (sortKey === 'status') {
                result = statusRank(a) - statusRank(b) ||
                    getContainerStatus(a).localeCompare(getContainerStatus(b));
            } else if (sortKey === 'name') {
                result = getContainerName(a).localeCompare(getContainerName(b));
            } else if (sortKey === 'image') {
                result = getContainerImage(a).localeCompare(getContainerImage(b));
            } else if (sortKey === 'cpu') {
                result = statsA.cpu - statsB.cpu;
            } else if (sortKey === 'memory') {
                result = statsA.memory - statsB.memory;
            } else if (sortKey === 'created') {
                result = createdTime(a) - createdTime(b);
            }

            return result * direction;
        });
    }, [containers, statusFilter, searchTerm, sortKey, sortDirection, containerStats]);

    const selectedStats = selectedContainer
        ? parseStats(containerStats[getContainerId(selectedContainer)])
        : { cpu: 0, memory: 0, available: false };

    if (loading) {
        return (
            <div className="dx-tab-pane">
                <div className="docker-loading">Loading containers...</div>
            </div>
        );
    }

    return (
        <div className="dx-tab-pane dx-containers-pane">
            <div className="dx-tab-toolbar">
                <div className="dx-filter-chips">
                    {[
                        { id: 'all', label: 'All', count: counts.all },
                        { id: 'running', label: 'Running', count: counts.running },
                        { id: 'stopped', label: 'Stopped', count: counts.stopped },
                    ].map(c => (
                        <button type="button"
                            key={c.id}
                            className={`filter-chip ${statusFilter === c.id ? 'active' : ''}`}
                            onClick={() => setStatusFilter(c.id)}
                            disabled={c.id !== 'all' && c.count === 0}
                        >
                            <span>{c.label}</span>
                            <span className="filter-chip-count">{c.count}</span>
                        </button>
                    ))}
                </div>
                <div className="dx-tab-toolbar-right">
                    <div className="dx-sort-control">
                        <span>Sort</span>
                        <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
                            <option value="status">Status</option>
                            <option value="name">Name</option>
                            <option value="image">Image</option>
                            <option value="cpu">CPU</option>
                            <option value="memory">RAM</option>
                            <option value="created">Created</option>
                        </select>
                        <button type="button"
                            className="lv-icon-btn"
                            onClick={() => setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc')}
                            title={`Sort ${sortDirection === 'asc' ? 'ascending' : 'descending'}`}
                        >
                            <ArrowUpDown size={13} />
                        </button>
                    </div>
                    <label className="dx-toggle">
                        <input
                            type="checkbox"
                            checked={showAll}
                            onChange={(e) => setShowAll(e.target.checked)}
                        />
                        <span>Include stopped</span>
                    </label>
                    <div className="dx-search-field">
                        <Search size={13} className="lv-search-field-icon" />
                        <input
                            type="text"
                            placeholder="Filter name, image, or ID..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                        {searchTerm && (
                            <Button size="icon" variant="ghost" className="lv-search-field-clear" onClick={() => setSearchTerm('')} title="Clear search" aria-label="Clear search">
                                <X size={11} />
                            </Button>
                        )}
                    </div>
                    <Button
                        size="icon"
                        variant="ghost"
                        className="lv-icon-btn"
                        onClick={loadContainers}
                        title="Refresh"
                        aria-label="Refresh containers"
                    >
                        <RefreshCw size={13} className={loading ? 'spinning' : ''} />
                    </Button>
                </div>
            </div>

            {filteredContainers.length === 0 ? (
                <EmptyState
                    icon={Box}
                    title={containers.length === 0 ? 'No containers' : 'No matching containers'}
                    description={containers.length === 0
                        ? 'Run your first container to see it here.'
                        : 'No containers match the current filters.'}
                />
            ) : (
                <div className="dx-manager-layout">
                    <section className="dx-resource-list">
                        <div className="dx-table-wrap">
                            <table className="dx-manager-table">
                                <thead>
                                    <tr>
                                        <th>Name</th>
                                        <th>Image</th>
                                        <th>Status</th>
                                        <th>Ports</th>
                                        <th>Resources</th>
                                        <th>Created</th>
                                        <th className="text-right">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredContainers.map(container => {
                                        const containerId = getContainerId(container);
                                        const stats = parseStats(containerStats[containerId]);
                                        const isRunning = isContainerRunning(container);
                                        const isProtected = isProtectedContainer(container);
                                        const ports = formatPorts(container.ports);
                                        const isSelected = getContainerId(selectedContainer) === containerId;
                                        return (
                                            <tr
                                                key={containerId}
                                                className={`${isRunning ? 'is-running' : 'is-stopped'} ${isSelected ? 'is-selected' : ''}`}
                                                onClick={() => setSelectedContainer(container)}
                                            >
                                                <td>
                                                    <div className="dx-name-stack">
                                                        <span className="dx-name-line">
                                                            {/* hue-hashed per-container identity dot (demo .dot-ico);
                                                                dims when stopped — status itself lives in the Status pill */}
                                                            <span
                                                                className={`dx-status-dot ${isRunning ? 'running' : 'stopped'}`}
                                                                style={{
                                                                    background: `hsl(${containerHue(getContainerName(container))} 60% 60%)`,
                                                                    boxShadow: isRunning
                                                                        ? `0 0 6px hsl(${containerHue(getContainerName(container))} 60% 60% / 0.55)`
                                                                        : 'none',
                                                                    opacity: isRunning ? 1 : 0.4,
                                                                }}
                                                            />
                                                            <span title={getContainerName(container)}>{getContainerName(container)}</span>
                                                        </span>
                                                        <span className="dx-muted-line mono">{shortId(containerId)}</span>
                                                    </div>
                                                </td>
                                                <td>
                                                    <span className="dx-code-pill" title={getContainerImage(container)}>
                                                        {getContainerImage(container)}
                                                    </span>
                                                </td>
                                                <td>
                                                    <span className={`dx-status-pill ${isRunning ? 'running' : 'stopped'}`}>
                                                        {getContainerStatusLabel(container)}
                                                    </span>
                                                    <span className="dx-muted-line">{getContainerStatus(container)}</span>
                                                </td>
                                                <td>
                                                    <div className="dx-port-list">
                                                        {ports.slice(0, 2).map((port, i) => (
                                                            <span key={i} className={`dx-port-pill ${port === '-' ? 'is-empty' : ''}`}>{port}</span>
                                                        ))}
                                                        {ports.length > 2 && <span className="dx-port-more">+{ports.length - 2}</span>}
                                                    </div>
                                                </td>
                                                <td>
                                                    <ContainerResourceBars stats={stats} muted={!isRunning} />
                                                </td>
                                                <td>
                                                    <span className="dx-muted-line">{container.created || container.CreatedAt || '-'}</span>
                                                </td>
                                                <td className="dx-row-actions" onClick={(e) => e.stopPropagation()}>
                                                    <button type="button" className="dx-row-action" onClick={() => setLogsContainer(container)} title="Logs">
                                                        <FileText size={13} />
                                                    </button>
                                                    {isRunning && !isRemote && (
                                                        <button type="button" className="dx-row-action" onClick={() => setExecContainer(container)} title="Exec">
                                                            <TerminalLucide size={13} />
                                                        </button>
                                                    )}
                                                    {isProtected ? (
                                                        <span className="dx-row-protected" title="ServerKit system container — managed by the panel, lifecycle controls are disabled">
                                                            <Lock size={11} /> System
                                                        </span>
                                                    ) : isRunning ? (
                                                        <>
                                                            <button type="button" className="dx-row-action" onClick={() => handleAction(containerId, 'restart')} title="Restart">
                                                                <RotateCw size={13} />
                                                            </button>
                                                            <button type="button" className="dx-row-action is-danger" onClick={() => handleAction(containerId, 'stop')} title="Stop">
                                                                <Square size={13} />
                                                            </button>
                                                        </>
                                                    ) : (
                                                        <>
                                                            <button type="button" className="dx-row-action is-success" onClick={() => handleAction(containerId, 'start')} title="Start">
                                                                <Play size={13} />
                                                            </button>
                                                            <button type="button" className="dx-row-action is-danger" onClick={() => handleAction(containerId, 'remove')} title="Remove">
                                                                <Trash2 size={13} />
                                                            </button>
                                                        </>
                                                    )}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </section>
                </div>
            )}

            {selectedContainer && (
                <ContainerInspector
                    container={selectedContainer}
                    stats={selectedStats}
                    onAction={handleAction}
                    onOpenLogs={setLogsContainer}
                    onOpenExec={setExecContainer}
                    onClose={() => setSelectedContainer(null)}
                />
            )}

            {logsContainer && (
                <ContainerLogsModal
                    container={logsContainer}
                    onClose={() => setLogsContainer(null)}
                />
            )}

            {execContainer && (
                <ContainerExecModal
                    container={execContainer}
                    onClose={() => setExecContainer(null)}
                />
            )}
        </div>
    );
};

const maskEnvValue = (entry) => {
    const [key, ...rest] = String(entry).split('=');
    if (!rest.length) return entry;
    if (/pass|secret|token|key|credential/i.test(key)) {
        return `${key}=****`;
    }
    return entry;
};

const ContainerInspector = ({ container, stats, onAction, onOpenLogs, onOpenExec, onClose }) => {
    const toast = useToast();
    const { serverId, isRemote } = useServer();
    const [details, setDetails] = useState(null);
    const [loading, setLoading] = useState(false);
    const [activeSection, setActiveSection] = useState('overview');
    const containerId = container ? getContainerId(container) : '';

    useEffect(() => {
        let mounted = true;
        let loadingTimer;

        async function loadDetails() {
            if (!container) {
                setDetails(null);
                return;
            }

            setLoading(true);
            loadingTimer = window.setTimeout(() => {
                if (mounted) setLoading(false);
            }, 2500);
            setActiveSection('overview');
            try {
                let data;
                if (isRemote) {
                    data = unwrapRemoteData(await api.getRemoteContainer(serverId, containerId));
                } else {
                    const result = await api.getContainer(containerId);
                    data = result.container || result;
                }
                if (mounted) setDetails(data || null);
            } catch (err) {
                console.error('Failed to inspect container:', err);
                if (mounted) setDetails(null);
            } finally {
                window.clearTimeout(loadingTimer);
                if (mounted) setLoading(false);
            }
        }

        loadDetails();
        return () => {
            mounted = false;
            window.clearTimeout(loadingTimer);
        };
    }, [container, containerId, serverId, isRemote]);

    if (!container) {
        return null;
    }

    const isRunning = isContainerRunning(container);
    const isProtected = isProtectedContainer(container);
    const ports = formatPorts(container.ports);
    const envVars = details?.Config?.Env || [];
    const mounts = details?.Mounts || [];
    const networks = Object.entries(details?.NetworkSettings?.Networks || {});
    const labels = details?.Config?.Labels || {};
    const restartPolicy = details?.HostConfig?.RestartPolicy?.Name || '-';
    const health = details?.State?.Health?.Status || getContainerStatusLabel(container);
    const projectName = getContainerProjectName(container, details);

    async function copyContainerId() {
        try {
            await navigator.clipboard.writeText(containerId);
            toast.success('Container ID copied');
        } catch {
            toast.error('Could not copy container ID');
        }
    }

    return (
        <>
        <div className="dx-drawer-backdrop" onClick={onClose} />
        <aside className="dx-inspector dx-inspector-drawer">
            <div className="dx-inspector-header">
                <div className="dx-inspector-icon">
                    <Box size={18} />
                </div>
                <div className="dx-inspector-title">
                    <h3 title={getContainerName(container)}>{getContainerName(container)}</h3>
                    <span>{shortId(containerId)}</span>
                </div>
                <button type="button" className="dx-row-action" onClick={copyContainerId} title="Copy container ID">
                    <Copy size={13} />
                </button>
                <button type="button" className="dx-row-action" onClick={onClose} title="Close details">
                    <X size={13} />
                </button>
            </div>

            <div className="dx-inspector-status">
                <span className={`dx-status-pill ${isRunning ? 'running' : 'stopped'}`}>
                    {getContainerStatusLabel(container)}
                </span>
                <span>{health}</span>
            </div>

            <div className="dx-inspector-actions">
                <button type="button" className="dx-action-btn" onClick={() => onOpenLogs(container)}>
                    <FileText size={13} /> Logs
                </button>
                {isRunning && !isRemote && (
                    <button type="button" className="dx-action-btn" onClick={() => onOpenExec(container)}>
                        <TerminalLucide size={13} /> Exec
                    </button>
                )}
                {isProtected ? (
                    <span className="dx-action-protected" title="ServerKit system container — managed by the panel, lifecycle controls are disabled">
                        <Lock size={13} /> System container
                    </span>
                ) : isRunning ? (
                    <>
                        <button type="button" className="dx-action-btn" onClick={() => onAction(containerId, 'restart')}>
                            <RotateCw size={13} /> Restart
                        </button>
                        <button type="button" className="dx-action-btn is-danger" onClick={() => onAction(containerId, 'stop')}>
                            <Square size={13} /> Stop
                        </button>
                    </>
                ) : (
                    <>
                        <button type="button" className="dx-action-btn is-success" onClick={() => onAction(containerId, 'start')}>
                            <Play size={13} /> Start
                        </button>
                        <button type="button" className="dx-action-btn is-danger" onClick={() => onAction(containerId, 'remove')}>
                            <Trash2 size={13} /> Remove
                        </button>
                    </>
                )}
            </div>

            <div className="dx-inspector-tabs">
                {['overview', 'ports', 'mounts', 'env'].map(section => (
                    <button type="button"
                        key={section}
                        className={activeSection === section ? 'active' : ''}
                        onClick={() => setActiveSection(section)}
                    >
                        {section}
                    </button>
                ))}
            </div>

            <div className="dx-inspector-body">
                {loading && <div className="dx-inspector-loading">Inspecting container...</div>}

                {activeSection === 'overview' && (
                    <>
                        <ContainerResourceBars stats={stats} muted={!isRunning} />
                        <div className="dx-detail-grid">
                            <div><span>Image</span><strong title={getContainerImage(container)}>{getContainerImage(container)}</strong></div>
                            <div><span>Project</span><strong>{projectName}</strong></div>
                            <div><span>Restart</span><strong>{restartPolicy}</strong></div>
                            <div><span>Created</span><strong>{container.created || container.CreatedAt || '-'}</strong></div>
                        </div>
                        <div className="dx-section-title"><Gauge size={13} /> Runtime</div>
                        <div className="dx-details-list">
                            <span>Status</span><code>{getContainerStatus(container)}</code>
                            <span>PID</span><code>{details?.State?.Pid || '-'}</code>
                            <span>Platform</span><code>{details?.Platform || details?.Os || '-'}</code>
                            <span>Driver</span><code>{details?.Driver || '-'}</code>
                        </div>
                    </>
                )}

                {activeSection === 'ports' && (
                    <>
                        <div className="dx-section-title"><Activity size={13} /> Published ports</div>
                        <div className="dx-inspector-list">
                            {ports.map((port, index) => (
                                <code key={index} className={port === '-' ? 'is-empty' : ''}>{port}</code>
                            ))}
                        </div>
                        <div className="dx-section-title"><ServerIcon size={13} /> Networks</div>
                        <div className="dx-details-list">
                            {networks.length === 0 ? (
                                <>
                                    <span>Networks</span><code>-</code>
                                </>
                            ) : networks.map(([name, network]) => (
                                <React.Fragment key={name}>
                                    <span>{name}</span>
                                    <code>{network?.IPAddress || network?.Gateway || '-'}</code>
                                </React.Fragment>
                            ))}
                        </div>
                    </>
                )}

                {activeSection === 'mounts' && (
                    <>
                        <div className="dx-section-title"><Database size={13} /> Mounts and volumes</div>
                        <div className="dx-inspector-list">
                            {mounts.length === 0 ? (
                                <code className="is-empty">No mounts</code>
                            ) : mounts.map((mount, index) => (
                                <code key={index}>
                                    {mount.Name || mount.Source || '-'} -&gt; {mount.Destination || '-'}
                                </code>
                            ))}
                        </div>
                    </>
                )}

                {activeSection === 'env' && (
                    <>
                        <div className="dx-section-title"><Package size={13} /> Environment</div>
                        <div className="dx-inspector-list">
                            {envVars.length === 0 ? (
                                <code className="is-empty">No environment variables</code>
                            ) : envVars.slice(0, 24).map((entry, index) => (
                                <code key={index}>{maskEnvValue(entry)}</code>
                            ))}
                            {envVars.length > 24 && <code>+{envVars.length - 24} more variables</code>}
                        </div>
                        <div className="dx-section-title"><Clock3 size={13} /> Labels</div>
                        <div className="dx-details-list">
                            {Object.keys(labels).length === 0 ? (
                                <>
                                    <span>Labels</span><code>-</code>
                                </>
                            ) : Object.entries(labels).slice(0, 12).map(([key, value]) => (
                                <React.Fragment key={key}>
                                    <span title={key}>{key}</span>
                                    <code title={value}>{value}</code>
                                </React.Fragment>
                            ))}
                        </div>
                    </>
                )}
            </div>
        </aside>
        </>
    );
};

const RunContainerModal = ({ onClose, onCreated }) => {
    const [formData, setFormData] = useState({
        image: '',
        name: '',
        ports: '',
        volumes: '',
        env: '',
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    function handleChange(e) {
        setFormData({ ...formData, [e.target.name]: e.target.value });
    }

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            const data = {
                image: formData.image,
                name: formData.name || undefined,
                ports: formData.ports ? formData.ports.split(',').map(p => p.trim()) : [],
                volumes: formData.volumes ? formData.volumes.split(',').map(v => v.trim()) : [],
                env: formData.env ? Object.fromEntries(
                    formData.env.split('\n').filter(l => l.includes('=')).map(l => {
                        const [key, ...rest] = l.split('=');
                        return [key.trim(), rest.join('=').trim()];
                    })
                ) : {},
            };

            await api.runContainer(data);
            onCreated();
            onClose();
        } catch (err) {
            setError(err.message || 'Failed to run container');
        } finally {
            setLoading(false);
        }
    }

    return (
        <Modal open onClose={onClose} title="Run Container" size="md">
            {error && <div className="error-message">{error}</div>}

            <form onSubmit={handleSubmit}>
                <div className="form-group">
                    <label>Image *</label>
                    <Input
                        type="text"
                        name="image"
                        value={formData.image}
                        onChange={handleChange}
                        placeholder="nginx:latest"
                        required
                    />
                </div>

                <div className="form-group">
                    <label>Container Name</label>
                    <Input
                        type="text"
                        name="name"
                        value={formData.name}
                        onChange={handleChange}
                        placeholder="my-container"
                    />
                </div>

                <div className="form-group">
                    <label>Ports (comma-separated)</label>
                    <Input
                        type="text"
                        name="ports"
                        value={formData.ports}
                        onChange={handleChange}
                        placeholder="8080:80, 443:443"
                    />
                </div>

                <div className="form-group">
                    <label>Volumes (comma-separated)</label>
                    <Input
                        type="text"
                        name="volumes"
                        value={formData.volumes}
                        onChange={handleChange}
                        placeholder="/host/path:/container/path"
                    />
                </div>

                <div className="form-group">
                    <label>Environment Variables (one per line, KEY=value)</label>
                    <Textarea
                        name="env"
                        value={formData.env}
                        onChange={handleChange}
                        placeholder="NODE_ENV=production&#10;API_KEY=xxx"
                        rows={4}
                    />
                </div>

                <div className="modal-actions">
                    <Button type="button" variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button type="submit" disabled={loading}>
                        {loading ? 'Running...' : 'Run Container'}
                    </Button>
                </div>
            </form>
        </Modal>
    );
};

const ContainerLogsModal = ({ container, onClose }) => {
    const { serverId, isRemote } = useServer();
    const containerId = getContainerId(container);
    const [logs, setLogs] = useState('');
    const [loading, setLoading] = useState(true);
    const [tail, setTail] = useState(200);
    const [searchPattern, setSearchPattern] = useState('');
    const [appliedSearch, setAppliedSearch] = useState('');
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [showLineNumbers, setShowLineNumbers] = useState(true);
    const [wrapLines, setWrapLines] = useState(true);
    const contentRef = useRef(null);
    const intervalRef = useRef(null);

    useEffect(() => {
        loadLogs();
    }, [container, tail]); // eslint-disable-line

    useEffect(() => {
        if (autoRefresh) {
            intervalRef.current = setInterval(() => loadLogs(false), 3000);
        }
        return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
    }, [autoRefresh, tail]); // eslint-disable-line

    async function loadLogs(showSpinner = true) {
        if (showSpinner) setLoading(true);
        try {
            let data;
            if (isRemote) {
                const result = await api.getRemoteContainerLogs(serverId, containerId, tail);
                data = unwrapRemoteData(result);
            } else {
                data = await api.getContainerLogs(containerId, tail);
            }
            setLogs(data.logs || '');
            if (autoRefresh && contentRef.current) {
                contentRef.current.scrollTop = contentRef.current.scrollHeight;
            }
        } catch (err) {
            setLogs('Failed to load logs: ' + (err.message || 'Unknown error'));
        } finally {
            setLoading(false);
        }
    }

    function handleDownload() {
        if (!logs) return;
        const blob = new Blob([logs], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${container.name}-${Date.now()}.log`;
        a.click();
        URL.revokeObjectURL(url);
    }

    return (
        // The shared DS drawer. (The container INSPECTOR next door stays on the
        // `dx-*` classes — that is the Docker workspace's own language.)
        <Drawer
            open
            onOpenChange={(open) => { if (!open) onClose(); }}
            title={getContainerName(container)}
            subtitle={`${getContainerImage(container)} · ${shortId(containerId)}`}
            icon={<Box size={18} />}
            width={520}
            flush
        >
                <div className="preview-drawer-meta">
                    <div className="meta-item">
                        <span className="meta-label">Status</span>
                        <span className="meta-value">{getContainerStatus(container)}</span>
                    </div>
                    <div className="meta-item">
                        <span className="meta-label">Image</span>
                        <span className="meta-value mono">{getContainerImage(container)}</span>
                    </div>
                    <div className="meta-item meta-item-wide">
                        <span className="meta-label">ID</span>
                        <span className="meta-value mono">{containerId}</span>
                    </div>
                    {container.ports && container.ports.length > 0 && (
                        <div className="meta-item meta-item-wide">
                            <span className="meta-label">Ports</span>
                            <span className="meta-value mono">{formatPorts(container.ports).join(', ')}</span>
                        </div>
                    )}
                </div>

                <LogToolbar
                    searchPattern={searchPattern}
                    onSearchChange={setSearchPattern}
                    onSearchSubmit={() => setAppliedSearch(searchPattern)}
                    onSearchClear={() => { setSearchPattern(''); setAppliedSearch(''); }}
                    lineCount={tail}
                    onLineCountChange={(n) => setTail(n)}
                    autoRefresh={autoRefresh}
                    onAutoRefreshToggle={() => setAutoRefresh(!autoRefresh)}
                    showLineNumbers={showLineNumbers}
                    onToggleLineNumbers={() => setShowLineNumbers(!showLineNumbers)}
                    wrapLines={wrapLines}
                    onToggleWrap={() => setWrapLines(!wrapLines)}
                    isFullscreen={false}
                    onToggleFullscreen={() => {}}
                    onRefresh={() => loadLogs()}
                    onDownload={handleDownload}
                    onClear={() => {}}
                    onScrollToBottom={() => {
                        if (contentRef.current) contentRef.current.scrollTop = contentRef.current.scrollHeight;
                    }}
                    canAct={true}
                />

                <div className="preview-drawer-body">
                    <LogContent
                        ref={contentRef}
                        content={logs}
                        loading={loading}
                        emptyMessage="No log output."
                        showLineNumbers={showLineNumbers}
                        wrapLines={wrapLines}
                        searchPattern={appliedSearch}
                    />
                </div>
        </Drawer>
    );
};

const ContainerExecModal = ({ container, onClose }) => {
    const containerId = getContainerId(container);
    const [command, setCommand] = useState('');
    const [output, setOutput] = useState([]);
    const [loading, setLoading] = useState(false);
    const [history, setHistory] = useState([]);
    const [historyIndex, setHistoryIndex] = useState(-1);
    const outputRef = React.useRef(null);
    const inputRef = React.useRef(null);

    useEffect(() => {
        if (inputRef.current) {
            inputRef.current.focus();
        }
    }, []);

    useEffect(() => {
        if (outputRef.current) {
            outputRef.current.scrollTop = outputRef.current.scrollHeight;
        }
    }, [output]);

    async function executeCommand(e) {
        e.preventDefault();
        if (!command.trim() || loading) return;

        const cmd = command.trim();
        setOutput(prev => [...prev, { type: 'command', text: `$ ${cmd}` }]);
        setHistory(prev => [cmd, ...prev.slice(0, 49)]);
        setHistoryIndex(-1);
        setCommand('');
        setLoading(true);

        try {
            const result = await api.execContainer(containerId, cmd);
            const stdout = result.output ?? result.stdout;
            const stderr = result.error ?? result.stderr;
            const exitCode = result.exit_code ?? result.return_code;
            if (stdout) {
                setOutput(prev => [...prev, { type: 'output', text: stdout }]);
            }
            if (stderr) {
                setOutput(prev => [...prev, { type: 'error', text: stderr }]);
            }
            if (exitCode !== undefined && exitCode !== 0) {
                setOutput(prev => [...prev, { type: 'info', text: `Exit code: ${exitCode}` }]);
            }
        } catch (err) {
            setOutput(prev => [...prev, { type: 'error', text: err.message || 'Failed to execute command' }]);
        } finally {
            setLoading(false);
            if (inputRef.current) {
                inputRef.current.focus();
            }
        }
    }

    function handleKeyDown(e) {
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (history.length > 0 && historyIndex < history.length - 1) {
                const newIndex = historyIndex + 1;
                setHistoryIndex(newIndex);
                setCommand(history[newIndex]);
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (historyIndex > 0) {
                const newIndex = historyIndex - 1;
                setHistoryIndex(newIndex);
                setCommand(history[newIndex]);
            } else if (historyIndex === 0) {
                setHistoryIndex(-1);
                setCommand('');
            }
        }
    }

    function clearOutput() {
        setOutput([]);
    }

    return (
        <Modal open onClose={onClose} title={`Exec: ${getContainerName(container)}`} size="lg">
            <div className="modal-body exec-modal-body">
                <div className="exec-output" ref={outputRef}>
                    {output.length === 0 ? (
                        <div className="exec-welcome">
                            <p>Execute commands in container <code>{getContainerName(container)}</code></p>
                            <p className="text-muted">Type a command and press Enter</p>
                        </div>
                    ) : (
                        output.map((line, idx) => (
                            <div key={idx} className={`exec-line exec-${line.type}`}>
                                <pre>{line.text}</pre>
                            </div>
                        ))
                    )}
                    {loading && (
                        <div className="exec-line exec-loading">
                            <span className="spinner-inline"></span> Running...
                        </div>
                    )}
                </div>
                <form onSubmit={executeCommand} className="exec-input-form">
                    <span className="exec-prompt">$</span>
                    <input
                        ref={inputRef}
                        type="text"
                        value={command}
                        onChange={(e) => setCommand(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Enter command..."
                        className="exec-input"
                        disabled={loading}
                        autoComplete="off"
                        spellCheck="false"
                    />
                    <Button type="submit" size="sm" disabled={loading || !command.trim()}>
                        Run
                    </Button>
                </form>
            </div>
            <div className="modal-actions">
                <Button variant="outline" onClick={clearOutput}>Clear</Button>
                <Button onClick={onClose}>Close</Button>
            </div>
        </Modal>
    );
};

export default ContainersTab;
