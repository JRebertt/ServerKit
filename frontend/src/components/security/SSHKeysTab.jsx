import { useState, useEffect, useMemo } from 'react';
import { KeyRound } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '@/hooks/useConfirm';
import EmptyState from '@/components/EmptyState';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { DataTable, DataTableFooter, ListToolbar } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer, applyFilters,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';

// What the Comment cell renders when a key carries none. It has to be a real
// value, not '': `ruleIsArmed` drops any rule whose value is empty, so
// "comment is ''" would silently filter nothing at all. Filtering on the same
// dash the cell shows keeps the rule and the row telling the same story.
const NO_COMMENT = '—';

// The modern default. Everything else in authorized_keys — ssh-rsa, ssh-dss,
// the ecdsa-sha2-* family — is a key someone generated years ago.
const MODERN_KEY_TYPE = 'ssh-ed25519';

// Built-in saved views. Both are hygiene worklists rather than slices: an
// authorized_keys file you can fully account for shows nothing under either,
// which is exactly the answer they exist to give.
const SSH_KEY_VIEWS = [
    {
        // A key you cannot attribute to a person is a key you cannot safely
        // remove — and the one most likely to outlive whoever added it.
        name: 'Unlabelled keys',
        state: {
            sorts: [{ key: 'type', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'sk1', field: 'comment', op: 'is', value: NO_COMMENT }],
            },
        },
    },
    {
        // The rotation list, stated as "not ed25519" rather than as a list of
        // legacy names, so a type we have never seen still shows up here.
        name: 'Legacy key types',
        state: {
            sorts: [{ key: 'type', direction: 'asc' }, { key: 'comment', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'sk2', field: 'type', op: 'none', value: [MODERN_KEY_TYPE] }],
            },
        },
    },
];

