import { useState, useEffect } from 'react';
import { KeyRound } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '@/hooks/useConfirm';
import EmptyState from '@/components/EmptyState';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { ColumnsMenu, DataTable, DataTableFooter, SortMenu } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';

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
        hiddenKeys, toggleColumn, showAllColumns,
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
            sortValue: (key) => key.comment || '',
            render: (key) => key.comment || <span className="sec-dash">—</span>,
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

    return (
        <div className="ssh-keys-tab">
            <div className="card sec-flush">
                <div className="card-header">
                    <h3>SSH Authorized Keys {!loading && keys.length > 0 && <span className="sec-count">· {keys.length}</span>}</h3>
                    <div className="card-actions">
                        <SortMenu columns={columns} sorts={sorts} onChange={setSorts} />
                        <ColumnsMenu
                            columns={columns}
                            hiddenKeys={hiddenKeys}
                            onToggle={toggleColumn}
                            onShowAll={showAllColumns}
                        />
                        <Button variant="default" size="sm" onClick={() => setShowAddModal(true)}>
                            Add Key
                        </Button>
                        <Button variant="outline" size="sm" onClick={loadKeys}>
                            Refresh
                        </Button>
                    </div>
                </div>
                {loading ? (
                    <div className="card-body">
                        <div className="loading-sm">Loading...</div>
                    </div>
                ) : keys.length === 0 ? (
                    <div className="card-body">
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
                    <DataTable
                        columns={columns}
                        data={keys}
                        keyField="id"
                        sorts={sorts}
                        onSortsChange={setSorts}
                        hiddenKeys={hiddenKeys}
                        footer={(
                            <DataTableFooter
                                shown={keys.length}
                                total={keys.length}
                                noun="key"
                            />
                        )}
                    />
                )}
            </div>

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
