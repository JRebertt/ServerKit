import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Layers,
    Inbox,
    Send,
    Trash2,
    RefreshCw,
    Plus,
    Activity,
    Folder,
    Server,
    AlertCircle,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useConfirm } from '../hooks/useConfirm';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
    DataTable, DataTableFooter, MetricCard, Pill, SearchField, SortChipBar,
    statusKind, statusLabel,
} from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { formatCompact, formatFull } from '../utils/formatNumber';
import { usePolling } from '@/hooks/usePolling';

const STATUS_ORDER = ['pending', 'in_flight', 'completed', 'failed', 'dead_letter'];

const POLL_INTERVAL = 3000;

// Built-in saved views.
//
// The per-status presets go through the rail's OWN Message Status filter (the
// `page` bag) instead of a column rule: a queue carries five separate counts
// that all render inside the single Messages cell, and one column can only
// expose one number to the rule engine — `total`. "Has a dead-lettered
// message" is therefore only expressible as page state.
//
// Every preset also resets the group to All. `selectedGroup` decides which
// group's queues are FETCHED, so a preset that left it alone would show a
// different set depending on what happened to be selected when it was clicked.
const PAGE = (messageFilter) => ({ selectedGroup: '', messageFilter, searchTerm: '' });
const NO_RULES = { match: 'all', rules: [] };
const BY_SIZE = [{ key: 'messages', direction: 'desc' }];

const BUILTIN_VIEWS = [
    {
        // Queues holding work nobody has picked up yet, biggest first.
        name: 'Backlog',
        state: { page: PAGE('pending'), sorts: BY_SIZE, hiddenKeys: [], columnFilters: NO_RULES },
    },
    {
        // A consumer is erroring here, but these messages still have retries.
        name: 'Failing',
        state: { page: PAGE('failed'), sorts: BY_SIZE, hiddenKeys: ['created'], columnFilters: NO_RULES },
    },
    {
        // Retries exhausted — nothing moves these without a manual requeue.
        name: 'Dead letter',
        state: { page: PAGE('dead_letter'), sorts: BY_SIZE, hiddenKeys: ['created'], columnFilters: NO_RULES },
    },
    {
        // Where the traffic actually is, across every status.
        name: 'Busiest',
        state: {
            page: PAGE('all'), sorts: BY_SIZE, hiddenKeys: [],
            columnFilters: { match: 'all', rules: [{ id: 'busy', field: 'messages', op: 'gt', value: 0 }] },
        },
    },
    {
        // Declared but never written to: the queues to wire up or delete.
        // Newest first, because a queue created minutes ago being empty is
        // expected and one created months ago being empty is the finding.
        name: 'Never used',
        state: {
            page: PAGE('all'), sorts: [{ key: 'created', direction: 'desc' }], hiddenKeys: [],
            columnFilters: { match: 'all', rules: [{ id: 'unused', field: 'messages', op: 'eq', value: 0 }] },
        },
    },
];

