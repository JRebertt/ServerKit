import { useCallback, useEffect, useMemo, useState } from 'react';
import { Trash2, Undo2, RefreshCw, Clock } from 'lucide-react';
import api from '@/services/api';
import { useToast } from '@/contexts/ToastContext';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import EmptyState from '@/components/EmptyState';
import { SegControl, Pill, DataTable, DataTableFooter } from '@/components/ds';
import ConfirmDialog from '@/components/ConfirmDialog';

// Everything the panel has soft-deleted, in one place. Type-agnostic on
// purpose: `kind` comes from the server's registry, so a newly restorable model
// shows up here with no change to this file.
export default function RecycleBinTab() {
    const toast = useToast();
    const { isAdmin } = useAuth();
    const [items, setItems] = useState([]);
    const [kinds, setKinds] = useState([]);
    const [retentionDays, setRetentionDays] = useState(30);
    const [kind, setKind] = useState('all');
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState(null);
    const [purgeTarget, setPurgeTarget] = useState(null);

    const load = useCallback(async () => {
        try {
            setLoading(true);
            const data = await api.getRecycleBin();
            setItems(data.items || []);
            setKinds(data.kinds || []);
            setRetentionDays(data.retention_days ?? 30);
        } catch (err) {
            toast.error(err.message || 'Could not load the recycle bin');
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const rowKey = (row) => `${row.kind}:${row.id}`;

    const restore = async (row) => {
        setBusyId(rowKey(row));
        try {
            const res = await api.restoreRecord(row.kind, row.id);
            // The row can be back while a side effect failed — report which.
            if (res?.warning) toast.error(res.warning);
            else toast.success(`Restored ${row.noun} “${row.label}”`);
            await load();
        } catch (err) {
            toast.error(err.message || 'Restore failed');
        } finally {
            setBusyId(null);
        }
    };

    const purge = async (row) => {
        setBusyId(rowKey(row));
        try {
            await api.purgeRecord(row.kind, row.id);
            toast.success(`Permanently deleted “${row.label}”`);
            await load();
        } catch (err) {
            toast.error(err.message || 'Delete failed');
        } finally {
            setBusyId(null);
            setPurgeTarget(null);
        }
    };

    const shown = useMemo(
        () => (kind === 'all' ? items : items.filter((i) => i.kind === kind)),
        [items, kind],
    );

    const filters = useMemo(() => [
        { value: 'all', label: 'All', count: items.length },
        ...kinds.map((k) => ({
            value: k,
            label: `${k.replace(/_/g, ' ')}s`,
            count: items.filter((i) => i.kind === k).length,
        })),
    ], [items, kinds]);

    const columns = useMemo(() => [
        {
            key: 'label',
            header: 'Record',
            sortable: true,
            hideable: false,
            type: 'text',
            value: (r) => r.label,
            render: (r) => (
                <div className="sk-cell-name">
                    <span>
                        {r.label}
                        {r.description && <div className="sk-cell-sub">{r.description}</div>}
                    </span>
                </div>
            ),
        },
        {
            key: 'kind',
            header: 'Type',
            sortable: true,
            type: 'enum',
            groupable: true,
            value: (r) => r.noun,
            render: (r) => <Pill kind="gray">{r.noun}</Pill>,
        },
        {
            key: 'deleted_at',
            header: 'Deleted',
            sortable: true,
            type: 'date',
            value: (r) => r.deleted_at,
            render: (r) => {
                if (!r.deleted_at) return <span className="dom-dash">—</span>;
                const when = new Date(r.deleted_at);
                const days = Math.floor((Date.now() - when.getTime()) / 86400000);
                const left = retentionDays - days;
                return (
                    <div>
                        <div className="sk-cell-mono">{when.toLocaleDateString()}</div>
                        <div className={`sk-cell-sub ${left <= 3 ? 'is-urgent' : ''}`}>
                            {left > 0 ? `purges in ${left}d` : 'past retention'}
                        </div>
                    </div>
                );
            },
        },
        {
            key: '__actions',
            header: '',
            sortable: false,
            hideable: false,
            className: 'text-right',
            render: (r) => (
                <div className="recyclebin__rowactions">
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={busyId === rowKey(r)}
                        onClick={() => restore(r)}
                    >
                        <Undo2 size={14} /> Restore
                    </Button>
                    {isAdmin && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="recyclebin__purge"
                            disabled={busyId === rowKey(r)}
                            onClick={() => setPurgeTarget(r)}
                            title="Delete permanently"
                            aria-label={`Delete ${r.label} permanently`}
                        >
                            <Trash2 size={14} />
                        </Button>
                    )}
                </div>
            ),
        },
    ], [busyId, isAdmin, retentionDays]); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="settings-section recyclebin">
            <div className="settings-section__head">
                <div>
                    <h2>Recycle bin</h2>
                    <p className="settings-section__hint">
                        Deleted records are kept for {retentionDays} days so they can be put back.
                        Restoring returns the record itself — it does not re-apply configuration
                        that was torn down at delete time (a domain’s vhost, for example).
                    </p>
                </div>
                <Button variant="outline" size="sm" onClick={load} disabled={loading}>
                    <RefreshCw size={15} /> Refresh
                </Button>
            </div>

            {loading ? (
                <EmptyState loading loadingVariant="table" title="Loading deleted records…" />
            ) : items.length === 0 ? (
                <EmptyState
                    icon={Trash2}
                    title="Nothing deleted"
                    description="Records you delete land here first, so a mistake is a click away from being undone."
                />
            ) : (
                <>
                    <div className="recyclebin__toolbar">
                        <SegControl value={kind} onChange={setKind} options={filters} />
                        <span className="recyclebin__retention">
                            <Clock size={13} /> kept {retentionDays} days
                        </span>
                    </div>

                    <DataTable
                        columns={columns}
                        data={shown}
                        keyField={rowKey}
                        defaultSorts={[{ key: 'deleted_at', direction: 'desc' }]}
                        storageKey="serverkit-table-recyclebin"
                        emptyTitle="Nothing of this type"
                        emptyMessage="Try another type."
                        footer={(
                            <DataTableFooter shown={shown.length} total={items.length} noun="record" />
                        )}
                    />
                </>
            )}

            <ConfirmDialog
                isOpen={!!purgeTarget}
                variant="danger"
                title={`Permanently delete “${purgeTarget?.label ?? ''}”?`}
                message="This cannot be undone. The record is removed from the database for good."
                details={purgeTarget ? `${purgeTarget.noun} · deleted ${purgeTarget.deleted_at?.slice(0, 10) || ''}` : ''}
                confirmText="Delete permanently"
                onConfirm={() => purgeTarget && purge(purgeTarget)}
                onCancel={() => setPurgeTarget(null)}
            />
        </div>
    );
}
