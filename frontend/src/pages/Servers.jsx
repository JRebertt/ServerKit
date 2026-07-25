import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
    Activity,
    CheckCircle2,
    Clock3,
    Folder,
    Plus,
    RefreshCw,
    Search,
    Server as ServerLucideIcon,
    XCircle,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { ConfirmDialog } from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable } from '@/components/ds';
import LinkPanelForm from '../components/servers/LinkPanelForm';

const Servers = () => {
    const [servers, setServers] = useState([]);
    const [groups, setGroups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showAddModal, setShowAddModal] = useState(false);
    const [showGroupModal, setShowGroupModal] = useState(false);
    const [selectedGroup, setSelectedGroup] = useState('all');
    const [selectedStatus, setSelectedStatus] = useState('all');
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedIds, setSelectedIds] = useState(() => new Set());
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
    const toast = useToast();

    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            const [serversData, groupsData] = await Promise.all([
                api.getServers(),
                api.getServerGroups()
            ]);
            setServers(Array.isArray(serversData) ? serversData : []);
            setGroups(Array.isArray(groupsData) ? groupsData : []);
        } catch (err) {
            console.error('Failed to load servers:', err);
            toast.error('Failed to load servers');
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => {
        loadData();
    }, [loadData]);

    async function handlePingServer(serverId) {
        try {
            const result = await api.pingServer(serverId);
            if (result.success) {
                toast.success(`Server responded in ${result.latency}ms`);
            } else {
                toast.error('Server did not respond');
            }
            loadData();
        } catch {
            toast.error('Failed to ping server');
        }
    }

    async function handleDeleteServer() {
        if (!deleteTarget) return;
        try {
            await api.deleteServer(deleteTarget.id);
            toast.success(`${deleteTarget.name} removed from fleet`);
            setSelectedIds(prev => {
                const next = new Set(prev);
                next.delete(deleteTarget.id);
                return next;
            });
            setDeleteTarget(null);
            loadData();
        } catch (err) {
            toast.error(err.message || 'Failed to delete server');
        }
    }

    async function handleBulkDelete() {
        const ids = Array.from(selectedIds);
        if (ids.length === 0) return;
        const results = await Promise.allSettled(ids.map(id => api.deleteServer(id)));
        const failed = results.filter(r => r.status === 'rejected').length;
        if (failed === 0) {
            toast.success(`${ids.length} server${ids.length === 1 ? '' : 's'} deleted`);
        } else {
            toast.error(`${failed} of ${ids.length} could not be deleted`);
        }
        setSelectedIds(new Set());
        setBulkDeleteOpen(false);
        loadData();
    }

    async function handleCopyInstall(server) {
        try {
            const result = await api.generateRegistrationToken(server.id);
            const connString = result?.connection_string;
            if (!connString) {
                toast.error('Could not generate connection string');
                return;
            }
            await navigator.clipboard.writeText(connString);
            toast.success('Connection string copied to clipboard');
        } catch (err) {
            toast.error(err.message || 'Failed to generate connection string');
        }
    }

    function toggleSelect(id) {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    }

    function toggleSelectAll(visibleIds) {
        setSelectedIds(prev => {
            const allSelected = visibleIds.length > 0 && visibleIds.every(id => prev.has(id));
            if (allSelected) {
                const next = new Set(prev);
                visibleIds.forEach(id => next.delete(id));
                return next;
            }
            const next = new Set(prev);
            visibleIds.forEach(id => next.add(id));
            return next;
        });
    }

    const filteredServers = servers.filter(server => {
        const matchesGroup = selectedGroup === 'all' ||
            (selectedGroup === 'ungrouped' && !server.group_id) ||
            String(server.group_id) === String(selectedGroup);
        const matchesStatus = selectedStatus === 'all' || server.status === selectedStatus;
        const matchesSearch = !searchTerm ||
            server.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
            server.hostname?.toLowerCase().includes(searchTerm.toLowerCase()) ||
            server.ip_address?.toLowerCase().includes(searchTerm.toLowerCase());
        return matchesGroup && matchesStatus && matchesSearch;
    });

    const fleetStats = {
        total: servers.length,
        online: servers.filter(s => s.status === 'online').length,
        offline: servers.filter(s => s.status === 'offline').length,
        connecting: servers.filter(s => s.status === 'connecting').length,
        pending: servers.filter(s => s.status === 'pending').length
    };
    const availability = fleetStats.total > 0 ? Math.round((fleetStats.online / fleetStats.total) * 100) : 0;
    const hasActiveFilters = selectedGroup !== 'all' || selectedStatus !== 'all' || Boolean(searchTerm);
    const groupCounts = servers.reduce((acc, server) => {
        const key = server.group_id ? String(server.group_id) : 'ungrouped';
        acc[key] = (acc[key] || 0) + 1;
        return acc;
    }, {});
    const statusFilters = [
        {
            key: 'all',
            label: 'All servers',
            value: fleetStats.total,
            detail: `${groups.length} group${groups.length === 1 ? '' : 's'}`,
            icon: ServerLucideIcon,
        },
        {
            key: 'online',
            label: 'Online',
            value: fleetStats.online,
            detail: `${availability}% available`,
            icon: CheckCircle2,
        },
        {
            key: 'offline',
            label: 'Offline',
            value: fleetStats.offline,
            detail: 'Needs attention',
            icon: XCircle,
        },
        {
            key: 'connecting',
            label: 'Connecting',
            value: fleetStats.connecting,
            detail: 'Agent handshake',
            icon: RefreshCw,
        },
        {
            key: 'pending',
            label: 'Pending',
            value: fleetStats.pending,
            detail: 'Awaiting install',
            icon: Clock3,
        },
    ];
    const groupFilters = [
        { key: 'all', label: 'All groups', value: fleetStats.total },
        ...groups.map(group => ({
            key: String(group.id),
            label: group.name,
            value: groupCounts[String(group.id)] || 0,
        })),
        { key: 'ungrouped', label: 'Ungrouped', value: groupCounts.ungrouped || 0 },
    ];
    const activeStatusLabel = statusFilters.find(filter => filter.key === selectedStatus)?.label || 'All servers';
    const fleetStateLabel = fleetStats.total === 0
        ? 'No agents paired'
        : fleetStats.offline > 0
            ? 'Needs attention'
            : (fleetStats.connecting + fleetStats.pending) > 0
                ? 'Pairing in progress'
                : 'Healthy';

    if (loading) {
        return (
            <div className="servers-page servers-page--loading">
                <div className="servers-loading-card">
                    <ServerIcon />
                    <span>Scanning fleet...</span>
                </div>
            </div>
        );
    }

    const visibleIds = filteredServers.map(s => s.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => selectedIds.has(id));
    const someVisibleSelected = visibleIds.some(id => selectedIds.has(id));

    return (
        <div className="servers-page servers-page--ops">
            <div className="servers-ops-workspace">
                <aside className="servers-fleet-rail">
                    <section className="servers-rail-section servers-rail-section--health">
                        <div className="servers-rail-section-header">
                            <Activity size={14} />
                            <span>Fleet health</span>
                        </div>
                        <div className="servers-health-dial" style={{ '--availability': `${availability * 3.6}deg` }}>
                            <strong>{availability}%</strong>
                            <span>available</span>
                        </div>
                        <div className="servers-health-summary">
                            <strong>{fleetStateLabel}</strong>
                            <span>{fleetStats.online} of {fleetStats.total} online</span>
                        </div>
                    </section>

                    <section className="servers-rail-section">
                        <div className="servers-rail-section-header">
                            <ServerLucideIcon size={14} />
                            <span>Status</span>
                        </div>
                        <div className="servers-status-nav">
                            {statusFilters.map(filter => {
                                const Icon = filter.icon;
                                return (
                                    <button
                                        type="button"
                                        key={filter.key}
                                        className={`servers-status-nav-item servers-status-nav-item--${filter.key} ${selectedStatus === filter.key ? 'active' : ''}`}
                                        onClick={() => setSelectedStatus(filter.key)}
                                    >
                                        <Icon size={15} />
                                        <span>
                                            <strong>{filter.label}</strong>
                                            <small>{filter.detail}</small>
                                        </span>
                                        <b>{filter.value}</b>
                                    </button>
                                );
                            })}
                        </div>
                    </section>

                    <section className="servers-rail-section">
                        <div className="servers-rail-section-header servers-rail-section-header--split">
                            <span>
                                <Folder size={14} />
                                Groups
                            </span>
                            <Button type="button" variant="ghost" size="sm" onClick={() => setShowGroupModal(true)}>
                                Manage
                            </Button>
                        </div>
                        <div className="servers-group-nav">
                            {groupFilters.map(filter => (
                                <button
                                    type="button"
                                    key={filter.key}
                                    className={`servers-group-nav-item ${selectedGroup === filter.key ? 'active' : ''}`}
                                    onClick={() => setSelectedGroup(filter.key)}
                                >
                                    <Folder size={14} />
                                    <span>{filter.label}</span>
                                    <b>{filter.value}</b>
                                </button>
                            ))}
                        </div>
                    </section>
                </aside>

                <main className="servers-main">
                    <div className="servers-workbar">
                        <div className="servers-workbar-title">
                            <span>Servers</span>
                            <h1>{activeStatusLabel}</h1>
                            <em>{filteredServers.length} visible of {servers.length}</em>
                        </div>
                        <div className="servers-workbar-actions">
                            <Button variant="outline" onClick={() => setShowGroupModal(true)}>
                                <Folder size={16} /> Groups
                            </Button>
                            <Button onClick={() => setShowAddModal(true)}>
                                <Plus size={16} /> Add Server
                            </Button>
                        </div>
                    </div>

                    <div className="servers-command-bar">
                        <div className="servers-toolbar">
                            <label className="search-box">
                                <Search size={16} />
                                <Input
                                    type="text"
                                    placeholder="Search by name, host, or IP..."
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                />
                            </label>
                        </div>

                        <div className="servers-results-summary">
                            <strong>{filteredServers.length}</strong>
                            <span>{filteredServers.length === 1 ? 'server' : 'servers'}</span>
                            {hasActiveFilters && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="servers-clear-filters"
                                    onClick={() => {
                                        setSelectedGroup('all');
                                        setSelectedStatus('all');
                                        setSearchTerm('');
                                    }}
                                >
                                    Clear filters
                                </Button>
                            )}
                        </div>
                    </div>

                    {selectedIds.size > 0 && (
                        <div className="servers-bulk-bar" role="region" aria-label="Bulk actions">
                            <div className="servers-bulk-bar__info">
                                <span className="servers-bulk-bar__count">{selectedIds.size}</span>
                                <span>selected</span>
                            </div>
                            <div className="servers-bulk-bar__actions">
                                <Button type="button" variant="ghost" size="sm" onClick={() => setSelectedIds(new Set())}>
                                    Clear selection
                                </Button>
                                <Button type="button" variant="destructive" size="sm" onClick={() => setBulkDeleteOpen(true)}>
                                    <TrashIcon /> Delete {selectedIds.size}
                                </Button>
                            </div>
                        </div>
                    )}

                    {filteredServers.length === 0 ? (
                        <EmptyState
                            icon={ServerLucideIcon}
                            title={servers.length === 0 ? 'No servers yet' : 'No servers match these filters'}
                            description={servers.length === 0
                                ? 'Add a server to start managing it from here.'
                                : 'Adjust the filters or search query to see your servers.'}
                            action={servers.length === 0 ? (
                                <Button onClick={() => setShowAddModal(true)}>
                                    <Plus size={16} /> Add your first server
                                </Button>
                            ) : (
                                <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => {
                                        setSelectedGroup('all');
                                        setSelectedStatus('all');
                                        setSearchTerm('');
                                    }}
                                >
                                    Clear filters
                                </Button>
                            )}
                        />
                    ) : (
                        <div className="servers-table-wrap">
                            <DataTable
                                tableClassName="servers-table"
                                sortable={false}
                                columns={[
                                    { key: 'select', header: (
                                        <input
                                            type="checkbox"
                                            aria-label="Select all visible servers"
                                            checked={allVisibleSelected}
                                            ref={el => { if (el) el.indeterminate = someVisibleSelected && !allVisibleSelected; }}
                                            onChange={() => toggleSelectAll(visibleIds)}
                                        />
                                    ), className: 'col-check' },
                                    { key: 'server', header: 'Server' },
                                    { key: 'status', header: 'Status' },
                                    { key: 'group', header: 'Group' },
                                    { key: 'os', header: 'OS · Agent' },
                                    { key: 'telemetry', header: 'Telemetry' },
                                    { key: 'lastSeen', header: 'Last seen' },
                                    { key: 'actions', header: '', className: 'col-actions' },
                                ]}
                                data={filteredServers}
                                keyField="id"
                                renderRow={(server, { key }) => (
                                    <ServerRow
                                        key={key}
                                        server={server}
                                        selected={selectedIds.has(server.id)}
                                        onToggle={() => toggleSelect(server.id)}
                                        onPing={() => handlePingServer(server.id)}
                                        onDelete={() => setDeleteTarget(server)}
                                        onCopyInstall={() => handleCopyInstall(server)}
                                    />
                                )}
                            />
                        </div>
                    )}
                </main>
            </div>

            {showAddModal && (
                <AddServerModal
                    groups={groups}
                    onClose={() => setShowAddModal(false)}
                    onCreated={() => {
                        setShowAddModal(false);
                        loadData();
                    }}
                />
            )}

            {showGroupModal && (
                <ManageGroupsModal
                    groups={groups}
                    onClose={() => setShowGroupModal(false)}
                    onUpdated={loadData}
                />
            )}

            <ConfirmDialog
                isOpen={Boolean(deleteTarget)}
                title={`Delete ${deleteTarget?.name || 'server'}?`}
                message="This removes the server from your fleet and revokes its agent token. The agent on the host will stop reporting."
                requireConfirmation={deleteTarget?.name}
                confirmText="Delete server"
                variant="danger"
                onConfirm={handleDeleteServer}
                onCancel={() => setDeleteTarget(null)}
            />

            <ConfirmDialog
                isOpen={bulkDeleteOpen}
                title={`Delete ${selectedIds.size} server${selectedIds.size === 1 ? '' : 's'}?`}
                message="All selected servers will be removed from the fleet and their agent tokens revoked. This cannot be undone."
                requireConfirmation="DELETE"
                confirmText={`Delete ${selectedIds.size} server${selectedIds.size === 1 ? '' : 's'}`}
                variant="danger"
                onConfirm={handleBulkDelete}
                onCancel={() => setBulkDeleteOpen(false)}
            />
        </div>
    );
};

