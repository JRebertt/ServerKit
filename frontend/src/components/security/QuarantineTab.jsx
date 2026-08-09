import { useState, useEffect } from 'react';
import { ShieldCheck } from 'lucide-react';
import api from '../../services/api';
import EmptyState from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { ColumnsMenu, DataTable, DataTableFooter, SortMenu } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { formatBytes } from '@/utils/formatBytes';

const QuarantineTab = () => {
    const [files, setFiles] = useState([]);
    const [loading, setLoading] = useState(true);
    const [message, setMessage] = useState(null);
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-quarantine-sort' });
    const {
        hiddenKeys, toggleColumn, showAllColumns,
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
    const columns = [
        {
            key: 'filename',
            header: 'Filename',
            sortable: true,
            hideable: false,
            sortValue: (file) => file.name || '',
            cellClassName: 'sk-cell-mono sec-path sec-path--red',
            render: (file) => file.name,
        },
        {
            key: 'original',
            header: 'Original Location',
            sortable: true,
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
            sortValue: (file) => (file.size == null ? null : Number(file.size)),
            cellClassName: 'sk-cell-mono',
            render: (file) => formatBytes(file.size, { defaultValue: '0 B' }),
        },
        {
            key: 'quarantined',
            header: 'Quarantined',
            sortable: true,
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

    return (
        <div className="quarantine-tab">
            {message && (
                <div className={`alert alert-${message.type === 'success' ? 'success' : 'danger'}`}>
                    {message.text}
                </div>
            )}

            <div className="card sec-flush">
                <div className="card-header">
                    <h3>Quarantined Files {!loading && files.length > 0 && <span className="sec-count">· {files.length}</span>}</h3>
                    <div className="sec-tableactions">
                        <SortMenu columns={columns} sorts={sorts} onChange={setSorts} />
                        <ColumnsMenu
                            columns={columns}
                            hiddenKeys={hiddenKeys}
                            onToggle={toggleColumn}
                            onShowAll={showAllColumns}
                        />
                        <Button variant="outline" size="sm" onClick={loadFiles}>Refresh</Button>
                    </div>
                </div>
                {loading ? (
                    <div className="card-body">
                        <div className="loading-sm">Loading...</div>
                    </div>
                ) : files.length === 0 ? (
                    <div className="card-body">
                        <EmptyState
                            icon={ShieldCheck}
                            title="No files in quarantine"
                            description="Infected files will appear here when detected"
                        />
                    </div>
                ) : (
                    <DataTable
                        columns={columns}
                        data={files}
                        keyField="name"
                        sorts={sorts}
                        onSortsChange={setSorts}
                        hiddenKeys={hiddenKeys}
                        footer={(
                            <DataTableFooter
                                shown={files.length}
                                total={files.length}
                                noun="file"
                            />
                        )}
                    />
                )}
            </div>
        </div>
    );
};

export default QuarantineTab;
