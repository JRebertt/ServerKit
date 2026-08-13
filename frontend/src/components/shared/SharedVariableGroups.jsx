import { useState, useEffect, useCallback, useMemo } from 'react';
import { ArrowLeft, Boxes, Plus, Trash2 } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import Modal from '@/components/Modal';
import ResourceListPage from '../layouts/ResourceListPage';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { SearchField, Pill, ServiceTile } from '@/components/ds';

const RESOURCE_TYPES = ['application', 'database', 'service', 'wordpress', 'server'];

// Preset views. "Unattached" is the one that earns its place: a group nothing
// is attached to is a group whose variables reach nothing, which is almost
// always a mistake rather than a choice.
const GROUP_VIEWS = [
    { name: 'All groups', state: { search: '', sorts: [], hiddenKeys: [], columnFilters: null } },
    {
        name: 'Unattached',
        state: {
            search: '',
            sorts: [],
            hiddenKeys: [],
            columnFilters: { match: 'all', rules: [{ id: 'sg1', field: 'attachments', op: 'eq', value: 0 }] },
        },
    },
];

/**
 * Manage shared variable groups for a given scope: create groups, add/remove
 * variables (secrets masked), and attach/detach a group to resources.
 *
 * Two depths on the same surface, matching every other list page: a table of
 * groups, and — once you pick one — a table of that group's variables. It used
 * to be a fixed sidebar of groups beside a detail pane, which meant the group
 * list alone could not be searched, sorted, filtered or saved as a view the way
 * every other list in the panel can.
 *
 * Props:
 *   scopeType   'workspace' | 'project' | 'environment'  (default 'workspace')
 *   scopeId     the scope identifier (string)            (default 'default')
 */
