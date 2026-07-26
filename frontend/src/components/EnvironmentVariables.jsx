import { useState, useEffect, useRef } from 'react';
import { Plus } from 'lucide-react';
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
    const [filter, setFilter] = useState('');

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

    // Filter env vars
    const filteredEnvVars = filter
        ? envVars.filter(ev =>
            ev.key.toLowerCase().includes(filter.toLowerCase()) ||
            (ev.description && ev.description.toLowerCase().includes(filter.toLowerCase()))
          )
        : envVars;

    if (loading) {
        return <EmptyState loading loadingVariant="form" title="Loading environment variables..." />;
    }

    return (
        <div className="env-vars-container">
            <div className="section-header">
                <h3>Environment Variables</h3>
                <div className="header-actions">
                    <Button size="sm" onClick={openAddModal}>
                        <Plus size={15} />
                        Add Variable
                    </Button>
                    {envVars.length > 0 && (
                        <Button variant="outline" size="sm" onClick={toggleShowAll} title={allVisible ? 'Hide all values' : 'Show all values'}>
                            {allVisible ? (
                                <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                                    <line x1="1" y1="1" x2="23" y2="23"/>
                                </svg>
                            ) : (
                                <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                                    <circle cx="12" cy="12" r="3"/>
                                </svg>
                            )}
                            {allVisible ? 'Hide All' : 'Show All'}
                        </Button>
                    )}
                    <Button variant="outline" size="sm" onClick={() => setShowImportModal(true)}>
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
                        </svg>
                        Import
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleExport(true)}>
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                        </svg>
                        Export
                    </Button>
                    <Button variant="outline" size="sm" onClick={handleShowHistory}>
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                            <circle cx="12" cy="12" r="10"/>
                            <polyline points="12 6 12 12 16 14"/>
                        </svg>
                        History
                    </Button>
                </div>
            </div>

            <p className="hint">
                Environment variables are encrypted at rest and masked by default. Changes require an app restart to take effect.
            </p>

            {/* Variables — bordered panel with a titled head + count */}
            <section className="env-panel">
                <div className="env-panel__head">
                    <span className="env-panel__title">
                        Variables
                        {envVars.length > 0 && (
                            <span className="env-panel__count">{envVars.length}</span>
                        )}
                    </span>
                    {envVars.length > 5 && (
                        <div className="env-panel__filter">
                            <Input
                                type="text"
                                value={filter}
                                onChange={(e) => setFilter(e.target.value)}
                                placeholder="Filter variables..."
                            />
                            {filter && (
                                <button type="button" className="filter-clear" onClick={() => setFilter('')}>&times;</button>
                            )}
                        </div>
                    )}
                </div>
                <div className="env-panel__body">
                    {filteredEnvVars.length === 0 ? (
                        <div className="env-empty">
                            <p>{filter ? 'No matching variables' : 'No environment variables defined yet'}</p>
                            {!filter && (
                                <Button size="sm" onClick={openAddModal}>
                                    <Plus size={15} />
                                    Add Variable
                                </Button>
                            )}
                        </div>
                    ) : (
                        <div className="env-list">
                            {filteredEnvVars.map(envVar => (
                                <div key={envVar.id} className="env-item">
                                    <div className="env-item-header">
                                        <span className="env-key">
                                            {envVar.key}
                                            {envVar.target_service && (
                                                <span
                                                    className="env-target-chip"
                                                    title={`Applies only to the "${envVar.target_service}" service`}
                                                >
                                                    &rarr; {envVar.target_service}
                                                </span>
                                            )}
                                        </span>
                                        <div className="env-item-actions">
                                            <button type="button"
                                                className="btn-icon"
                                                onClick={() => toggleShowValue(envVar.id)}
                                                title={showValues[envVar.id] ? 'Hide value' : 'Show value'}
                                            >
                                                {showValues[envVar.id] ? (
                                                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                                                        <line x1="1" y1="1" x2="23" y2="23"/>
                                                    </svg>
                                                ) : (
                                                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                                                        <circle cx="12" cy="12" r="3"/>
                                                    </svg>
                                                )}
                                            </button>
                                            <button type="button"
                                                className="btn-icon"
                                                onClick={() => copyToClipboard(envVar.value)}
                                                title="Copy value"
                                            >
                                                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                                                </svg>
                                            </button>
                                            <button type="button"
                                                className="btn-icon"
                                                onClick={() => startEditing(envVar)}
                                                title="Edit"
                                            >
                                                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                                                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                                                </svg>
                                            </button>
                                            <button type="button"
                                                className="btn-icon btn-danger"
                                                onClick={() => handleDelete(envVar.key)}
                                                title="Delete"
                                            >
                                                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                                    <polyline points="3 6 5 6 21 6"/>
                                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                                                </svg>
                                            </button>
                                        </div>
                                    </div>

                                    {editingId === envVar.id ? (
                                        <div className="env-edit-row">
                                            <Input
                                                type="text"
                                                value={editValue}
                                                onChange={(e) => setEditValue(e.target.value)}
                                                autoFocus
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') handleUpdate(envVar.key);
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
                                            <Button size="sm" onClick={() => handleUpdate(envVar.key)}>
                                                Save
                                            </Button>
                                            <Button variant="outline" size="sm" onClick={cancelEditing}>
                                                Cancel
                                            </Button>
                                        </div>
                                    ) : (
                                        <div className="env-value">
                                            {showValues[envVar.id] ? envVar.value : '••••••••••••'}
                                        </div>
                                    )}

                                    {envVar.description && (
                                        <div className="env-description">{envVar.description}</div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Footer actions */}
                    {envVars.length > 0 && (
                        <div className="env-footer">
                            <Button variant="outline" size="sm" className="env-clear-btn" onClick={handleClearAll}>
                                <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                                    <polyline points="3 6 5 6 21 6"/>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                                </svg>
                                Clear All
                            </Button>
                        </div>
                    )}
                </div>
            </section>

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
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Key</th>
                                <th>Action</th>
                                <th>Changed At</th>
                            </tr>
                        </thead>
                        <tbody>
                            {history.map((h, idx) => (
                                <tr key={idx}>
                                    <td className="mono">{h.key}</td>
                                    <td>
                                        <Badge variant={h.action === 'created' ? 'success' : h.action === 'deleted' ? 'destructive' : 'warning'}>
                                            {h.action}
                                        </Badge>
                                    </td>
                                    <td>{new Date(h.changed_at).toLocaleString()}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
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
