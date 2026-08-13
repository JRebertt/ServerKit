import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Copy, Download, Eye, EyeOff, History, Pencil, Plus, Trash2, Upload, Variable,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import Modal from './Modal';
import EmptyState from './EmptyState';
import { DataTable, DataTableFooter, ListToolbar, SearchField } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';

// What a masked value renders as. Unchanged from the list this table replaces:
// every env var is stored as a secret, so every value is dots until the row's
// eye (or Show All) reveals it.
const MASK = '••••••••••••';

// What the Description and Applies-to cells show when the row carries neither.
// They have to be real values, not '': `ruleIsArmed` drops any rule whose value
// is empty, so "description is ''" would filter nothing at all — and the
// Undocumented view below is exactly that rule.
const NO_DESCRIPTION = '—';
const ALL_SERVICES = 'All services';

const BY_KEY = [{ key: 'key', direction: 'asc' }];
const NO_RULES = { match: 'all', rules: [] };

// Built-in saved views. Scope is deliberately not one of them: it only exists
// on compose apps, and the Applies-to column's own menu already offers the
// per-service pick-list with live counts wherever it applies.
const ENV_VIEWS = [
    {
        // Every variable the container will see, in the order you would read a
        // .env file. The landing view, and the one that says "nothing is
        // filtered".
        name: 'All variables',
        state: { sorts: BY_KEY, hiddenKeys: [], columnFilters: NO_RULES },
    },
    {
        // A hygiene worklist rather than a slice: a variable nobody described
        // is a variable nobody can safely delete, and it is the one most likely
        // to outlive whoever added it. Empty on a fully documented app, which
        // is exactly the answer it exists to give.
        name: 'Undocumented',
        state: {
            sorts: BY_KEY,
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'env1', field: 'description', op: 'is', value: NO_DESCRIPTION }],
            },
        },
    },
];