const formatLastSeen = (timestamp) => {
    if (!timestamp) return 'Never';
    const date = new Date(timestamp);
    const now = new Date();
    const diff = (now - date) / 1000;
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return date.toLocaleDateString();
};

const clamp = (v) => Math.min(100, Math.max(0, Number(v) || 0));

const ServerRow = ({ server, selected, onToggle, onPing, onDelete, onCopyInstall, className = '', onClick }) => {
    const [menuPos, setMenuPos] = useState(null);
    const triggerRef = useRef(null);
    const menuRef = useRef(null);

    const closeMenu = useCallback(() => setMenuPos(null), []);

    const openMenu = () => {
        const r = triggerRef.current?.getBoundingClientRect();
        if (!r) return;
        const menuHeight = 240;
        const menuWidth = 220;
        const flipUp = r.bottom + menuHeight + 8 > window.innerHeight;
        setMenuPos({
            top: flipUp ? r.top - menuHeight - 4 : r.bottom + 4,
            left: Math.max(8, r.right - menuWidth),
        });
    };

    useEffect(() => {
        if (!menuPos) return undefined;
        const onDocDown = (e) => {
            if (
                menuRef.current && !menuRef.current.contains(e.target) &&
                triggerRef.current && !triggerRef.current.contains(e.target)
            ) {
                closeMenu();
            }
        };
        const onScroll = () => closeMenu();
        document.addEventListener('mousedown', onDocDown);
        window.addEventListener('scroll', onScroll, true);
        window.addEventListener('resize', onScroll);
        return () => {
            document.removeEventListener('mousedown', onDocDown);
            window.removeEventListener('scroll', onScroll, true);
            window.removeEventListener('resize', onScroll);
        };
    }, [menuPos, closeMenu]);

    const status = server.status || 'pending';
    const displayHost = server.hostname || server.ip_address || 'Unassigned endpoint';
    const initial = (server.name || displayHost || '?').charAt(0).toUpperCase();
    const metrics = {
        cpu: clamp(server.metrics?.cpu_percent),
        memory: clamp(server.metrics?.memory_percent),
        disk: clamp(server.metrics?.disk_percent),
    };
    const hasMetrics = server.metrics && status === 'online';

    return (
        <tr
            className={`server-row server-row--${status} ${selected ? 'is-selected' : ''} ${className}`.trim()}
            onClick={onClick}
        >
            <td className="col-check">
                <input
                    type="checkbox"
                    checked={selected}
                    onChange={onToggle}
                    aria-label={`Select ${server.name}`}
                />
            </td>
            <td>
                <Link to={`/servers/${server.id}`} className="server-row__name">
                    <span className={`server-row__avatar server-row__avatar--${status}`} aria-hidden="true">{initial}</span>
                    <span className="server-row__identity">
                        <span className="server-row__title">{server.name}</span>
                        <span className="server-row__sub">{displayHost}</span>
                    </span>
                </Link>
            </td>
            <td>
                <span className={`status-pill status-pill--${status}`}>
                    <span className="status-pill__dot" />
                    {status}
                </span>
            </td>
            <td>
                {server.group_name ? (
                    <span className="server-row__group">
                        <FolderIcon size={12} />
                        {server.group_name}
                    </span>
                ) : (
                    <span className="muted">—</span>
                )}
            </td>
            <td>
                <div className="server-row__stack">
                    <span>{server.os_type || 'Unknown'}</span>
                    <span className="muted">{server.agent_version ? `agent ${server.agent_version}` : 'agent not installed'}</span>
                </div>
            </td>
            <td>
                {hasMetrics ? (
                    <div className="server-row__telemetry">
                        <span title={`CPU ${metrics.cpu.toFixed(0)}%`}>
                            <em>CPU</em>
                            <span className="bar"><span className="bar-fill cpu" style={{ width: `${metrics.cpu}%` }} /></span>
                            <b>{metrics.cpu.toFixed(0)}%</b>
                        </span>
                        <span title={`RAM ${metrics.memory.toFixed(0)}%`}>
                            <em>RAM</em>
                            <span className="bar"><span className="bar-fill memory" style={{ width: `${metrics.memory}%` }} /></span>
                            <b>{metrics.memory.toFixed(0)}%</b>
                        </span>
                        <span title={`Disk ${metrics.disk.toFixed(0)}%`}>
                            <em>DSK</em>
                            <span className="bar"><span className="bar-fill disk" style={{ width: `${metrics.disk}%` }} /></span>
                            <b>{metrics.disk.toFixed(0)}%</b>
                        </span>
                    </div>
                ) : (
                    <span className="muted">{status === 'pending' ? 'Awaiting agent' : status === 'offline' ? 'Offline' : 'No data'}</span>
                )}
            </td>
            <td>
                <span className="server-row__lastseen">{formatLastSeen(server.last_seen)}</span>
            </td>
            <td className="col-actions">
                <div className="row-actions">
                    <button type="button" className="row-actions__icon" onClick={onPing} title="Ping server" aria-label={`Ping ${server.name}`}>
                        <RefreshIcon />
                    </button>
                    <Link to={`/servers/${server.id}/docker`} className="row-actions__icon" title="Open Docker" aria-label={`Open Docker for ${server.name}`}>
                        <DockerIcon />
                    </Link>
                    <button
                        ref={triggerRef}
                        type="button"
                        className="row-actions__icon"
                        onClick={() => (menuPos ? closeMenu() : openMenu())}
                        aria-haspopup="menu"
                        aria-expanded={Boolean(menuPos)}
                        title="More actions"
                    >
                        <MoreIcon />
                    </button>
                    {menuPos && (
                        <div
                            ref={menuRef}
                            className="row-menu"
                            role="menu"
                            style={{ position: 'fixed', top: menuPos.top, left: menuPos.left }}
                        >
                            <Link to={`/servers/${server.id}`} className="row-menu__item" role="menuitem" onClick={closeMenu}>
                                <EyeIcon /> View details
                            </Link>
                            <button type="button" className="row-menu__item" role="menuitem" onClick={() => { closeMenu(); onPing(); }}>
                                <RefreshIcon /> Ping now
                            </button>
                            {status === 'pending' && (
                                <button type="button" className="row-menu__item" role="menuitem" onClick={() => { closeMenu(); onCopyInstall(); }}>
                                    <CopyIcon /> Copy connection string
                                </button>
                            )}
                            <Link to={`/servers/${server.id}/docker`} className="row-menu__item" role="menuitem" onClick={closeMenu}>
                                <DockerIcon /> Manage Docker
                            </Link>
                            <div className="row-menu__divider" />
                            <button type="button" className="row-menu__item row-menu__item--danger" role="menuitem" onClick={() => { closeMenu(); onDelete(); }}>
                                <TrashIcon /> Delete server
                            </button>
                        </div>
                    )}
                </div>
            </td>
        </tr>
    );
};

