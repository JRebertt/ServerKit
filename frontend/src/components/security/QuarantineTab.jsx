import { useState, useEffect, useMemo } from 'react';
import { ShieldCheck } from 'lucide-react';
import api from '../../services/api';
import EmptyState from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { DataTable, DataTableFooter, ListToolbar } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer, applyFilters,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { formatBytes } from '@/utils/formatBytes';

// Built-in saved views. Three, because the quarantine list only ever answers
// three questions: what did the last scan catch, what is filling the
// quarantine directory, and which of these can still be put back.
//
// Every rule matches a column's `value` accessor (ds/grid/fields.js), never
// `sortValue` — see the `quarantined` column for why that distinction bites.
const NO_RULES = { match: 'all', rules: [] };

const QUARANTINE_VIEWS = [
    {
        // The landing view: quarantine is an event log, so the newest catch is
        // the one nobody has looked at yet.
        name: 'Newest first',
        state: {
            sorts: [{ key: 'quarantined', direction: 'desc' }],
            hiddenKeys: [],
            columnFilters: NO_RULES,
        },
    },
    {
        // Nothing ages out of quarantine on its own, so this is the view you
        // open when the partition holding it starts to fill.
        name: 'Largest first',
        state: {
            sorts: [{ key: 'size', direction: 'desc' }],
            hiddenKeys: [],
            columnFilters: NO_RULES,
        },
    },
    {
        // Restore needs the sidecar that recorded where the file came from —
        // without it the Restore button is dead and delete is the only move.
        // The rule is "an absolute path was recorded": the quarantine service
        // writes os.path.abspath(), and a row with no sidecar reads '', which
        // starts with nothing.
        name: 'Restorable',
        state: {
            sorts: [{ key: 'quarantined', direction: 'desc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'qr1', field: 'original', op: 'starts', value: '/' }],
            },
        },
    },
];

const QuarantineTab = () => {
    const [files, setFiles] = useState([]);
    const [loading, setLoading] = useState(true);
    const [message, setMessage] = useState(null);
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-quarantine-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-quarantine-cols' });

    useEffect(() => {
        loadFiles();
    }, []);

    async function loadFiles() {
        try {
            const data = await api.getQuarantinedFiles();
            setFiles(data.files || []);
        } catch (err) {
            console.error('Failed to load quarantined files:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleDelete(filename) {
        if (!confirm(`Permanently delete ${filename}? This cannot be undone.`)) return;

        try {
            await api.deleteQuarantinedFile(filename);
            setMessage({ type: 'success', text: 'File deleted' });
            loadFiles();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        }
    }

    async function handleRestore(file) {
        const target = file.original_path || 'its original location';
        if (!confirm(`Restore ${file.name} to ${target}? Only do this for false positives.`)) return;

        try {
            const result = await api.restoreQuarantinedFile(file.name);
            setMessage({ type: 'success', text: result.message || 'File restored' });
            loadFiles();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        }
    }

    // Cell markup/classNames identical to the hand-rolled table they replace.
    // Two accessors per column on purpose: `value` is what the column menu, the
    // filter rules and the export read, `sortValue` is what DataTable's sorter
    // reads — it has no fallback to `value`, so a column needs both.
    const columns = [
        {
            key: 'filename',
            header: 'Filename',
            sortable: true,
            hideable: false,
            type: 'text',
            value: (file) => file.name || '',
            sortValue: (file) => file.name || '',
            cellClassName: 'sk-cell-mono sec-path sec-path--red',
            render: (file) => file.name,
        },
        {
            key: 'original',
            header: 'Original Location',
            sortable: true,
            type: 'text',
            // '' rather than null when the sidecar is missing: the Restorable
            // view asks whether the recorded path is absolute, and a null would
            // make that rule compare against the string "null".
            value: (file) => file.original_path || '',
            sortValue: (file) => file.original_path || '',
            cellClassName: 'sk-cell-mono sec-path sec-faint',
            render: (file) => (
                <span title={file.original_path || ''}>
                    {file.original_path || '—'}
                </span>
            ),
        },
        {
            key: 'size',
            header: 'Size',
            sortable: true,
            type: 'num',
            value: (file) => (file.size == null ? null : Number(file.size)),
            sortValue: (file) => (file.size == null ? null : Number(file.size)),
            cellClassName: 'sk-cell-mono',
            render: (file) => formatBytes(file.size, { defaultValue: '0 B' }),
        },
        {
            key: 'quarantined',
            header: 'Quarantined',
            sortable: true,
            // Declared, not inferred: the sorter wants epoch ms, and letting
            // that number type the column would offer "is under 1754…" instead
            // of a date picker — and make any date rule match nothing.
            type: 'date',
            value: (file) => file.quarantined_at || null,
            sortValue: (file) => {
                const t = new Date(file.quarantined_at).getTime();
                return Number.isNaN(t) ? null : t;
            },
            cellClassName: 'sk-cell-mono sec-faint',
            render: (file) => new Date(file.quarantined_at).toLocaleString(),
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            render: (file) => (
                <div className="quarantine-actions">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleRestore(file)}
                        disabled={!file.original_path}
                        title={file.original_path ? 'Restore to original location' : 'Original location unknown'}
                    >
                        Restore
                    </Button>
                    <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleDelete(file.name)}
                    >
                        Delete
                    </Button>
                </div>
            ),
        },
    ];

    // No `pageState`: the endpoint returns the whole quarantine directory
    // unpaginated, and the tab owns no search or server-side filter of its own,
    // so there is nothing page-private for a saved view to carry.
    const chrome = useTableChrome({
        columns,
        rows: files,
        viewPageKey: 'security-quarantine',
        builtinViews: QUARANTINE_VIEWS,
        noun: 'files',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
    });

    // DataTable applies the column rules itself, so the tab has to re-run them
    // to say how many rows survived. Cheap — the list is a directory listing.
    const shownCount = useMemo(
        () => applyFilters(files, chrome.cfg.filters, chrome.columns).length,
        [files, chrome.cfg.filters, chrome.columns],
    );

    // Null while the fetch is in flight: an empty `files` is "not known yet",
    // and "0 files" is a claim.
    const countLabel = loading ? null
        : shownCount === files.length
            ? `${files.length} file${files.length === 1 ? '' : 's'}`
            : `${shownCount} of ${files.length} files`;

    return (
        <div className="quarantine-tab">
            {message && (
                <div className={`alert alert-${message.type === 'success' ? 'success' : 'danger'}`}>
                    {message.text}
                </div>
            )}

            {/* The view name replaces the old "Quarantined Files · N" eyebrow:
                the view IS what you are looking at, and two titles stacked read
                as two sections. */}
            <GridViewPicker
                views={chrome.views}
                label="files"
                total={countLabel}
                onCreate={chrome.createView}
            />
            <ListToolbar
                tools={(
                    <>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={loadFiles} />
                    </>
                )}
            >
                <Button variant="outline" size="sm" onClick={loadFiles}>Refresh</Button>
            </ListToolbar>

            <GridChips {...chrome.chipProps} />

            <DataTable
                loading={loading}
                columns={chrome.columns}
                data={files}
                keyField="name"
                sorts={sorts}
                onSortsChange={setSorts}
                {...chrome.tableProps}
                emptyState={(
                    <EmptyState
                        icon={ShieldCheck}
                        title="No files in quarantine"
                        description="Infected files will appear here when detected"
                    />
                )}
                footer={(
                    <DataTableFooter
                        shown={shownCount}
                        total={files.length}
                        noun="file"
                    />
                )}
            />

            <GridFilterDrawer {...chrome.drawerProps} />
        </div>
    );
};

export default QuarantineTab;