const EnvironmentVariables = ({ appId }) => {
    const toast = useToast();
    const [envVars, setEnvVars] = useState([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    // Form state (add modal). Env vars are always stored as secrets — there is
    // no "make this one public" choice, so no is_secret toggle here.
    const [newKey, setNewKey] = useState('');
    const [newValue, setNewValue] = useState('');
    const [newDescription, setNewDescription] = useState('');
    const [newTargetService, setNewTargetService] = useState('');

    // Compose service targeting (empty list => single-container app, hide selector)
    const [composeServices, setComposeServices] = useState([]);

    // UI state
    const [showValues, setShowValues] = useState({});
    const [allVisible, setAllVisible] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [editValue, setEditValue] = useState('');
    const [editTargetService, setEditTargetService] = useState('');
    const [showAddModal, setShowAddModal] = useState(false);
    const [showImportModal, setShowImportModal] = useState(false);
    const [showHistoryModal, setShowHistoryModal] = useState(false);
    const [importContent, setImportContent] = useState('');
    const [importOverwrite, setImportOverwrite] = useState(true);
    const [history, setHistory] = useState([]);
    const [search, setSearch] = useState('');

    const { sorts, setSorts } = useTableSort({
        defaultSorts: BY_KEY,
        storageKey: 'serverkit-table-svc-env-sort',
    });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({
        storageKey: 'serverkit-table-svc-env-cols',
    });

    const fileInputRef = useRef(null);

    useEffect(() => {
        loadEnvVars();
        loadComposeServices();
    }, [appId]);

    async function loadComposeServices() {
        try {
            const data = await api.getComposeServices(appId);
            setComposeServices(data.services || []);
        } catch {
            // Non-compose apps or errors: keep single-container UX (no selector).
            setComposeServices([]);
        }
    }

    async function loadEnvVars() {
        try {
            setLoading(true);
            const data = await api.getEnvVars(appId);
            setEnvVars(data.env_vars || []);
        } catch (err) {
            toast.error('Failed to load environment variables');
            console.error('Failed to load env vars:', err);
        } finally {
            setLoading(false);
        }
    }

    function openAddModal() {
        setNewKey('');
        setNewValue('');
        setNewDescription('');
        setNewTargetService('');
        setShowAddModal(true);
    }

    async function handleAdd(e) {
        e.preventDefault();
        if (!newKey.trim()) {
            toast.error('Key is required');
            return;
        }

        setSaving(true);
        try {
            // Always stored as a secret — env vars are treated as sensitive by
            // default, so we never ask the user to opt out of masking.
            await api.createEnvVar(appId, newKey.trim(), newValue, true, newDescription || null, newTargetService || null);
            toast.success('Environment variable added');
            setNewKey('');
            setNewValue('');
            setNewDescription('');
            setNewTargetService('');
            setShowAddModal(false);
            loadEnvVars();
        } catch (err) {
            toast.error(err.message || 'Failed to add environment variable');
        } finally {
            setSaving(false);
        }
    }

    async function handleUpdate(key) {
        if (editingId === null) return;

        setSaving(true);
        try {
            const payload = { value: editValue };
            // Only thread target_service through for compose apps. Empty string
            // clears the var back to all-services; a name targets one service.
            if (composeServices.length > 0) {
                payload.target_service = editTargetService || '';
            }
            await api.updateEnvVar(appId, key, payload);
            toast.success('Environment variable updated');
            setEditingId(null);
            setEditValue('');
            setEditTargetService('');
            loadEnvVars();
        } catch (err) {
            toast.error(err.message || 'Failed to update environment variable');
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete(key) {
        if (!confirm(`Delete environment variable "${key}"?`)) return;

        try {
            await api.deleteEnvVar(appId, key);
            toast.success('Environment variable deleted');
            loadEnvVars();
        } catch (err) {
            toast.error(err.message || 'Failed to delete environment variable');
        }
    }

    function toggleShowValue(id) {
        setShowValues(prev => {
            const next = { ...prev, [id]: !prev[id] };
            const allShown = envVars.every(ev => next[ev.id]);
            setAllVisible(allShown);
            return next;
        });
    }

    function toggleShowAll() {
        if (allVisible) {
            setShowValues({});
            setAllVisible(false);
        } else {
            const all = {};
            envVars.forEach(ev => { all[ev.id] = true; });
            setShowValues(all);
            setAllVisible(true);
        }
    }

    function startEditing(envVar) {
        setEditingId(envVar.id);
        setEditValue(envVar.value);
        setEditTargetService(envVar.target_service || '');
    }

    function cancelEditing() {
        setEditingId(null);
        setEditValue('');
        setEditTargetService('');
    }

    async function handleExport(includeSecrets = true) {
        try {
            const data = await api.exportEnvFile(appId, includeSecrets);
            const blob = new Blob([data.content], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = data.filename || 'app.env';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            toast.success('Environment file exported');
        } catch (err) {
            toast.error('Failed to export');
        }
    }

    async function handleImport() {
        if (!importContent.trim()) {
            toast.error('Please paste .env content');
            return;
        }

        setSaving(true);
        try {
            const result = await api.importEnvFile(appId, importContent, importOverwrite);
            toast.success(`${result.count} variables imported`);
            setShowImportModal(false);
            setImportContent('');
            loadEnvVars();
        } catch (err) {
            toast.error(err.message || 'Failed to import');
        } finally {
            setSaving(false);
        }
    }

    function handleFileUpload(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            setImportContent(event.target.result);
        };
        reader.readAsText(file);
    }

    async function handleShowHistory() {
        try {
            const data = await api.getEnvVarHistory(appId);
            setHistory(data.history || []);
            setShowHistoryModal(true);
        } catch (err) {
            toast.error('Failed to load history');
        }
    }

    async function handleClearAll() {
        if (!confirm('Delete ALL environment variables? This cannot be undone.')) return;
        if (!confirm('Are you absolutely sure?')) return;

        try {
            await api.clearEnvVars(appId);
            toast.success('All environment variables cleared');
            loadEnvVars();
        } catch (err) {
            toast.error('Failed to clear');
        }
    }

    function copyToClipboard(value) {
        navigator.clipboard.writeText(value);
        toast.success('Copied to clipboard');
    }

    // The search box narrows the rows before any column rule sees them, over
    // the two fields you actually remember: the key and what someone wrote it
    // was for.
    const filteredEnvVars = useMemo(() => {
        const needle = search.trim().toLowerCase();
        if (!needle) return envVars;
        return envVars.filter((ev) => (
            ev.key.toLowerCase().includes(needle)
            || (ev.description && ev.description.toLowerCase().includes(needle))
        ));
    }, [envVars, search]);

    // Declared above the loading guard: the chrome below is a hook, so it
    // cannot sit behind an early return.
    const columns = [
        {
            key: 'key',
            header: 'Key',
            sortable: true,
            hideable: false,
            // An identifier you type a fragment of, never pick from a list.
            type: 'text',
            value: (ev) => ev.key || '',
            sortValue: (ev) => ev.key || '',
            cellClassName: 'sk-cell-name env-cell-key',
            render: (ev) => ev.key,
        },
        {
            key: 'value',
            header: 'Value',
            sortable: false,
            // Neither sortable nor filterable, and `value` answers with the
            // mask rather than the secret: those three accessors also feed the
            // "⋮" export and the column menu's pick-list, so a real accessor
            // here would make the grid the one path that hands out a value the
            // rest of the tab keeps behind an eye toggle.
            filterable: false,
            value: () => MASK,
            cellClassName: 'env-cell-value',
            render: (ev) => (editingId === ev.id ? (
                <div className="env-edit-row">
                    <Input
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        autoFocus
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') handleUpdate(ev.key);
                            if (e.key === 'Escape') cancelEditing();
                        }}
                    />
                    {composeServices.length > 0 && (
                        <select
                            className="env-target-select__control"
                            value={editTargetService}
                            onChange={(e) => setEditTargetService(e.target.value)}
                            title="Inject this variable into a single compose service"
                        >
                            <option value="">All services</option>
                            {composeServices.map((svc) => (
                                <option key={svc} value={svc}>{svc}</option>
                            ))}
                        </select>
                    )}
                    <Button size="sm" onClick={() => handleUpdate(ev.key)}>Save</Button>
                    <Button variant="outline" size="sm" onClick={cancelEditing}>Cancel</Button>
                </div>
            ) : (showValues[ev.id] ? ev.value : MASK)),
        },
        // Only compose apps can target a single service, so on a single-service
        // app the column would say "All services" on every row and answer
        // nothing. But `composeServices` comes from the app's CURRENT compose
        // file, and a variable can still carry a `target_service` from before a
        // service was renamed or removed — hiding the column outright is how a
        // variable that applies to exactly one service silently looks like it
        // applies to all of them. Show it whenever either source says there is
        // a distinction to draw.
        ...(composeServices.length > 0 || envVars.some((ev) => ev.target_service) ? [{
            key: 'scope',
            header: 'Applies to',
            sortable: true,
            // Declared, not inferred: a compose app with two services and three
            // variables is over the enum cardinality ratio and would degrade to
            // free text, turning the per-service pick-list into a typed
            // fragment.
            type: 'enum',
            value: (ev) => ev.target_service || ALL_SERVICES,
            sortValue: (ev) => ev.target_service || ALL_SERVICES,
            render: (ev) => (ev.target_service ? (
                <span
                    className="env-target-chip"
                    title={`Applies only to the "${ev.target_service}" service`}
                >
                    &rarr; {ev.target_service}
                </span>
            ) : <span className="env-muted">{ALL_SERVICES}</span>),
        }] : []),
        {
            key: 'description',
            header: 'Description',
            sortable: true,
            // Text, never enum: on an app where nothing is documented the
            // inference would see one repeated dash and offer a checklist.
            // `value` substitutes the dash the cell shows so the undocumented
            // rows are addressable by the view below; `sortValue` stays '' so
            // they collate as empty rather than as whatever "—" sorts under.
            type: 'text',
            value: (ev) => ev.description || NO_DESCRIPTION,
            sortValue: (ev) => ev.description || '',
            render: (ev) => ev.description || <span className="env-muted">{NO_DESCRIPTION}</span>,
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            className: 'actions-cell',
            cellClassName: 'actions-cell',
            render: (ev) => (
                <>
                    <button
                        type="button"
                        className="btn-icon"
                        onClick={() => toggleShowValue(ev.id)}
                        title={showValues[ev.id] ? 'Hide value' : 'Show value'}
                    >
                        {showValues[ev.id] ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                    <button
                        type="button"
                        className="btn-icon"
                        onClick={() => copyToClipboard(ev.value)}
                        title="Copy value"
                    >
                        <Copy size={16} />
                    </button>
                    <button
                        type="button"
                        className="btn-icon"
                        onClick={() => startEditing(ev)}
                        title="Edit"
                    >
                        <Pencil size={16} />
                    </button>
                    <button
                        type="button"
                        className="btn-icon btn-danger"
                        onClick={() => handleDelete(ev.key)}
                        title="Delete"
                    >
                        <Trash2 size={16} />
                    </button>
                </>
            ),
        },
    ];

    // The page-private half of a saved view: the search box narrows the rows
    // before any column rule runs, so a view has to carry it.
    const pageState = useMemo(() => ({ search }), [search]);
    const applyPage = useCallback((saved) => {
        if (saved.search !== undefined) setSearch(saved.search);
    }, []);

    // Scoped to this tab, and namespaced: /services/:id renders one tab at a
    // time but the Events tab on the same ROUTE hosts a chrome of its own, so
    // unscoped the two would read and write the same ?view=/?sort= and each
    // would arrive as the other's.
    const chrome = useTableChrome({
        columns,
        rows: filteredEnvVars,
        viewPageKey: 'servicedetail-environment',
        urlScope: 'env',
        builtinViews: ENV_VIEWS,
        noun: 'variables',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        pageState,
        applyPage,
    });

    if (loading) {
        return <EmptyState loading loadingVariant="table" title="Loading environment variables..." />;
    }

    return (
        <div className="env-vars-container">
            <p className="hint">
                Environment variables are encrypted at rest and masked by default. Changes require an app restart to take effect.
            </p>

            {envVars.length === 0 ? (
                <EmptyState
                    icon={Variable}
                    title="No environment variables"
                    description="Add one here, or import an existing .env file."
                    action={(
                        <div className="env-empty-actions">
                            <Button onClick={openAddModal}>
                                <Plus size={15} />
                                Add Variable
                            </Button>
                            <Button variant="outline" onClick={() => setShowImportModal(true)}>
                                <Upload size={14} />
                                Import
                            </Button>
                        </div>
                    )}
                />
            ) : (
                <>
                    {/* One row of chrome: the view name is this tab's heading and
                        the search, the filter and the "⋮" ride the same line.
                        ServiceDetail owns the page top bar, so the chrome stays
                        inline here rather than being hoisted (see
                        useTopbarChrome). No count on it — the footer reports
                        that, under the rows it is counting. */}
                    <GridViewPicker
                        views={chrome.views}
                        label="variables"
                        onCreate={chrome.createView}
                        actions={(
                            <>
                                <SearchField
                                    value={search}
                                    onSearch={setSearch}
                                    placeholder="Search keys or descriptions…"
                                />
                                <GridFilterButton
                                    count={chrome.filterCount}
                                    onClick={() => chrome.setDrawerOpen(true)}
                                />
                                <GridToolsMenu {...chrome.toolsProps} onRefresh={loadEnvVars} />
                            </>
                        )}
                    />

                    {/* What acts on the .env file itself, rather than on what you
                        are looking at. Refresh is gone from it — it is in the "⋮". */}
                    <ListToolbar>
                        <Button size="sm" onClick={openAddModal}>
                            <Plus size={15} />
                            Add Variable
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={toggleShowAll}
                            title={allVisible ? 'Hide all values' : 'Show all values'}
                        >
                            {allVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                            {allVisible ? 'Hide All' : 'Show All'}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setShowImportModal(true)}>
                            <Upload size={14} />
                            Import
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => handleExport(true)}>
                            <Download size={14} />
                            Export
                        </Button>
                        <Button variant="outline" size="sm" onClick={handleShowHistory}>
                            <History size={14} />
                            History
                        </Button>
                        <Button variant="outline" size="sm" className="env-clear-btn" onClick={handleClearAll}>
                            <Trash2 size={14} />
                            Clear All
                        </Button>
                    </ListToolbar>

                    <GridChips {...chrome.chipProps} />

                    <DataTable
                        columns={chrome.columns}
                        data={filteredEnvVars}
                        keyField="id"
                        sorts={sorts}
                        onSortsChange={setSorts}
                        {...chrome.tableProps}
                        tableClassName="data-table"
                        emptyTitle="No variables match your search."
                        emptyMessage=""
                        footer={(
                            <DataTableFooter
                                // DataTable applies the column rules itself, so
                                // the shown count comes from the chrome —
                                // `envVars` is only ever the whole file.
                                shown={chrome.shownCount}
                                total={envVars.length}
                                noun="variable"
                            />
                        )}
                    />
                </>
            )}

            <GridFilterDrawer {...chrome.drawerProps} />

            {/* Add Variable Modal */}
            <Modal open={showAddModal} onClose={() => setShowAddModal(false)} title="Add Environment Variable">
                <form onSubmit={handleAdd}>
                    <div className="form-group">
                        <Label>Key</Label>
                        <Input
                            type="text"
                            value={newKey}
                            onChange={(e) => setNewKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ''))}
                            placeholder="KEY_NAME"
                            className="env-key-input"
                            autoFocus
                        />
                    </div>
                    <div className="form-group">
                        <Label>Value</Label>
                        <Input
                            type="text"
                            value={newValue}
                            onChange={(e) => setNewValue(e.target.value)}
                            placeholder="value"
                        />
                    </div>
                    <div className="form-group">
                        <Label>Description <span className="env-optional">(optional)</span></Label>
                        <Input
                            type="text"
                            value={newDescription}
                            onChange={(e) => setNewDescription(e.target.value)}
                            placeholder="What is this variable for?"
                        />
                    </div>
                    {composeServices.length > 0 && (
                        <div className="form-group">
                            <Label>Applies to</Label>
                            <select
                                className="env-target-select__control"
                                value={newTargetService}
                                onChange={(e) => setNewTargetService(e.target.value)}
                            >
                                <option value="">All services</option>
                                {composeServices.map((svc) => (
                                    <option key={svc} value={svc}>{svc}</option>
                                ))}
                            </select>
                        </div>
                    )}
                    <p className="hint env-modal-hint">
                        Stored encrypted and masked by default. Reveal it any time with the eye icon.
                    </p>
                    <div className="modal-footer">
                        <Button type="button" variant="outline" onClick={() => setShowAddModal(false)}>
                            Cancel
                        </Button>
                        <Button type="submit" disabled={saving}>
                            {saving ? 'Adding...' : 'Add Variable'}
                        </Button>
                    </div>
                </form>
            </Modal>

            {/* Import Modal */}
            <Modal open={showImportModal} onClose={() => setShowImportModal(false)} title="Import Environment Variables">
                <p className="hint">Paste your .env file content below or upload a file.</p>

                <div className="import-file-upload">
                    <input
                        type="file"
                        ref={fileInputRef}
                        accept=".env,.txt"
                        onChange={handleFileUpload}
                        style={{ display: 'none' }}
                    />
                    <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
                        Choose File
                    </Button>
                </div>

                <Textarea
                    value={importContent}
                    onChange={(e) => setImportContent(e.target.value)}
                    placeholder={"DATABASE_URL=postgres://...\nAPI_KEY=your-api-key\nDEBUG=false"}
                    rows={10}
                    className="import-textarea"
                />

                <label className="checkbox-label">
                    <Checkbox
                        checked={importOverwrite}
                        onCheckedChange={setImportOverwrite}
                    />
                    <span>Overwrite existing variables with same keys</span>
                </label>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowImportModal(false)}>
                        Cancel
                    </Button>
                    <Button onClick={handleImport} disabled={saving}>
                        {saving ? 'Importing...' : 'Import'}
                    </Button>
                </div>
            </Modal>

            {/* History Modal */}
            <Modal open={showHistoryModal} onClose={() => setShowHistoryModal(false)} title="Change History" size="lg">
                {history.length === 0 ? (
                    <p className="hint">No changes recorded yet.</p>
                ) : (
                    <DataTable
                        columns={[
                            {
                                key: 'key',
                                header: 'Key',
                                sortable: true,
                                hideable: false,
                                sortValue: (h) => h.key || '',
                                cellClassName: 'mono',
                                render: (h) => h.key,
                            },
                            {
                                key: 'action',
                                header: 'Action',
                                sortable: true,
                                sortValue: (h) => h.action || '',
                                render: (h) => (
                                    <Badge variant={h.action === 'created' ? 'success' : h.action === 'deleted' ? 'destructive' : 'warning'}>
                                        {h.action}
                                    </Badge>
                                ),
                            },
                            {
                                key: 'changed_at',
                                header: 'Changed At',
                                sortable: true,
                                sortValue: (h) => new Date(h.changed_at).getTime(),
                                render: (h) => new Date(h.changed_at).toLocaleString(),
                            },
                        ]}
                        data={history.map((h, idx) => ({ ...h, __idx: idx }))}
                        keyField="__idx"
                        storageKey="serverkit-table-env-history"
                        tableClassName="table"
                        footer={(
                            <DataTableFooter
                                shown={history.length}
                                total={history.length}
                                noun="change"
                            />
                        )}
                    />
                )}
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowHistoryModal(false)}>
                        Close
                    </Button>
                </div>
            </Modal>
        </div>
    );
};

export default EnvironmentVariables;