const PairAgentForm = ({ groups, onClose, onClaimed }) => {
    const [pairCode, setPairCode] = useState('');
    const [passphrase, setPassphrase] = useState('');
    const [name, setName] = useState('');
    const [groupId, setGroupId] = useState('');
    const [lookupResult, setLookupResult] = useState(null);
    const [lookupError, setLookupError] = useState('');
    const [claimError, setClaimError] = useState('');
    const [loading, setLoading] = useState(false);
    const toast = useToast();

    const formattedCode = pairCode
        .toUpperCase()
        .replace(/[^0-9A-Z]/g, '')
        .replace(/[01OIL]/g, '')
        .slice(0, 6);

    // Auto-lookup as soon as the user finishes typing all 6 characters.
    // Avoids showing "must be 6 chars" while the user is still mid-entry or
    // just clicking around — the previous onBlur trigger fired too eagerly.
    useEffect(() => {
        if (formattedCode.length !== 6) return;
        let cancelled = false;
        setLookupError('');
        setLoading(true);
        api.lookupPairCode(formattedCode)
            .then((res) => {
                if (cancelled) return;
                setLookupResult(res);
                // Prefer the operator-set display name (entered in the agent's
                // wizard) over the raw hostname. Falls back to hostname when
                // the agent didn't supply one.
                const suggestedName = res.system_info?.display_name
                    || res.system_info?.hostname;
                if (!name && suggestedName) setName(suggestedName);
            })
            .catch((err) => {
                if (cancelled) return;
                setLookupError(err.message || 'Pair code not found');
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [formattedCode]);

    async function handleClaim(e) {
        e.preventDefault();
        setClaimError('');
        // Trim before validating: copy/paste from the agent screen sometimes
        // catches a trailing space, which used to silently fail the claim.
        const cleanPass = passphrase.trim();
        if (!cleanPass) {
            setClaimError('Passphrase is required');
            return;
        }
        setLoading(true);
        try {
            await api.claimPairedAgent({
                pair_code: formattedCode,
                passphrase: cleanPass,
                name: name || undefined,
                group_id: groupId || undefined,
                trust_fingerprint: true
            });
            toast.success('Agent paired successfully');
            onClaimed();
        } catch (err) {
            const status = err.status || err.response?.status;
            if (status === 429) {
                setClaimError('Too many attempts. Wait a few minutes, or re-open the agent wizard to start a new pairing.');
            } else if (status === 401) {
                setClaimError('Pair code or passphrase is wrong. Check both values exactly as shown on the agent screen.');
            } else {
                setClaimError(err.message || 'Failed to claim agent');
            }
        } finally {
            setLoading(false);
        }
    }

    function formatDisplay(code) {
        if (!code) return '------';
        return code.length > 3 ? `${code.slice(0, 3)}-${code.slice(3)}` : code;
    }

    return (
        <form className="server-setup-form" onSubmit={handleClaim}>
            <div className="server-setup-form__body">
                <div className="pair-instructions">
                    <p>
                        On the target machine, start the agent. It will display a&nbsp;6-character pair code and a passphrase — enter both below.
                    </p>
                </div>

                <div className="form-group">
                    <label>Pair code</label>
                    <Input
                        type="text"
                        value={formatDisplay(formattedCode)}
                        onChange={(e) => {
                            setPairCode(e.target.value);
                            setLookupResult(null);
                            setLookupError('');
                        }}
                        placeholder="ABC-123"
                        autoFocus
                        autoComplete="off"
                        spellCheck={false}
                        style={{ fontFamily: 'monospace', fontSize: '1.25rem', letterSpacing: '0.15em', textAlign: 'center' }}
                        required
                    />
                    <span className="form-hint">The code is shown in the terminal output or system tray.</span>
                    {lookupError && <div className="error-message" style={{ marginTop: '0.5rem' }}>{lookupError}</div>}
                </div>

                {lookupResult && (
                    <div className="success-banner" style={{ marginTop: '0.5rem' }}>
                        <div>
                            <strong>Agent found</strong>
                            <p className="success-subtitle">
                                {lookupResult.system_info?.display_name && (
                                    <>Server: <code>{lookupResult.system_info.display_name}</code><br /></>
                                )}
                                Hostname: <code>{lookupResult.system_info?.hostname || 'unknown'}</code><br />
                                Fingerprint: <code style={{ fontFamily: 'monospace' }}>{lookupResult.pubkey_fpr}</code>
                            </p>
                            <p className="text-muted" style={{ marginTop: '0.25rem', fontSize: '0.85em' }}>
                                Confirm this fingerprint matches the one shown by the agent before continuing.
                            </p>
                        </div>
                    </div>
                )}

                <div className="form-group">
                    <label>Passphrase *</label>
                    <Input
                        type="text"
                        value={passphrase}
                        onChange={(e) => setPassphrase(e.target.value)}
                        placeholder="Shown on the agent's pairing screen"
                        autoComplete="off"
                        spellCheck={false}
                        style={{ fontFamily: 'monospace', fontSize: '1.1rem', letterSpacing: '0.08em' }}
                        required
                    />
                </div>

                <div className="form-row">
                    <div className="form-group">
                        <label>Server name</label>
                        <Input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder={lookupResult?.system_info?.hostname || 'Auto-detected from agent (optional)'}
                        />
                        <span className="form-hint">Leave blank to use the agent&apos;s hostname.</span>
                    </div>
                    <div className="form-group">
                        <label>Group</label>
                        <select value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                            <option value="">No Group</option>
                            {groups.map(g => (
                                <option key={g.id} value={g.id}>{g.name}</option>
                            ))}
                        </select>
                    </div>
                </div>

                {claimError && <div className="error-message">{claimError}</div>}
            </div>

            <div className="modal-actions">
                <Button type="button" variant="outline" onClick={onClose}>
                    Cancel
                </Button>
                <Button type="submit" disabled={loading || formattedCode.length !== 6}>
                    {loading ? 'Pairing…' : 'Pair Agent'}
                </Button>
            </div>
        </form>
    );
};

// Token-lifetime presets shown in the "Add Server" expiry dropdown. The value
// is in seconds; -1 is a sentinel for "never" (the backend turns it into a
// far-future date). Default is 7 days — long enough to set up later that
// evening, short enough that an abandoned string doesn't linger forever as a
// usable bearer credential.
const EXPIRY_OPTIONS = [
    { label: '1 hour',  value: 60 * 60 },
    { label: '24 hours', value: 24 * 60 * 60 },
    { label: '7 days',  value: 7 * 24 * 60 * 60 },
    { label: '30 days', value: 30 * 24 * 60 * 60 },
    { label: 'Never',   value: -1 },
];
const DEFAULT_EXPIRY = 7 * 24 * 60 * 60;

const AddServerModal = ({ groups, onClose, onCreated }) => {
    const [mode, setMode] = useState('install');
    const [step, setStep] = useState(1);
    const [groupId, setGroupId] = useState('');
    const [expiresIn, setExpiresIn] = useState(DEFAULT_EXPIRY);
    const [registrationData, setRegistrationData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const toast = useToast();

    async function handleCreateServer(e) {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            // The backend now derives the server name from the agent's
            // hostname on /register, so we just send what the user can
            // actually pick: the token's lifetime and (optionally) which
            // group the row should land in.
            const result = await api.createServer({
                expires_in: expiresIn,
                group_id: groupId || undefined,
            });
            setRegistrationData(result);
            setStep(2);
        } catch (err) {
            setError(err.message || 'Failed to create server');
        } finally {
            setLoading(false);
        }
    }

    function copyToClipboard(text) {
        navigator.clipboard.writeText(text);
        toast.success('Copied to clipboard');
    }

    const connectionString = registrationData?.connection_string || '';
    const linuxInstallScript = registrationData ? `curl -fsSL ${window.location.origin}/api/v1/servers/install.sh | sudo bash -s -- \\
  --server "${window.location.origin}" \\
  --token "${registrationData.registration_token}"` : '';

    const windowsInstallScript = registrationData ? `irm ${window.location.origin}/api/v1/servers/install.ps1 | iex
Install-ServerKitAgent -Server "${window.location.origin}" -Token "${registrationData.registration_token}"` : '';

    return (
        <Modal
            open
            onClose={onClose}
            size="lg"
            className="server-setup-modal"
            title={step === 1 ? (mode === 'link' ? 'Link to Master Panel' : 'Add Server') : (mode === 'pair' ? 'Pair Agent' : 'Connect Agent')}
        >
                <p className="sk-modal__subtitle">
                    {step === 1 && mode === 'link'
                        ? 'Make THIS server manageable by another ServerKit panel — no agent install needed.'
                        : step === 2 && mode !== 'pair'
                        ? 'Paste the connection string into the agent, or run the one-liner installer.'
                        : step === 2
                        ? 'Enter the 6-char code shown on the agent and your passphrase.'
                        : 'Connect an existing agent or set up a brand-new machine.'}
                </p>

                {step === 1 && (
                    <div className="mode-switcher">
                        <button
                            type="button"
                            className={`mode-switcher__tab${mode === 'install' ? ' is-active' : ''}`}
                            onClick={() => setMode('install')}
                        >
                            Connection string
                        </button>
                        <button
                            type="button"
                            className={`mode-switcher__tab${mode === 'pair' ? ' is-active' : ''}`}
                            onClick={() => setMode('pair')}
                        >
                            Pair code
                        </button>
                        <button
                            type="button"
                            className={`mode-switcher__tab${mode === 'link' ? ' is-active' : ''}`}
                            onClick={() => setMode('link')}
                        >
                            Link panel
                        </button>
                    </div>
                )}

                {step === 1 && mode === 'link' ? (
                    <LinkPanelForm onClose={onClose} />
                ) : step === 1 && mode === 'pair' ? (
                    <PairAgentForm
                        groups={groups}
                        onClose={onClose}
                        onClaimed={onCreated}
                    />
                ) : step === 1 ? (
                    <form className="server-setup-form" onSubmit={handleCreateServer}>
                        <div className="server-setup-form__body">
                            {error && <div className="error-message">{error}</div>}

                            <p className="section-description">
                                Generate a single connection string. Paste it into the agent&apos;s
                                pairing wizard, or use it with the one-liner installer. The
                                agent&apos;s hostname becomes the server name on first connect — you
                                can rename it later from the server&apos;s Settings tab.
                            </p>

                            <div className="form-row">
                                <div className="form-group">
                                    <label>Group</label>
                                    <select value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                                        <option value="">No Group</option>
                                        {groups.map(group => (
                                            <option key={group.id} value={group.id}>{group.name}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Token expires</label>
                                    <select
                                        value={expiresIn}
                                        onChange={(e) => setExpiresIn(Number(e.target.value))}
                                    >
                                        {EXPIRY_OPTIONS.map(opt => (
                                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                                        ))}
                                    </select>
                                    <span className="form-hint">Single-use. Burned the moment an agent registers with it.</span>
                                </div>
                            </div>
                        </div>

                        <div className="modal-actions">
                            <Button type="button" variant="outline" onClick={onClose}>
                                Cancel
                            </Button>
                            <Button type="submit" disabled={loading}>
                                {loading ? 'Generating…' : 'Generate Connection String'}
                            </Button>
                        </div>
                    </form>
                ) : (
                    <div className="install-instructions">
                        <div className="install-instructions__scroll">
                            <div className="success-banner">
                                <CheckCircleIcon />
                                <div>
                                    <strong>Connection string ready</strong>
                                    <p className="success-subtitle">Paste this into the agent, or run the installer.</p>
                                </div>
                            </div>

                            <ConnectionStringField
                                value={connectionString}
                                onCopy={() => copyToClipboard(connectionString)}
                            />

                            <details className="install-fallback">
                                <summary>Need to install the agent first? Use the one-liner installer.</summary>
                                <div className="install-tabs" style={{ marginTop: '0.75rem' }}>
                                    <InstallTab
                                        title="Linux"
                                        description="curl, tar, sudo, and systemd"
                                        icon={<TerminalIcon />}
                                        script={linuxInstallScript}
                                        onCopy={() => copyToClipboard(linuxInstallScript)}
                                    />
                                    <InstallTab
                                        title="Windows (PowerShell)"
                                        description="Run as Administrator"
                                        icon={<WindowsIcon />}
                                        script={windowsInstallScript}
                                        onCopy={() => copyToClipboard(windowsInstallScript)}
                                    />
                                </div>
                            </details>

                            <div className="install-info">
                                <h4>What happens next?</h4>
                                <ol>
                                    <li>Open the agent on your target machine and paste the connection string.</li>
                                    <li>The agent registers automatically and reports its hostname back as the server name.</li>
                                    <li>The row in this list will switch from <strong>Pending</strong> to <strong>Online</strong>.</li>
                                </ol>
                                <p className="text-muted">
                                    The token is single-use. If you reinstall the agent later, generate a new connection string from the server&apos;s Settings tab.
                                </p>
                            </div>
                        </div>

                        <div className="modal-actions">
                            <Button onClick={onCreated}>
                                Close
                            </Button>
                        </div>
                    </div>
                )}
        </Modal>
    );
};

const ConnectionStringField = ({ value, onCopy }) => {
    return (
        <div className="connection-string-field">
            <div className="connection-string-field__header">
                <KeyIcon />
                <span>Connection string</span>
                <Button variant="outline" size="sm" onClick={onCopy}>
                    <CopyIcon /> Copy
                </Button>
            </div>
            <pre className="connection-string-field__value">{value}</pre>
        </div>
    );
};

const InstallTab = ({ title, description, icon, script, onCopy }) => {
    return (
        <div className="install-tab">
            <div className="install-tab-header">
                {icon}
                <div className="install-tab-title">
                    <span>{title}</span>
                    {description && <span className="install-tab-description">{description}</span>}
                </div>
                <Button variant="outline" size="sm" onClick={onCopy}>
                    <CopyIcon /> Copy
                </Button>
            </div>
            <pre className="install-script">{script}</pre>
        </div>
    );
};

const ManageGroupsModal = ({ groups, onClose, onUpdated }) => {
    const [groupList, setGroupList] = useState(groups);
    const [newGroupName, setNewGroupName] = useState('');
    const [editingGroup, setEditingGroup] = useState(null);
    const [loading, setLoading] = useState(false);
    const toast = useToast();

    async function handleCreateGroup(e) {
        e.preventDefault();
        if (!newGroupName.trim()) return;

        setLoading(true);
        try {
            await api.createServerGroup({ name: newGroupName.trim() });
            setNewGroupName('');
            toast.success('Group created');
            onUpdated();
            const data = await api.getServerGroups();
            setGroupList(Array.isArray(data) ? data : []);
        } catch (err) {
            toast.error(err.message || 'Failed to create group');
        } finally {
            setLoading(false);
        }
    }

    async function handleUpdateGroup(groupId, newName) {
        try {
            await api.updateServerGroup(groupId, { name: newName });
            toast.success('Group updated');
            setEditingGroup(null);
            onUpdated();
            const data = await api.getServerGroups();
            setGroupList(Array.isArray(data) ? data : []);
        } catch (err) {
            toast.error(err.message || 'Failed to update group');
        }
    }

    async function handleDeleteGroup(groupId) {
        if (!confirm('Delete this group? Servers in this group will become ungrouped.')) return;

        try {
            await api.deleteServerGroup(groupId);
            toast.success('Group deleted');
            onUpdated();
            const data = await api.getServerGroups();
            setGroupList(Array.isArray(data) ? data : []);
        } catch (err) {
            toast.error(err.message || 'Failed to delete group');
        }
    }

    return (
        <Modal open onClose={onClose} title="Manage Server Groups">
                <form onSubmit={handleCreateGroup} className="group-form">
                    <Input
                        type="text"
                        value={newGroupName}
                        onChange={(e) => setNewGroupName(e.target.value)}
                        placeholder="New group name..."
                        disabled={loading}
                    />
                    <Button type="submit" disabled={loading || !newGroupName.trim()}>
                        <PlusIcon /> Add
                    </Button>
                </form>

                <div className="groups-list">
                    {groupList.length === 0 ? (
                        <div className="empty-groups">No groups created yet</div>
                    ) : (
                        groupList.map(group => (
                            <div key={group.id} className="group-item">
                                {editingGroup === group.id ? (
                                    <Input
                                        type="text"
                                        defaultValue={group.name}
                                        onBlur={(e) => handleUpdateGroup(group.id, e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleUpdateGroup(group.id, e.target.value);
                                            if (e.key === 'Escape') setEditingGroup(null);
                                        }}
                                        autoFocus
                                    />
                                ) : (
                                    <>
                                        <span className="group-name">
                                            <FolderIcon size={14} />
                                            {group.name}
                                        </span>
                                        <span className="group-count">{group.server_count || 0} servers</span>
                                        <div className="group-actions">
                                            <button type="button"
                                                className="btn-icon"
                                                onClick={() => setEditingGroup(group.id)}
                                                title="Edit"
                                            >
                                                <EditIcon />
                                            </button>
                                            <button type="button"
                                                className="btn-icon danger"
                                                onClick={() => handleDeleteGroup(group.id)}
                                                title="Delete"
                                            >
                                                <TrashIcon />
                                            </button>
                                        </div>
                                    </>
                                )}
                            </div>
                        ))
                    )}
                </div>

                <div className="modal-actions">
                    <Button onClick={onClose}>Done</Button>
                </div>
        </Modal>
    );
};

// Icons
const ServerIcon = ({ size = 24, className = '' }) => (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
        <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
        <line x1="6" y1="6" x2="6.01" y2="6"/>
        <line x1="6" y1="18" x2="6.01" y2="18"/>
    </svg>
);

const PlusIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="12" y1="5" x2="12" y2="19"/>
        <line x1="5" y1="12" x2="19" y2="12"/>
    </svg>
);

const FolderIcon = ({ size = 16 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
);

const CheckCircleIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
        <polyline points="22 4 12 14.01 9 11.01"/>
    </svg>
);

const RefreshIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="23 4 23 10 17 10"/>
        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
    </svg>
);

const EyeIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
        <circle cx="12" cy="12" r="3"/>
    </svg>
);

const DockerIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="7" width="5" height="5" rx="1"/>
        <rect x="9" y="7" width="5" height="5" rx="1"/>
        <rect x="16" y="7" width="5" height="5" rx="1"/>
        <rect x="2" y="14" width="5" height="5" rx="1"/>
        <rect x="9" y="14" width="5" height="5" rx="1"/>
    </svg>
);

const TerminalIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="4 17 10 11 4 5"/>
        <line x1="12" y1="19" x2="20" y2="19"/>
    </svg>
);

const WindowsIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
        <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801"/>
    </svg>
);

const CopyIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
    </svg>
);

const EditIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
    </svg>
);

const TrashIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="3 6 5 6 21 6"/>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
    </svg>
);

const MoreIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
        <circle cx="5" cy="12" r="1.6"/>
        <circle cx="12" cy="12" r="1.6"/>
        <circle cx="19" cy="12" r="1.6"/>
    </svg>
);

const KeyIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
    </svg>
);

export default Servers;