const SSHKeysTab = () => {
    const [keys, setKeys] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showAddModal, setShowAddModal] = useState(false);
    const [newKey, setNewKey] = useState('');
    const [actionLoading, setActionLoading] = useState(false);
    const toast = useToast();
    const { confirm } = useConfirm();
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-ssh-keys-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-ssh-keys-cols' });

    useEffect(() => {
        loadKeys();
    }, []);

    const loadKeys = async () => {
        setLoading(true);
        try {
            const data = await api.getSSHKeys();
            setKeys(data.keys || []);
        } catch (error) {
            console.error('Failed to load SSH keys:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleAddKey = async () => {
        if (!newKey.trim()) return;
        setActionLoading(true);
        try {
            await api.addSSHKey(newKey);
            toast.success('SSH key added successfully');
            setShowAddModal(false);
            setNewKey('');
            await loadKeys();
        } catch (error) {
            toast.error(`Failed to add key: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleRemoveKey = async (keyId, comment) => {
        const confirmed = await confirm({
            title: 'Remove SSH Key',
            message: `Are you sure you want to remove the SSH key${comment ? ` "${comment}"` : ''}? This may lock you out if it's your only key.`,
            confirmText: 'Remove',
            variant: 'danger',
        });
        if (!confirmed) return;
        try {
            await api.removeSSHKey(keyId);
            toast.success('SSH key removed');
            await loadKeys();
        } catch (error) {
            toast.error(`Failed to remove key: ${error.message}`);
        }
    };

    // Cell markup/classNames identical to the hand-rolled table they replace.
    const columns = [
        {
            key: 'type',
            header: 'Type',
            sortable: true,
            // Declared, not inferred: two keys of two types fail the enum
            // cardinality test and would fall back to text, which turns the
            // pick-list into a typed fragment and "Legacy key types" into a
            // no-op. `value` is what the rules read.
            type: 'enum',
            value: (key) => key.type || '',
            sortValue: (key) => key.type || '',
            render: (key) => <span className="sk-tag">{key.type}</span>,
        },
        {
            key: 'fingerprint',
            header: 'Fingerprint',
            sortable: true,
            hideable: false,
            sortValue: (key) => key.fingerprint || '',
            cellClassName: 'sk-cell-mono sec-fp',
            render: (key) => key.fingerprint,
        },
        {
            key: 'comment',
            header: 'Comment',
            sortable: true,
            // Text, never enum: on a box with three unlabelled keys the
            // inference would see one repeated value and offer a checklist.
            // `value` substitutes the dash the cell shows so the unlabelled
            // rows are addressable; `sortValue` keeps returning '' so the
            // ordering users already have persisted does not shift.
            type: 'text',
            value: (key) => key.comment || NO_COMMENT,
            sortValue: (key) => key.comment || '',
            render: (key) => key.comment || <span className="sec-dash">{NO_COMMENT}</span>,
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            render: (key) => (
                <Button variant="destructive" size="sm" onClick={() => handleRemoveKey(key.id, key.comment)}>
                    Remove
                </Button>
            ),
        },
    ];

    // Scoped to this table, not to Security as a page: one tab is mounted at a
    // time, so a picker at the page heading would sit above whichever tab
    // happened to be open. No `urlScope` — the keys table is the only one on
    // this tab, so its links keep the plain ?view= names.
    const chrome = useTableChrome({
        columns,
        rows: keys,
        viewPageKey: 'security-ssh-keys',
        builtinViews: SSH_KEY_VIEWS,
        noun: 'keys',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
    });

    // DataTable applies the column rules itself, so the count has to be
    // re-derived here or a view that narrows to one key still claims the total.
    const shownKeys = useMemo(
        () => applyFilters(keys, chrome.cfg.filters, chrome.columns),
        [keys, chrome.cfg.filters, chrome.columns],
    );

    return (
        <div className="ssh-keys-tab">
            {/* The view name replaces the old "SSH Authorized Keys" <h3>: one
                heading, and it now names the slice you are looking at. Add Key
                and Refresh stay put — they are actions, not filters. */}
            <GridViewPicker
                views={chrome.views}
                label="keys"
                // Null while the read is in flight: an empty `keys` means "not
                // known yet", and "0 of 0 keys" would be a claim.
                total={loading ? null : `${shownKeys.length} of ${keys.length} keys`}
                onCreate={chrome.createView}
            />
            <ListToolbar
                tools={(
                    <>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={loadKeys} />
                    </>
                )}
            >
                <Button variant="default" size="sm" onClick={() => setShowAddModal(true)}>
                    Add Key
                </Button>
                <Button variant="outline" size="sm" onClick={loadKeys}>
                    Refresh
                </Button>
            </ListToolbar>

            <GridChips {...chrome.chipProps} />

            {loading ? (
                <div className="card">
                    <div className="loading-sm">Loading...</div>
                </div>
            ) : keys.length === 0 ? (
                <div className="card">
                    <EmptyState
                        icon={KeyRound}
                        title="No SSH keys configured for root user."
                        action={(
                            <Button variant="default" onClick={() => setShowAddModal(true)}>
                                Add SSH Key
                            </Button>
                        )}
                    />
                </div>
            ) : (
                <div className="card sec-flush">
                    <DataTable
                        columns={chrome.columns}
                        data={keys}
                        keyField="id"
                        sorts={sorts}
                        onSortsChange={setSorts}
                        {...chrome.tableProps}
                        footer={(
                            <DataTableFooter
                                shown={shownKeys.length}
                                total={keys.length}
                                noun="key"
                            />
                        )}
                    />
                </div>
            )}

            <GridFilterDrawer {...chrome.drawerProps} />

            <Modal open={showAddModal} onClose={() => setShowAddModal(false)} title="Add SSH Public Key" size="lg">
                <div className="form-group">
                    <Label>Public Key</Label>
                    <Textarea
                        value={newKey}
                        onChange={(e) => setNewKey(e.target.value)}
                        placeholder="ssh-rsa AAAA... user@host or ssh-ed25519 AAAA... user@host"
                        rows={4}
                    />
                    <p className="help-text">Paste your SSH public key (typically from ~/.ssh/id_rsa.pub or ~/.ssh/id_ed25519.pub)</p>
                </div>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowAddModal(false)}>Cancel</Button>
                    <Button variant="default" onClick={handleAddKey} disabled={actionLoading || !newKey.trim()}>
                        {actionLoading ? 'Adding...' : 'Add Key'}
                    </Button>
                </div>
            </Modal>
        </div>
    );
};

export default SSHKeysTab;
