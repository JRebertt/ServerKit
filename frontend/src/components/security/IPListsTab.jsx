import { useState, useEffect } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '@/hooks/useConfirm';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ColumnsMenu, DataTable, DataTableFooter, SortMenu } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';

const IPListsTab = () => {
    const [lists, setLists] = useState({ allowlist: [], blocklist: [] });
    const [loading, setLoading] = useState(true);
    const [showAddModal, setShowAddModal] = useState(null);
    const [newIP, setNewIP] = useState('');
    const [newComment, setNewComment] = useState('');
    const [actionLoading, setActionLoading] = useState(false);
    const toast = useToast();
    const { confirm } = useConfirm();
    // Each list is its own table with its own persisted sort/columns state.
    const allowSorts = useTableSort({ storageKey: 'serverkit-table-ip-allowlist-sort' });
    const allowCols = useColumnVisibility({ storageKey: 'serverkit-table-ip-allowlist-cols' });
    const blockSorts = useTableSort({ storageKey: 'serverkit-table-ip-blocklist-sort' });
    const blockCols = useColumnVisibility({ storageKey: 'serverkit-table-ip-blocklist-cols' });

    useEffect(() => {
        loadLists();
    }, []);

    const loadLists = async () => {
        setLoading(true);
        try {
            const data = await api.getIPLists();
            setLists({
                allowlist: data.allowlist || [],
                blocklist: data.blocklist || []
            });
        } catch (error) {
            console.error('Failed to load IP lists:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleAdd = async () => {
        if (!newIP.trim()) return;
        setActionLoading(true);
        try {
            await api.addToIPList(newIP, showAddModal, newComment);
            toast.success(`IP added to ${showAddModal}`);
            setShowAddModal(null);
            setNewIP('');
            setNewComment('');
            await loadLists();
        } catch (error) {
            toast.error(`Failed to add IP: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleRemove = async (item, listType) => {
        const confirmed = await confirm({
            title: `Remove from ${listType}`,
            message: `Are you sure you want to remove ${item.ip} from the ${listType}?`,
            confirmText: 'Remove',
            variant: 'warning',
        });
        if (!confirmed) return;
        try {
            await api.removeFromIPList(item.ip, listType);
            toast.success(`IP removed from ${listType}`, {
                duration: 8000,
                action: {
                    label: 'Undo',
                    onClick: async () => {
                        try {
                            await api.addToIPList(item.ip, listType, item.comment || '');
                            toast.success(`IP restored to ${listType}`);
                            await loadLists();
                        } catch (error) {
                            toast.error(`Could not restore IP: ${error.message}`);
                        }
                    },
                },
            });
            await loadLists();
        } catch (error) {
            toast.error(`Failed to remove IP: ${error.message}`);
        }
    };

    // Cell markup/classNames identical to the hand-rolled table they replace.
    const renderList = (title, listType, items, tone, sortState, colState) => {
        const columns = [
            {
                key: 'ip',
                header: 'IP / CIDR',
                sortable: true,
                hideable: false,
                sortValue: (item) => item.ip || '',
                cellClassName: `sk-cell-mono sec-ip--${tone}`,
                render: (item) => item.ip,
            },
            {
                key: 'comment',
                header: 'Comment',
                sortable: true,
                sortValue: (item) => item.comment || '',
                render: (item) => item.comment || <span className="sec-dash">—</span>,
            },
            {
                key: 'added',
                header: 'Added',
                sortable: true,
                sortValue: (item) => {
                    const t = new Date(item.added_at).getTime();
                    return Number.isNaN(t) ? null : t;
                },
                cellClassName: 'sk-cell-mono sec-faint',
                render: (item) => new Date(item.added_at).toLocaleDateString(),
            },
            {
                key: 'actions',
                header: '',
                sortable: false,
                hideable: false,
                cellClassName: 'sec-rowend',
                render: (item) => (
                    <Button variant="destructive" size="sm" onClick={() => handleRemove(item, listType)}>
                        Remove
                    </Button>
                ),
            },
        ];
        return (
        <div className="card sec-flush">
            <div className="card-header">
                <h3 className={`sec-listtitle sec-listtitle--${tone}`}>
                    {title} <span className="sec-count">· {items.length}</span>
                </h3>
                <div className="sec-tableactions">
                    <SortMenu columns={columns} sorts={sortState.sorts} onChange={sortState.setSorts} />
                    <ColumnsMenu
                        columns={columns}
                        hiddenKeys={colState.hiddenKeys}
                        onToggle={colState.toggleColumn}
                        onShowAll={colState.showAllColumns}
                    />
                    <Button variant="default" size="sm" onClick={() => setShowAddModal(listType)}>
                        Add IP
                    </Button>
                </div>
            </div>
            {items.length === 0 ? (
                <div className="card-body">
                    <p className="text-muted">No IPs in {listType}.</p>
                </div>
            ) : (
                <DataTable
                    columns={columns}
                    data={items}
                    keyField={(item) => item.ip}
                    sorts={sortState.sorts}
                    onSortsChange={sortState.setSorts}
                    hiddenKeys={colState.hiddenKeys}
                    footer={(
                        <DataTableFooter
                            shown={items.length}
                            total={items.length}
                            noun="entry"
                        />
                    )}
                />
            )}
        </div>
        );
    };

    if (loading) {
        return <div className="loading-sm">Loading IP lists...</div>;
    }

    return (
        <div className="ip-lists-tab">
            <div className="ip-lists-grid">
                {renderList('Allowlist', 'allowlist', lists.allowlist, 'green', allowSorts, allowCols)}
                {renderList('Blocklist', 'blocklist', lists.blocklist, 'red', blockSorts, blockCols)}
            </div>

            <Modal open={!!showAddModal} onClose={() => setShowAddModal(null)} title={`Add to ${showAddModal || ''}`}>
                <div className="form-group">
                    <Label>IP Address or CIDR</Label>
                    <Input
                        type="text"
                        value={newIP}
                        onChange={(e) => setNewIP(e.target.value)}
                        placeholder="192.168.1.100 or 10.0.0.0/24"
                    />
                </div>
                <div className="form-group">
                    <Label>Comment (optional)</Label>
                    <Input
                        type="text"
                        value={newComment}
                        onChange={(e) => setNewComment(e.target.value)}
                        placeholder="Office IP, VPN, etc."
                    />
                </div>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowAddModal(null)}>Cancel</Button>
                    <Button variant="default" onClick={handleAdd} disabled={actionLoading || !newIP.trim()}>
                        {actionLoading ? 'Adding...' : 'Add'}
                    </Button>
                </div>
            </Modal>
        </div>
    );
};

export default IPListsTab;
