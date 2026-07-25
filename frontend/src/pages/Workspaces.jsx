import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import { LayoutGrid, Plus, ChevronRight, Search } from 'lucide-react';
import { Pill, SegControl, ServiceTile } from '@/components/ds';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';

// Matches WorkspaceSwitcher: the active workspace id lives in localStorage.
const ACTIVE_KEY = 'active_workspace_id';

// "since Jun 2026" card meta from the workspace's real created_at.
const formatSince = (iso) => {
    if (!iso) return null;
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
        ? null
        : d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
};

const Workspaces = () => {
    const toast = useToast();
    const navigate = useNavigate();
    const [workspaces, setWorkspaces] = useState([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('all'); // all | active | inactive
    const [search, setSearch] = useState('');
    const [selectedIds, setSelectedIds] = useState(new Set());
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [form, setForm] = useState({ name: '', description: '', max_servers: 0, max_users: 0, primary_color: '#6d7cff' });

    const activeId = localStorage.getItem(ACTIVE_KEY);

    const loadWorkspaces = useCallback(async () => {
        try {
            const data = await api.getWorkspaces();
            setWorkspaces(data.workspaces || []);
        } catch (err) {
            toast.error('Failed to load workspaces');
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => { loadWorkspaces(); }, [loadWorkspaces]);

    useTopbarActions(() => (
        <Button size="sm" onClick={() => setShowCreateModal(true)}>
            <Plus size={16} />
            New Workspace
        </Button>
    ), []);

    const handleCreate = async () => {
        try {
            await api.createWorkspace(form);
            toast.success('Workspace created');
            setShowCreateModal(false);
            setForm({ name: '', description: '', max_servers: 0, max_users: 0, primary_color: '#6d7cff' });
            loadWorkspaces();
        } catch (err) {
            toast.error(err.message);
        }
    };

    if (loading) return <div className="sk-tabgroup__inner workspaces-page"><EmptyState loading loadingVariant="cards" title="Loading workspaces" /></div>;

    const q = search.trim().toLowerCase();
    const shownWorkspaces = workspaces.filter(ws => {
        const matchesStatus = statusFilter === 'all'
            || (statusFilter === 'active' ? ws.status === 'active' : ws.status !== 'active');
        const matchesSearch = q === '' || [ws.name, ws.slug, ws.description]
            .some(v => v && String(v).toLowerCase().includes(q));
        return matchesStatus && matchesSearch;
    });

    const activeCount = workspaces.filter(ws => ws.status === 'active').length;

    return (
        <div className="sk-tabgroup__inner workspaces-page">
            {workspaces.length === 0 ? (
                <EmptyState
                    icon={LayoutGrid}
                    title="No workspaces yet"
                    description="Create one to isolate servers by team or project."
                    action={
                        <Button onClick={() => setShowCreateModal(true)}>
                            New Workspace
                        </Button>
                    }
                />
            ) : (
                <div className="wp-list">
                    <div className="wp-list__toolbar">
                        <SegControl
                            value={statusFilter}
                            onChange={setStatusFilter}
                            options={[
                                { value: 'all', label: 'All', count: workspaces.length },
                                { value: 'active', label: 'Active', count: activeCount },
                                { value: 'inactive', label: 'Inactive', count: workspaces.length - activeCount },
                            ]}
                        />
                        <div className="wp-list__search">
                            <Search size={15} aria-hidden="true" />
                            <input
                                type="text"
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                placeholder="Search workspaces…"
                                aria-label="Search workspaces"
                            />
                        </div>
                    </div>

                    {selectedIds.size > 0 && (
                        <div className="wp-list__bulkbar">
                            <span className="wp-list__bulkcount">{selectedIds.size} selected</span>
                            <div className="wp-list__bulkactions">
                                <Button variant="ghost" size="sm" onClick={() => setSelectedIds(new Set())}>
                                    Clear
                                </Button>
                            </div>
                        </div>
                    )}

                    <div className="wp-list__card">
                        <table className="sk-dtable">
                            <thead>
                                <tr>
                                    <th className="wp-list__ck">
                                        <Checkbox
                                            checked={shownWorkspaces.length > 0 && shownWorkspaces.every(ws => selectedIds.has(ws.id))}
                                            onCheckedChange={(checked) => {
                                                setSelectedIds(checked ? new Set(shownWorkspaces.map(ws => ws.id)) : new Set());
                                            }}
                                            aria-label="Select all workspaces"
                                        />
                                    </th>
                                    <th>Workspace</th>
                                    <th>Slug</th>
                                    <th>Members</th>
                                    <th>Servers</th>
                                    <th>Users</th>
                                    <th>Status</th>
                                    <th className="wp-list__action" />
                                </tr>
                            </thead>
                            <tbody>
                                {shownWorkspaces.map(ws => {
                                    const since = formatSince(ws.created_at);
                                    const isCurrent = activeId === String(ws.id);
                                    return (
                                        <tr
                                            key={ws.id}
                                            className={`is-clickable ${selectedIds.has(ws.id) ? 'is-selected' : ''}`}
                                            onClick={() => navigate(`/workspaces/${ws.id}`)}
                                        >
                                            <td className="wp-list__ck" onClick={e => e.stopPropagation()}>
                                                <Checkbox
                                                    checked={selectedIds.has(ws.id)}
                                                    onCheckedChange={(checked) => {
                                                        setSelectedIds(prev => {
                                                            const next = new Set(prev);
                                                            if (checked) next.add(ws.id);
                                                            else next.delete(ws.id);
                                                            return next;
                                                        });
                                                    }}
                                                    aria-label={`Select ${ws.name || `workspace ${ws.id}`}`}
                                                />
                                            </td>
                                            <td>
                                                <div className="sk-cell-name">
                                                    <ServiceTile
                                                        name={ws.name}
                                                        size={30}
                                                        gradient={ws.primary_color || undefined}
                                                        className="wp-list__tile"
                                                        aria-hidden="true"
                                                    />
                                                    <span>
                                                        <div>{ws.name}</div>
                                                        {ws.description && (
                                                            <div className="sk-cell-sub">{ws.description}</div>
                                                        )}
                                                        {since && !ws.description && (
                                                            <div className="sk-cell-sub">since {since}</div>
                                                        )}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="sk-cell-mono">/{ws.slug}</td>
                                            <td className="sk-cell-mono">{ws.member_count ?? 0}</td>
                                            <td className="sk-cell-mono">{ws.max_servers > 0 ? ws.max_servers : '—'}</td>
                                            <td className="sk-cell-mono">{ws.max_users > 0 ? ws.max_users : '—'}</td>
                                            <td>
                                                {isCurrent ? (
                                                    <Pill kind="green">active</Pill>
                                                ) : (
                                                    <Pill kind={ws.status === 'active' ? 'green' : 'amber'}>
                                                        {ws.status || 'unknown'}
                                                    </Pill>
                                                )}
                                            </td>
                                            <td>
                                                <ChevronRight size={16} className="wp-list__chev" />
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            <Modal
                open={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                title="Create Workspace"
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setShowCreateModal(false)}>Cancel</Button>
                        <Button onClick={handleCreate} disabled={!form.name}>Create</Button>
                    </>
                )}
            >
                <div className="form-group">
                    <label>Name</label>
                    <Input value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="My Team" />
                </div>
                <div className="form-group">
                    <label>Description</label>
                    <Textarea value={form.description} onChange={e => setForm({...form, description: e.target.value})} rows={2} />
                </div>
                <div className="form-row">
                    <div className="form-group">
                        <label>Max Servers (0 = unlimited)</label>
                        <Input type="number" value={form.max_servers} onChange={e => setForm({...form, max_servers: parseInt(e.target.value) || 0})} />
                    </div>
                    <div className="form-group">
                        <label>Max Users (0 = unlimited)</label>
                        <Input type="number" value={form.max_users} onChange={e => setForm({...form, max_users: parseInt(e.target.value) || 0})} />
                    </div>
                </div>
                <div className="form-group">
                    <label>Brand Color</label>
                    <input
                        type="color"
                        className="workspace-color-input"
                        value={form.primary_color}
                        onChange={e => setForm({...form, primary_color: e.target.value})}
                        aria-label="Workspace brand color"
                    />
                    <span className="form-hint">Recolors the panel for anyone viewing this workspace. Leave the default for no custom branding.</span>
                </div>
            </Modal>
        </div>
    );
};

export default Workspaces;