const SharedVariableGroups = ({ scopeType = 'workspace', scopeId = 'default' }) => {
    const toast = useToast();
    const [groups, setGroups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedId, setSelectedId] = useState(null);
    const [detail, setDetail] = useState(null);

    // create-group form
    const [creating, setCreating] = useState(false);
    const [newName, setNewName] = useState('');
    const [newDescription, setNewDescription] = useState('');
    const [search, setSearch] = useState('');

    // add-variable form
    const [varKey, setVarKey] = useState('');
    const [varValue, setVarValue] = useState('');
    const [varSecret, setVarSecret] = useState(false);
    const [varTarget, setVarTarget] = useState('');

    // attach form
    const [attachType, setAttachType] = useState(RESOURCE_TYPES[0]);
    const [attachId, setAttachId] = useState('');

    const loadGroups = useCallback(async () => {
        try {
            setLoading(true);
            const data = await api.listVariableGroups(scopeType, scopeId);
            setGroups(data.groups || []);
        } catch {
            toast.error('Failed to load variable groups');
        } finally {
            setLoading(false);
        }
    }, [scopeType, scopeId, toast]);

    const loadDetail = useCallback(async (groupId) => {
        if (!groupId) { setDetail(null); return; }
        try {
            const data = await api.getVariableGroup(groupId);
            setDetail(data);
        } catch {
            toast.error('Failed to load group');
        }
    }, [toast]);

    useEffect(() => { loadGroups(); }, [loadGroups]);
    useEffect(() => { loadDetail(selectedId); }, [selectedId, loadDetail]);

    async function handleCreateGroup(e) {
        e.preventDefault();
        if (!newName.trim()) return;
        try {
            const group = await api.createVariableGroup({
                scopeType, scopeId, name: newName.trim(),
                description: newDescription.trim() || null,
            });
            toast.success('Group created');
            setNewName('');
            setNewDescription('');
            setCreating(false);
            await loadGroups();
            setSelectedId(group.id);
        } catch (err) {
            toast.error(err.message || 'Failed to create group');
        }
    }

    async function handleDeleteGroup(groupId) {
        if (!confirm('Delete this variable group? Attachments will be removed.')) return;
        try {
            await api.deleteVariableGroup(groupId);
            toast.success('Group deleted');
            if (selectedId === groupId) setSelectedId(null);
            loadGroups();
        } catch (err) {
            toast.error(err.message || 'Failed to delete group');
        }
    }

    async function handleAddVariable(e) {
        e.preventDefault();
        if (!varKey.trim() || !selectedId) return;
        try {
            await api.addGroupVariable(selectedId, {
                key: varKey.trim(), value: varValue, isSecret: varSecret,
                targetService: varTarget.trim() || null,
            });
            setVarKey('');
            setVarValue('');
            setVarSecret(false);
            setVarTarget('');
            loadDetail(selectedId);
            loadGroups();
        } catch (err) {
            toast.error(err.message || 'Failed to add variable');
        }
    }

    async function handleDeleteVariable(variableId) {
        try {
            await api.deleteGroupVariable(selectedId, variableId);
            loadDetail(selectedId);
            loadGroups();
        } catch (err) {
            toast.error(err.message || 'Failed to delete variable');
        }
    }

    async function handleAttach(e) {
        e.preventDefault();
        if (!attachId.trim() || !selectedId) return;
        try {
            await api.attachVariableGroup(selectedId, attachType, attachId.trim());
            toast.success('Group attached');
            setAttachId('');
            loadDetail(selectedId);
            loadGroups();
        } catch (err) {
            toast.error(err.message || 'Failed to attach group');
        }
    }

    async function handleDetach(att) {
        try {
            await api.detachVariableGroup(selectedId, att.resource_type, att.resource_id);
            loadDetail(selectedId);
            loadGroups();
        } catch (err) {
            toast.error(err.message || 'Failed to detach');
        }
    }

    // The top bar follows the depth, like Vaults: create groups at the list,
    // go back and manage one inside it.
    useTopbarActions(() => (detail ? (
        <>
            <Button variant="outline" size="sm" onClick={() => setSelectedId(null)}>
                <ArrowLeft size={15} /> All groups
            </Button>
            <SearchField value={search} onSearch={setSearch} placeholder="Search variables…" />
        </>
    ) : (
        <>
            <Button size="sm" onClick={() => setCreating(true)}>
                <Plus size={15} /> New group
            </Button>
            <SearchField value={search} onSearch={setSearch} placeholder="Search groups…" />
        </>
    )), [detail, search]);

    // A term that matched a group name is not a variable key; clear on depth change.
    useEffect(() => { setSearch(''); }, [selectedId]);

    const groupRows = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return groups;
        return groups.filter((g) => (
            g.name?.toLowerCase().includes(q) || g.description?.toLowerCase().includes(q)
        ));
    }, [groups, search]);

    const variableRows = useMemo(() => {
        const all = detail?.variables || [];
        const q = search.trim().toLowerCase();
        if (!q) return all;
        return all.filter((v) => (
            v.key?.toLowerCase().includes(q) || v.target_service?.toLowerCase().includes(q)
        ));
    }, [detail, search]);

    const groupColumns = useMemo(() => [
        {
            key: 'name',
            header: 'Group',
            sortable: true,
            hideable: false,
            value: (g) => g.name,
            render: (g) => (
                <div className="sk-cell-name">
                    <ServiceTile name={g.name} size={30} className="wp-list__tile" aria-hidden="true" />
                    <span>{g.name}</span>
                </div>
            ),
        },
        {
            key: 'description',
            header: 'Description',
            sortable: true,
            value: (g) => g.description || '',
            render: (g) => g.description || <span className="wp-list__dash">—</span>,
        },
        // `value` sorts and filters; `render` is what the cell shows —
        // DataTable falls back to row[key], and these counts have no such key.
        {
            key: 'variables',
            header: 'Variables',
            type: 'number',
            sortable: true,
            width: 110,
            cellClassName: 'sk-cell-mono',
            value: (g) => g.variable_count ?? 0,
            render: (g) => g.variable_count ?? 0,
        },
        {
            key: 'attachments',
            header: 'Attached',
            type: 'number',
            sortable: true,
            width: 110,
            cellClassName: 'sk-cell-mono',
            value: (g) => g.attachment_count ?? 0,
            render: (g) => g.attachment_count ?? 0,
        },
        {
            key: '__actions',
            header: '',
            sortable: false,
            hideable: false,
            width: 56,
            className: 'text-right',
            render: (g) => (
                <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive"
                    title="Delete group"
                    onClick={(e) => { e.stopPropagation(); handleDeleteGroup(g.id); }}
                >
                    <Trash2 size={14} />
                </Button>
            ),
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
    ], []);

    const variableColumns = useMemo(() => [
        {
            key: 'key',
            header: 'Key',
            sortable: true,
            hideable: false,
            value: (v) => v.key,
            cellClassName: 'sk-cell-mono',
            render: (v) => (
                <span className="shared-vars-table__key">
                    {v.key}
                    {v.is_secret && <Pill kind="amber" dot={false}>secret</Pill>}
                </span>
            ),
        },
        {
            key: 'value',
            header: 'Value',
            sortable: false,
            filterable: false,
            cellClassName: 'sk-cell-mono',
            render: (v) => <span className="shared-vars-table__value">{v.value}</span>,
        },
        {
            key: 'target',
            header: 'Target service',
            sortable: true,
            // A blank target is not missing data — it means every service in the
            // stack, which is a different statement from "unknown".
            value: (v) => v.target_service || '',
            render: (v) => (v.target_service ? (
                <span className="env-target-chip" title={`Applies only to the "${v.target_service}" service`}>
                    &rarr; {v.target_service}
                </span>
            ) : (
                <span className="shared-vars-table__target-all">all services</span>
            )),
        },
        {
            key: '__actions',
            header: '',
            sortable: false,
            hideable: false,
            width: 56,
            className: 'text-right',
            render: (v) => (
                <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive"
                    title="Delete variable"
                    aria-label={`Delete variable ${v.key}`}
                    onClick={(e) => { e.stopPropagation(); handleDeleteVariable(v.id); }}
                >
                    <Trash2 size={14} />
                </Button>
            ),
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
    ], []);

    if (!detail) {
        return (
            <>
                <ResourceListPage
                    className="shared-groups"
                    loading={loading}
                    loadingTitle="Loading variable groups…"
                    storageKey="serverkit-list-variable-groups"
                    viewPageKey="variable-groups"
                    noun="groups"
                    builtinViews={GROUP_VIEWS}
                    totalCount={groups.length}
                    items={groupRows}
                    columns={groupColumns}
                    keyField="id"
                    onRowClick={(g) => setSelectedId(g.id)}
                    emptyIcon={Boxes}
                    emptyTitle="No variable groups yet"
                    emptyDescription="A group is a set of variables you attach to services, databases or servers at once, instead of copying the same values into each."
                    emptyAction={<Button onClick={() => setCreating(true)}><Plus size={16} /> Create your first group</Button>}
                    filteredEmptyIcon={Boxes}
                    filteredEmptyTitle="No groups found"
                    filteredEmptyDescription="Try adjusting your search or filters."
                />

                <Modal open={creating} onClose={() => setCreating(false)} title="New variable group">
                    <form onSubmit={handleCreateGroup}>
                        <p className="sk-modal__subtitle">
                            Variables in this group apply to every resource you attach it to.
                        </p>
                        <div className="projects-form">
                            <div className="projects-form__field">
                                <Label htmlFor="vg-name">Name</Label>
                                <Input
                                    id="vg-name"
                                    autoFocus
                                    value={newName}
                                    onChange={(e) => setNewName(e.target.value)}
                                    placeholder="e.g. shared-database"
                                    required
                                />
                            </div>
                            <div className="projects-form__field">
                                <Label htmlFor="vg-desc">Description (optional)</Label>
                                <Input
                                    id="vg-desc"
                                    value={newDescription}
                                    onChange={(e) => setNewDescription(e.target.value)}
                                    placeholder="What this group is for…"
                                />
                            </div>
                        </div>
                        <div className="modal-actions">
                            <Button type="button" variant="outline" onClick={() => setCreating(false)}>Cancel</Button>
                            <Button type="submit" disabled={!newName.trim()}>Create group</Button>
                        </div>
                    </form>
                </Modal>
            </>
        );
    }

    return (
        <ResourceListPage
            className="shared-groups"
            loading={false}
            storageKey="serverkit-list-group-variables"
            viewPageKey="group-variables"
            noun="variables"
            totalCount={(detail.variables || []).length}
            items={variableRows}
            columns={variableColumns}
            keyField="id"
            emptyIcon={Boxes}
            emptyTitle={`No variables in ${detail.name}`}
            emptyDescription="Add the first key/value pair below — it reaches every resource this group is attached to."
            filteredEmptyIcon={Boxes}
            filteredEmptyTitle="No variables found"
            filteredEmptyDescription="Try adjusting your search or filters."
        >
            <div className="shared-groups__detail">
                            <div className="shared-groups__detail-header">
                                <div>
                                    <h3>{detail.name}</h3>
                                    {detail.description && (
                                        <p className="shared-groups__desc">{detail.description}</p>
                                    )}
                                </div>
                                <Button
                                    variant="destructive"
                                    size="sm"
                                    onClick={() => handleDeleteGroup(detail.id)}
                                >
                                    Delete group
                                </Button>
                            </div>

                            <form className="shared-groups__add-var" onSubmit={handleAddVariable}>
                                <Input
                                    type="text"
                                    value={varKey}
                                    onChange={(e) => setVarKey(e.target.value)}
                                    placeholder="KEY"
                                    className="shared-groups__var-key"
                                />
                                <Input
                                    type={varSecret ? 'password' : 'text'}
                                    value={varValue}
                                    onChange={(e) => setVarValue(e.target.value)}
                                    placeholder="value"
                                    className="shared-groups__var-value"
                                />
                                <Input
                                    type="text"
                                    value={varTarget}
                                    onChange={(e) => setVarTarget(e.target.value)}
                                    placeholder="all services"
                                    className="shared-groups__var-target"
                                    title="Target compose service (leave blank to apply to all services)"
                                />
                                <label className="shared-groups__secret">
                                    <Checkbox checked={varSecret} onCheckedChange={setVarSecret} />
                                    <span>Secret</span>
                                </label>
                                <Button type="submit" size="sm" disabled={!varKey.trim()}>
                                    Add
                                </Button>
                            </form>

                            {/* Attachments */}
                            <h4 className="shared-groups__subhead">Attached resources</h4>
                            {(detail.attachments || []).length === 0 ? (
                                <p className="shared-groups__hint">Not attached to any resource yet.</p>
                            ) : (
                                <ul className="shared-groups__attachments">
                                    {detail.attachments.map((a) => (
                                        <li key={a.id} className="shared-groups__attachment">
                                            <span className="shared-groups__attachment-label">
                                                {a.resource_type}:{a.resource_id}
                                            </span>
                                            <button
                                                type="button"
                                                className="shared-tag__remove"
                                                onClick={() => handleDetach(a)}
                                                title="Detach"
                                                aria-label="Detach group"
                                            >
                                                &times;
                                            </button>
                                        </li>
                                    ))}
                                </ul>
                            )}

                            <form className="shared-groups__attach" onSubmit={handleAttach}>
                                <select
                                    value={attachType}
                                    onChange={(e) => setAttachType(e.target.value)}
                                    className="shared-groups__attach-type"
                                >
                                    {RESOURCE_TYPES.map((t) => (
                                        <option key={t} value={t}>{t}</option>
                                    ))}
                                </select>
                                <Input
                                    type="text"
                                    value={attachId}
                                    onChange={(e) => setAttachId(e.target.value)}
                                    placeholder="resource id"
                                    className="shared-groups__attach-id"
                                />
                                <Button type="submit" size="sm" disabled={!attachId.trim()}>
                                    Attach
                                </Button>
                            </form>
            </div>
        </ResourceListPage>
    );
};

export default SharedVariableGroups;
