import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import Modal from '@/components/Modal';
import ResourceListPage from '../components/layouts/ResourceListPage';
import { LayoutGrid, Plus, ChevronRight } from 'lucide-react';
import { Pill, ServiceTile, SearchField } from '@/components/ds';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import useFocusParam from '@/hooks/useFocusParam';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

// Matches WorkspaceSwitcher: the active workspace id lives in localStorage.
const ACTIVE_KEY = 'active_workspace_id';

// Preset views. Only three: `servers` and `users` are quota CEILINGS, not
// usage, so there is no column to express "near capacity" against.
const WORKSPACE_VIEWS = [
    { name: 'Active', state: { filter: 'active', search: '', sorts: [], hiddenKeys: [] } },
    { name: 'Inactive', state: { filter: 'inactive', search: '', sorts: [], hiddenKeys: [] } },
    {
        name: 'Most members',
        state: {
            filter: 'all', search: '', hiddenKeys: [],
            sorts: [{ key: 'members', direction: 'desc' }],
        },
    },
    {
        // Created and then never staffed — candidates to archive.
        name: 'Empty workspaces',
        state: {
            filter: 'all', search: '', hiddenKeys: ['servers', 'users'], groupBy: null,
            sorts: [{ key: 'name', direction: 'asc' }],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'ew1', field: 'members', op: 'eq', value: 0 }],
            },
        },
    },
    {
        // Deactivated but people are still attached — access that outlived the workspace.
        name: 'Archived but still staffed',
        state: {
            filter: 'inactive', search: '', hiddenKeys: ['servers', 'users'], groupBy: null,
            sorts: [{ key: 'members', direction: 'desc' }],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'as1', field: 'members', op: 'gt', value: 0 }],
            },
        },
    },
];

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
    // Quick-create deep link: /workspaces?focus=create:workspace opens the modal.
    useFocusParam('create', () => setShowCreateModal(true));
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
        <>
            <Button size="sm" onClick={() => setShowCreateModal(true)}>
                <Plus size={16} />
                New Workspace
            </Button>
            <SearchField
                value={search}
                onSearch={setSearch}
                placeholder="Search workspaces…"
            />
        </>
    ), [search]);

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

    const q = search.trim().toLowerCase();
    const shownWorkspaces = workspaces.filter(ws => {
        const matchesStatus = statusFilter === 'all'
            || (statusFilter === 'active' ? ws.status === 'active' : ws.status !== 'active');
        const matchesSearch = q === '' || [ws.name, ws.slug, ws.description]
            .some(v => v && String(v).toLowerCase().includes(q));
        return matchesStatus && matchesSearch;
    });

    const activeCount = workspaces.filter(ws => ws.status === 'active').length;

    const toggleOne = (id, checked) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (checked) next.add(id);
            else next.delete(id);
            return next;
        });
    };

    // DataTable columns. Interactive cells stop click propagation so they don't
    // trigger the row's navigate.
    const columns = [
        {
            key: 'name',
            header: 'Workspace',
            sortable: true,
            hideable: false,
            render: (ws) => {
                const since = formatSince(ws.created_at);
                return (
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
                            {ws.description && <div className="sk-cell-sub">{ws.description}</div>}
                            {since && !ws.description && <div className="sk-cell-sub">since {since}</div>}
                        </span>
                    </div>
                );
            },
        },
        { key: 'slug', header: 'Slug', sortable: true, cellClassName: 'sk-cell-mono', render: (ws) => `/${ws.slug}` },
        // Numeric sorts: unlimited (0/unset) sorts last.
        { key: 'members', header: 'Members', sortable: true, sortValue: (ws) => ws.member_count ?? null, cellClassName: 'sk-cell-mono', render: (ws) => ws.member_count ?? 0 },
        { key: 'servers', header: 'Servers', sortable: true, sortValue: (ws) => (ws.max_servers > 0 ? ws.max_servers : null), cellClassName: 'sk-cell-mono', render: (ws) => (ws.max_servers > 0 ? ws.max_servers : '—') },
        { key: 'users', header: 'Users', sortable: true, sortValue: (ws) => (ws.max_users > 0 ? ws.max_users : null), cellClassName: 'sk-cell-mono', render: (ws) => (ws.max_users > 0 ? ws.max_users : '—') },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            // Matches the pill: the active workspace (and active status) first.
            sortValue: (ws) => (activeId === String(ws.id) || ws.status === 'active' ? 0 : 1),
            groupable: true,
            groupValue: (ws) => ws.status,
            groupLabel: (value) => (value ? value.charAt(0).toUpperCase() + value.slice(1) : 'None'),
            render: (ws) => (
                activeId === String(ws.id)
                    ? <Pill kind="green">active</Pill>
                    : <Pill kind={ws.status === 'active' ? 'green' : 'amber'}>{ws.status || 'unknown'}</Pill>
            ),
        },
        {
            key: '__chev',
            header: '',
            sortable: false,
            hideable: false,
            className: 'wp-list__action',
            render: () => <ChevronRight size={16} className="wp-list__chev" />,
        },
    ];

    return (
        <ResourceListPage
            className="workspaces-page"
            loading={loading}
            loadingTitle="Loading workspaces"
            storageKey="serverkit-list-workspaces"
            viewPageKey="workspaces"
            noun="workspaces"
            builtinViews={WORKSPACE_VIEWS}
            totalCount={workspaces.length}
            items={shownWorkspaces}
            columns={columns}
            keyField="id"
            onRowClick={(ws) => navigate(`/workspaces/${ws.id}`)}
            selectable
            selectedIds={selectedIds}
            onToggleSelect={toggleOne}
            onSelectAll={(checked) => setSelectedIds(checked ? new Set(shownWorkspaces.map(ws => ws.id)) : new Set())}
            filters={[
                { value: 'all', label: 'All', count: workspaces.length },
                { value: 'active', label: 'Active', count: activeCount },
                { value: 'inactive', label: 'Inactive', count: workspaces.length - activeCount },
            ]}
            activeFilter={statusFilter}
            onFilterChange={setStatusFilter}
            searchTerm={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search workspaces…"
            searchInTopbar
            selectedCount={selectedIds.size}
            onClearSelection={() => setSelectedIds(new Set())}
            emptyIcon={LayoutGrid}
            emptyTitle="No workspaces yet"
            emptyDescription="Create one to isolate servers by team or project."
            emptyAction={
                <Button onClick={() => setShowCreateModal(true)}>
                    New Workspace
                </Button>
            }
            filteredEmptyIcon={LayoutGrid}
            filteredEmptyTitle="No workspaces found"
            filteredEmptyDescription="Try adjusting your search or filter."
        >

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
        </ResourceListPage>
    );
};

export default Workspaces;