const QueueOperations = () => {
    const toast = useToast();
    const { confirm } = useConfirm();

    const [loading, setLoading] = useState(true);
    const [groups, setGroups] = useState([]);
    const [queues, setQueues] = useState([]);
    const [stats, setStats] = useState(null);

    const [selectedGroup, setSelectedGroup] = useState('');
    const [messageFilter, setMessageFilter] = useState('all');
    const [searchTerm, setSearchTerm] = useState('');

    const [showGroupModal, setShowGroupModal] = useState(false);
    const [groupForm, setGroupForm] = useState({ name: '', description: '' });

    const [showQueueModal, setShowQueueModal] = useState(false);
    const [queueForm, setQueueForm] = useState({ name: '', description: '', config: '{}' });

    const [sendTarget, setSendTarget] = useState(null);
    const [sendForm, setSendForm] = useState({ payload: '{}', priority: 0, delay_ms: 0 });
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-queue-ops-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-queue-ops-cols' });

    // The three narrowing controls this page owns, as the envelope's `page`
    // bag. Group and status are what the rail clicks set, so a saved view
    // restores the rail to the state it was captured in.
    const viewPageState = useMemo(
        () => ({ selectedGroup, messageFilter, searchTerm }),
        [selectedGroup, messageFilter, searchTerm],
    );
    const applyViewPageState = useCallback((saved) => {
        if (saved.selectedGroup !== undefined) setSelectedGroup(saved.selectedGroup);
        if (saved.messageFilter !== undefined) setMessageFilter(saved.messageFilter);
        if (saved.searchTerm !== undefined) setSearchTerm(saved.searchTerm);
    }, []);

    const navigate = useNavigate();

    const loadData = useCallback(async () => {
        try {
            const [groupsRes, statsRes] = await Promise.all([
                api.getQueueGroups(),
                api.getGlobalQueueStats(),
            ]);
            setGroups(groupsRes.groups || []);
            setStats(statsRes);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setLoading(false);
        }
    }, [toast]);

    const loadQueues = useCallback(async (groupSlug) => {
        try {
            if (groupSlug) {
                const res = await api.getQueues(groupSlug);
                setQueues(res.queues || []);
                return;
            }
            // All groups: fan out and merge.
            const lists = await Promise.all(
                groups.map(g => api.getQueues(g.slug).then(r => r.queues || []).catch(() => []))
            );
            setQueues(lists.flat());
        } catch (err) {
            toast.error(err.message);
        }
    }, [groups, toast]);

    useEffect(() => {
        loadData();
    }, [loadData]);

    // Reload when the selected group changes; poll on top of that.
    useEffect(() => {
        loadQueues(selectedGroup);
    }, [selectedGroup, loadQueues]);

    usePolling(
        () => Promise.all([loadData(), loadQueues(selectedGroup)]),
        POLL_INTERVAL,
        { immediate: false },
    );

    const totalQueues = useMemo(
        () => groups.reduce((acc, g) => acc + (g.stats?.queues || 0), 0),
        [groups]
    );

    const totalMessages = useMemo(
        () => (stats ? Object.values(stats.messages || {}).reduce((a, b) => a + b, 0) : 0),
        [stats]
    );

    const statusCounts = useMemo(() => stats?.messages || {}, [stats]);

    const filteredQueues = useMemo(() => {
        const q = searchTerm.trim().toLowerCase();
        return queues.filter(queue => {
            const matchesSearch = !q ||
                queue.name?.toLowerCase().includes(q) ||
                queue.slug?.toLowerCase().includes(q) ||
                queue.group_slug?.toLowerCase().includes(q);
            const matchesStatus = messageFilter === 'all' || (queue.stats?.[messageFilter] || 0) > 0;
            return matchesSearch && matchesStatus;
        });
    }, [queues, searchTerm, messageFilter]);

    const activeGroup = useMemo(
        () => groups.find(g => g.slug === selectedGroup),
        [groups, selectedGroup]
    );

    // System-owned groups are read-only: their queues can be viewed but not
    // mutated (the backend enforces this too). Used to hide destructive actions.
    const systemGroupSlugs = useMemo(
        () => new Set(groups.filter(g => g.owner_type === 'system').map(g => g.slug)),
        [groups]
    );

    const handleCreateGroup = async (e) => {
        e.preventDefault();
        try {
            await api.createQueueGroup({
                name: groupForm.name,
                description: groupForm.description,
            });
            toast.success('Queue group created');
            setShowGroupModal(false);
            setGroupForm({ name: '', description: '' });
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleCreateQueue = async (e) => {
        e.preventDefault();
        const groupSlug = queueForm.groupSlug || selectedGroup;
        if (!groupSlug) {
            toast.error('Select a group for the queue');
            return;
        }
        let config = {};
        try {
            config = JSON.parse(queueForm.config);
        } catch {
            toast.error('Config must be valid JSON');
            return;
        }
        try {
            await api.createQueue(groupSlug, {
                name: queueForm.name,
                description: queueForm.description,
                config,
            });
            toast.success('Queue created');
            setShowQueueModal(false);
            setQueueForm({ name: '', description: '', config: '{}' });
            loadQueues(selectedGroup);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleDeleteQueue = async (queue) => {
        const confirmed = await confirm({
            title: 'Delete Queue',
            message: `Are you sure you want to delete "${queue.name || queue.slug}" and all its messages?`,
            variant: 'danger',
        });
        if (!confirmed) return;
        try {
            await api.deleteQueue(queue.group_slug, queue.slug);
            toast.success('Queue deleted');
            loadQueues(selectedGroup);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const openSendModal = (queue) => {
        setSendTarget(queue);
        setSendForm({ payload: '{}', priority: 0, delay_ms: 0 });
    };

    const handleSendMessage = async (e) => {
        e.preventDefault();
        const queue = sendTarget;
        if (!queue?.group_slug || !queue?.slug) {
            toast.error('Select a destination queue');
            return;
        }
        let payload = {};
        try {
            payload = JSON.parse(sendForm.payload);
        } catch {
            toast.error('Payload must be valid JSON');
            return;
        }
        try {
            await api.sendMessage(queue.group_slug, queue.slug, payload, {
                priority: parseInt(sendForm.priority, 10) || 0,
                delay_ms: parseInt(sendForm.delay_ms, 10) || 0,
            });
            toast.success('Message sent');
            setSendTarget(null);
            loadQueues(selectedGroup);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const openQueue = (queue) => {
        navigate(`/queue/${encodeURIComponent(queue.group_slug)}/${encodeURIComponent(queue.slug)}`);
    };

    const hasActiveFilters = selectedGroup !== '' || messageFilter !== 'all' || Boolean(searchTerm);

    const activeStatusLabel = messageFilter === 'all'
        ? 'All queues'
        : `${statusLabel(messageFilter)} queues`;
    const activeGroupLabel = activeGroup ? activeGroup.name : 'All groups';

    // DataTable columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace, so _queue-operations.scss keeps applying
    // (.queue-table, .queue-row-*, .queue-actions, .col-actions).
    const columns = [
        {
            key: 'name',
            header: 'Queue',
            sortable: true,
            hideable: false,
            sortValue: (queue) => queue.name || queue.slug || '',
            render: (queue) => (
                <div className="queue-row-name">
                    <span className="queue-row-title">{queue.name}</span>
                    <code className="queue-row-sub">/{queue.slug}</code>
                </div>
            ),
        },
        {
            key: 'group',
            header: 'Group',
            sortable: true,
            sortValue: (queue) => queue.group_slug || null,
            render: (queue) => (
                queue.group_slug && (
                    <span className="queue-row-group">
                        <Folder size={12} /> {queue.group_slug}
                    </span>
                )
            ),
        },
        {
            key: 'messages',
            header: 'Messages',
            sortable: true,
            // The cell renders five per-status pills, but a rule can only ever
            // mean one number — the total. Declared explicitly so the "Busiest"
            // and "Never used" presets compare against it rather than against
            // whatever the type inference makes of the pill markup.
            type: 'num',
            value: (queue) => queue.stats?.total ?? 0,
            sortValue: (queue) => queue.stats?.total ?? 0,
            render: (queue) => (
                <div className="queue-row-counts" onClick={e => e.stopPropagation()}>
                    {STATUS_ORDER.filter(s => (queue.stats?.[s] || 0) > 0).map(status => (
                        <Pill key={status} kind={statusKind(status)}>
                            {statusLabel(status)} {queue.stats[status]}
                        </Pill>
                    ))}
                    {(queue.stats?.total || 0) === 0 && (
                        <span className="muted">Empty</span>
                    )}
                </div>
            ),
        },
        {
            key: 'created',
            header: 'Created',
            sortable: true,
            // The sort wants epoch ms, but that number is also what the filter
            // would infer from — leaving the column menu offering "is under
            // 1755…". `value` hands the rule engine the ISO string instead, so
            // the menu offers before/after with a date picker.
            type: 'date',
            value: (queue) => queue.created_at,
            sortValue: (queue) => new Date(queue.created_at).getTime(),
            render: (queue) => new Date(queue.created_at).toLocaleString(),
        },
        {
            key: '__actions',
            header: '',
            sortable: false,
            hideable: false,
            className: 'col-actions',
            cellClassName: 'col-actions',
            render: (queue) => (
                <div className="queue-actions" onClick={e => e.stopPropagation()}>
                    {!systemGroupSlugs.has(queue.group_slug) && (
                        <Button variant="ghost" size="sm" onClick={() => openSendModal(queue)} title="Send message">
                            <Send size={14} />
                        </Button>
                    )}
                    <Button variant="ghost" size="sm" onClick={() => openQueue(queue)} title="View messages">
                        <Inbox size={14} />
                    </Button>
                    {!systemGroupSlugs.has(queue.group_slug) && (
                        <Button variant="ghost" size="sm" onClick={() => handleDeleteQueue(queue)} title="Delete queue">
                            <Trash2 size={14} />
                        </Button>
                    )}
                </div>
            ),
        },
    ];

    // Shared list chrome: view picker + filter chips + filter drawer + tools,
    // driven off this page's existing sorts/hiddenKeys state. Declared before
    // the loading return so the hook order never changes between renders.
    const chrome = useTableChrome({
        columns,
        rows: filteredQueues,
        viewPageKey: 'queue-operations',
        builtinViews: BUILTIN_VIEWS,
        noun: 'queues',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        pageState: viewPageState,
        applyPage: applyViewPageState,
    });

    if (loading) {
        return (
            <div className="queue-page queue-page--loading">
                <div className="queue-loading-card">
                    <Layers size={24} />
                    <span>Loading queue bus...</span>
                </div>
            </div>
        );
    }

    return (
        <div className="queue-page queue-page--ops">
            <div className="queue-ops-workspace">
                <aside className="queue-fleet-rail">
                    <section className="queue-rail-section queue-rail-section--overview">
                        <div className="queue-rail-section-header">
                            <Activity size={14} />
                            <span>Overview</span>
                        </div>
                        <div className="queue-rail-overview">
                            <MetricCard label="Groups" value={groups.length} compact />
                            <MetricCard label="Queues" value={totalQueues} compact />
                            <MetricCard label="Messages" value={totalMessages} compact />
                            <MetricCard label="Dead Letter" value={statusCounts.dead_letter || 0} kind="danger" compact />
                        </div>
                    </section>

                    <section className="queue-rail-section">
                        <div className="queue-rail-section-header queue-rail-section-header--split">
                            <span><Folder size={14} /> Groups</span>
                            <button type="button" onClick={() => setShowGroupModal(true)}>New</button>
                        </div>
                        <div className="queue-group-nav">
                            <button
                                type="button"
                                className={`queue-group-nav-item ${selectedGroup === '' ? 'active' : ''}`}
                                onClick={() => setSelectedGroup('')}
                            >
                                <Server size={14} />
                                <span>All groups</span>
                                <b title={String(formatFull(totalQueues))}>{formatCompact(totalQueues)}</b>
                            </button>
                            {groups.map(group => (
                                <button
                                    type="button"
                                    key={group.id}
                                    className={`queue-group-nav-item ${selectedGroup === group.slug ? 'active' : ''}`}
                                    onClick={() => setSelectedGroup(group.slug)}
                                >
                                    <Folder size={14} />
                                    <span>{group.name}</span>
                                    {group.owner_type === 'system' && (
                                        <span className="queue-group-badge">system</span>
                                    )}
                                    <b>{formatCompact(group.stats?.queues || 0)}</b>
                                </button>
                            ))}
                        </div>
                    </section>

                    <section className="queue-rail-section">
                        <div className="queue-rail-section-header">
                            <AlertCircle size={14} />
                            <span>Message Status</span>
                        </div>
                        <div className="queue-status-nav">
                            <button
                                type="button"
                                className={`queue-status-nav-item ${messageFilter === 'all' ? 'active' : ''}`}
                                onClick={() => setMessageFilter('all')}
                            >
                                <span><strong>All</strong><small>Any status</small></span>
                                <b title={String(formatFull(totalMessages))}>{formatCompact(totalMessages)}</b>
                            </button>
                            {STATUS_ORDER.map(status => (
                                <button
                                    type="button"
                                    key={status}
                                    className={`queue-status-nav-item queue-status-nav-item--${status} ${messageFilter === status ? 'active' : ''}`}
                                    onClick={() => setMessageFilter(status)}
                                >
                                    <span>
                                        <strong>{statusLabel(status)}</strong>
                                        <small>{status}</small>
                                    </span>
                                    <b title={String(formatFull(statusCounts[status] || 0))}>{formatCompact(statusCounts[status] || 0)}</b>
                                </button>
                            ))}
                        </div>
                    </section>
                </aside>

                <main className="queue-main">
                    <div className="queue-workbar">
                        <div className="queue-workbar-title">
                            <span>Queue Bus</span>
                            <h1>{activeGroupLabel}</h1>
                            <em>{activeStatusLabel} · {filteredQueues.length} visible</em>
                        </div>
                        <div className="queue-workbar-actions">
                            <Button variant="outline" onClick={() => setShowGroupModal(true)}>
                                <Folder size={16} /> Group
                            </Button>
                            <Button variant="outline" onClick={() => setShowQueueModal(true)}>
                                <Plus size={16} /> Queue
                            </Button>
                            <Button variant="outline" onClick={() => { loadData(); loadQueues(selectedGroup); }}>
                                <RefreshCw size={16} /> Refresh
                            </Button>
                        </div>
                    </div>

                    {/* The view name is the page's heading for the list, and
                        the table's own chrome sits on that same line. */}
                    <GridViewPicker
                        views={chrome.views}
                        label="queues"
                        onCreate={chrome.createView}
                        actions={(
                            <>
                                <SearchField
                                    value={searchTerm}
                                    onSearch={setSearchTerm}
                                    placeholder="Search queues…"
                                />
                                <GridFilterButton
                                    count={chrome.filterCount}
                                    onClick={() => chrome.setDrawerOpen(true)}
                                />
                                <GridToolsMenu
                                    {...chrome.toolsProps}
                                    onRefresh={() => { loadData(); loadQueues(selectedGroup); }}
                                />
                            </>
                        )}
                    />

                    {/* The group select stays out of the chrome row: it decides
                        which group's queues are FETCHED, not how the loaded
                        rows are shown. */}
                    <div className="queue-command-bar">
                        <div className="queue-toolbar">
                            <select
                                className="queue-select"
                                value={selectedGroup}
                                onChange={(e) => setSelectedGroup(e.target.value)}
                            >
                                <option value="">All groups</option>
                                {groups.map(g => <option key={g.id} value={g.slug}>{g.name}</option>)}
                            </select>
                        </div>
                        {hasActiveFilters && (
                            <button
                                type="button"
                                className="queue-clear-filters"
                                onClick={() => {
                                    setSelectedGroup('');
                                    setMessageFilter('all');
                                    setSearchTerm('');
                                }}
                            >
                                Clear filters
                            </button>
                        )}
                    </div>

                    <GridChips {...chrome.chipProps} />

                    <SortChipBar columns={columns} sorts={sorts} onChange={setSorts} />

                    {filteredQueues.length === 0 ? (
                        <EmptyState
                            icon={Layers}
                            title={queues.length === 0 ? 'No queues yet' : 'No queues match these filters'}
                            description={queues.length === 0
                                ? 'Create a queue group and queue to start sending messages.'
                                : 'Adjust the filters or search query to see your queues.'}
                            action={queues.length === 0 ? (
                                <Button onClick={() => setShowGroupModal(true)}>
                                    <Plus size={16} /> Create Group
                                </Button>
                            ) : (
                                <Button variant="outline" onClick={() => {
                                    setSelectedGroup('');
                                    setMessageFilter('all');
                                    setSearchTerm('');
                                }}>
                                    Clear filters
                                </Button>
                            )}
                        />
                    ) : (
                        <DataTable
                            columns={chrome.columns}
                            data={filteredQueues}
                            keyField="id"
                            sorts={sorts}
                            onSortsChange={setSorts}
                            {...chrome.tableProps}
                            onRowClick={(queue) => openQueue(queue)}
                            className="queue-table-wrap"
                            tableClassName="queue-table"
                            footer={(
                                <DataTableFooter
                                    shown={filteredQueues.length}
                                    total={queues.length}
                                    noun="queue"
                                />
                            )}
                        />
                    )}
                </main>
            </div>

            {/* Create Group Modal */}
            <Modal open={showGroupModal} onClose={() => setShowGroupModal(false)} title="Create Queue Group">
                        <form onSubmit={handleCreateGroup}>
                                <div className="form-group">
                                    <Label htmlFor="group-name">Name</Label>
                                    <Input id="group-name" value={groupForm.name} onChange={(e) => setGroupForm({ ...groupForm, name: e.target.value })} required />
                                </div>
                                <div className="form-group">
                                    <Label htmlFor="group-description">Description</Label>
                                    <Input id="group-description" value={groupForm.description} onChange={(e) => setGroupForm({ ...groupForm, description: e.target.value })} />
                                </div>
                            <div className="modal-actions">
                                <Button type="button" variant="outline" onClick={() => setShowGroupModal(false)}>Cancel</Button>
                                <Button type="submit">Create Group</Button>
                            </div>
                        </form>
            </Modal>

            {/* Create Queue Modal */}
            <Modal open={showQueueModal} onClose={() => setShowQueueModal(false)} title="Create Queue">
                        <form onSubmit={handleCreateQueue}>
                                <div className="form-group">
                                    <Label htmlFor="queue-group">Group</Label>
                                    <select
                                        id="queue-group"
                                        className="queue-select queue-select--full"
                                        value={queueForm.groupSlug || selectedGroup || ''}
                                        onChange={(e) => setQueueForm({ ...queueForm, groupSlug: e.target.value })}
                                        required
                                    >
                                        <option value="">Select group</option>
                                        {groups.map(g => <option key={g.id} value={g.slug}>{g.name}</option>)}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <Label htmlFor="queue-name">Name</Label>
                                    <Input id="queue-name" value={queueForm.name} onChange={(e) => setQueueForm({ ...queueForm, name: e.target.value })} required />
                                </div>
                                <div className="form-group">
                                    <Label htmlFor="queue-description">Description</Label>
                                    <Input id="queue-description" value={queueForm.description} onChange={(e) => setQueueForm({ ...queueForm, description: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <Label htmlFor="queue-config">Config (JSON)</Label>
                                    <Textarea id="queue-config" value={queueForm.config} onChange={(e) => setQueueForm({ ...queueForm, config: e.target.value })} rows={4} />
                                </div>
                            <div className="modal-actions">
                                <Button type="button" variant="outline" onClick={() => setShowQueueModal(false)}>Cancel</Button>
                                <Button type="submit">Create Queue</Button>
                            </div>
                        </form>
            </Modal>

            {/* Send Message Modal */}
            <Modal open={!!sendTarget} onClose={() => setSendTarget(null)} title="Send Message">
                        {sendTarget && (
                        <form onSubmit={handleSendMessage}>
                                <div className="queue-send-destination">
                                    <div>
                                        <Label>Group</Label>
                                        <div className="queue-send-readonly">{sendTarget.group_slug}</div>
                                    </div>
                                    <div>
                                        <Label>Queue</Label>
                                        <div className="queue-send-readonly">{sendTarget.slug}</div>
                                    </div>
                                </div>
                                <div className="form-group">
                                    <Label htmlFor="payload">Payload (JSON)</Label>
                                    <Textarea
                                        id="payload"
                                        value={sendForm.payload}
                                        onChange={(e) => setSendForm({ ...sendForm, payload: e.target.value })}
                                        rows={6}
                                        required
                                    />
                                </div>
                                <div className="form-row">
                                    <div className="form-group">
                                        <Label htmlFor="priority">Priority</Label>
                                        <Input id="priority" type="number" value={sendForm.priority} onChange={(e) => setSendForm({ ...sendForm, priority: e.target.value })} />
                                    </div>
                                    <div className="form-group">
                                        <Label htmlFor="delay_ms">Delay (ms)</Label>
                                        <Input id="delay_ms" type="number" value={sendForm.delay_ms} onChange={(e) => setSendForm({ ...sendForm, delay_ms: e.target.value })} />
                                    </div>
                                </div>
                            <div className="modal-actions">
                                <Button type="button" variant="outline" onClick={() => setSendTarget(null)}>Cancel</Button>
                                <Button type="submit"><Send size={14} className="mr-2" /> Send Message</Button>
                            </div>
                        </form>
                        )}
            </Modal>

            <GridFilterDrawer {...chrome.drawerProps} />
        </div>
    );
};

export default QueueOperations;
