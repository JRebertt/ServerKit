import { useCallback, useEffect, useMemo, useState } from 'react';
import { Trash2, Undo2, RefreshCw, Clock } from 'lucide-react';
import api from '@/services/api';
import { useToast } from '@/contexts/ToastContext';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import EmptyState from '@/components/EmptyState';
import { SegControl, Pill, DataTable, ListToolbar } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import ConfirmDialog from '@/components/ConfirmDialog';

// Built-in saved views. Neither one names a `kind`: the registry decides what
// lands here, so a preset that spelled out 'domain' would be a list this file
// otherwise never hard-codes — and it would duplicate the type SegControl
// anyway. Both views work on whatever the server registered.
//
// `page.kind` is spelled out on both. The SegControl is part of the captured
// state, so a preset that left it out would compare unequal to the live state
// the instant it was applied and the picker would read "Unsaved" every time.
const RECYCLEBIN_VIEWS = [
    {
        // Oldest deletion first — the rows closest to being reaped by the
        // retention window, which is the only deadline this page has. The
        // default order (newest first) puts them at the very bottom.
        name: 'Closest to purge',
        state: {
            sorts: [{ key: 'deleted_at', direction: 'asc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: { match: 'all', rules: [] },
            page: { kind: 'all' },
        },
    },
    {
        // No rules either: everything, bucketed by what it is. The group
        // headers carry the per-type counts, so this answers "what kind of
        // thing have we been deleting" without touching the SegControl.
        name: 'By type',
        state: {
            sorts: [{ key: 'deleted_at', direction: 'desc' }],
            hiddenKeys: [],
            groupBy: 'kind',
            columnFilters: { match: 'all', rules: [] },
            page: { kind: 'all' },
        },
    },
];

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

    // Lifted out of <DataTable> so a saved view can capture them. The storage
    // keys are the ones DataTable derived from storageKey="serverkit-table-
    // recyclebin", so a persisted sort or hidden column survives.
    const { sorts, setSorts } = useTableSort({
        defaultSorts: [{ key: 'deleted_at', direction: 'desc' }],
        storageKey: 'serverkit-table-recyclebin-sort',
    });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({
        storageKey: 'serverkit-table-recyclebin-cols',
    });
    // Not persisted on its own: a grouping worth keeping is a saved view.
    const [groupBy, setGroupBy] = useState(null);

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
            // Three outcomes, not two: the side effect FAILED (warning), it
            // succeeded but left something the user should know (notice — a
            // domain that came back without its certificate), or it just worked.
            if (res?.warning) toast.error(res.warning);
            else if (res?.item?.notice) toast.warning(res.item.notice);
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
            // `groupValue` spelled out because grouping otherwise falls back to
            // row[key] — the raw registry slug ('saved_view'), where every
            // other surface here reads the noun ('saved view').
            value: (r) => r.noun,
            groupValue: (r) => r.noun,
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

    // Single table on this tab, so no `urlScope` — the shareable link keeps
    // the plain `?view=` every other single-table page produces.
    //
    // The type SegControl goes in `pageState`, so saving a view remembers
    // which type you had picked. A preset that omits `kind` must land back on
    // 'all': the envelope's page bag is `{}` there, and `undefined` would
    // leave the SegControl with no selected option.
    const chrome = useTableChrome({
        columns,
        rows: shown,
        viewPageKey: 'settings-recyclebin',
        builtinViews: RECYCLEBIN_VIEWS,
        noun: 'items',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        groupBy,
        setGroupBy,
        pageState: { kind },
        applyPage: (p) => setKind(p.kind || 'all'),
    });

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
                    {/* The section's h2 above stays put — it heads the
                        retention explanation as much as the table, so the
                        picker sits with the table it actually belongs to. */}
                    <GridViewPicker
                        views={chrome.views}
                        label="items"
                        total={`${shown.length} of ${items.length} item${items.length === 1 ? '' : 's'}`}
                        onCreate={chrome.createView}
                    />
                    {/* The retention note goes in the count slot: it is meta,
                        not a tool, and that also spares
                        `.recyclebin__retention`'s margin-left:auto from a flex
                        row it was never written for. */}
                    <ListToolbar
                        filters={<SegControl value={kind} onChange={setKind} options={filters} />}
                        count={(
                            <span className="recyclebin__retention">
                                <Clock size={13} /> kept {retentionDays} days
                            </span>
                        )}
                        tools={(
                            <>
                                <GridFilterButton
                                    count={chrome.filterCount}
                                    onClick={() => chrome.setDrawerOpen(true)}
                                />
                                <GridToolsMenu {...chrome.toolsProps} onRefresh={load} />
                            </>
                        )}
                    />

                    <GridChips {...chrome.chipProps} />

                    <DataTable
                        columns={chrome.columns}
                        data={shown}
                        keyField={rowKey}
                        sorts={sorts}
                        onSortsChange={setSorts}
                        {...chrome.tableProps}
                        groupBy={groupBy}
                        onGroupByChange={setGroupBy}
                        emptyTitle="Nothing of this type"
                        emptyMessage="Try another type."
                    />
                </>
            )}

            <GridFilterDrawer {...chrome.drawerProps} />

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
