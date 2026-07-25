import { useEffect, useState } from 'react';
import { Archive, Trash2, RefreshCw } from 'lucide-react';
import api from '../../services/api';
import EmptyState from '../EmptyState';
import { useConfirm } from '../../hooks/useConfirm';
import { formatBytes } from '@/utils/formatBytes';

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'mysql', label: 'MySQL' },
    { id: 'postgresql', label: 'PostgreSQL' },
];

export default function BackupsTab() {
    const { confirm } = useConfirm();
    const [backups, setBackups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');

    useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

    async function load() {
        setLoading(true);
        try {
            const data = await api.getDatabaseBackups(filter === 'all' ? null : filter);
            setBackups(data.backups || []);
        } catch (err) {
            console.error('Failed to load backups:', err);
        } finally {
            setLoading(false);
        }
    }

    async function remove(filename) {
        const ok = await confirm({ title: 'Delete backup', message: `Delete backup "${filename}"? This cannot be undone.`, confirmText: 'Delete backup', variant: 'danger' });
        if (!ok) return;
        try {
            await api.deleteDatabaseBackup(filename);
            load();
        } catch (err) {
            console.error('Failed to delete backup:', err);
        }
    }

    return (
        <div className="dbx-backups">
            <div className="dbx-backups-toolbar">
                <div className="dbx-segmented">
                    {FILTERS.map((f) => (
                        <button key={f.id} type="button" className={filter === f.id ? 'is-active' : ''} onClick={() => setFilter(f.id)}>
                            {f.label}
                        </button>
                    ))}
                </div>
                <div className="dbx-table-toolbar-spacer" />
                <button type="button" className="dbx-icon-btn" onClick={load} disabled={loading} aria-label="Refresh">
                    <RefreshCw size={14} className={loading ? 'dbx-spin' : ''} aria-hidden="true" />
                </button>
            </div>

            <div className="dbx-backups-body">
                {loading ? (
                    <EmptyState loading loadingVariant="table" title="Loading backups…" />
                ) : backups.length === 0 ? (
                    <EmptyState icon={Archive} title="No backups yet" description="Back up a database from its tree menu and it will appear here." />
                ) : (
                    <table className="dbx-grid dbx-backups-table">
                        <thead>
                            <tr>
                                <th scope="col">Database</th>
                                <th scope="col">Engine</th>
                                <th scope="col">File</th>
                                <th scope="col">Size</th>
                                <th scope="col">Created</th>
                                <th scope="col" aria-label="Actions" />
                            </tr>
                        </thead>
                        <tbody>
                            {backups.map((b) => (
                                <tr key={b.filename}>
                                    <td className="dbx-col-name">{b.database}</td>
                                    <td>
                                        <span className={`dbx-engine-tag is-${b.type}`}>{b.type === 'mysql' ? 'MySQL' : 'PostgreSQL'}</span>
                                    </td>
                                    <td className="dbx-mono">{b.filename}</td>
                                    <td className="dbx-mono">{formatBytes(b.size, { decimals: 2, defaultValue: '0 B' })}</td>
                                    <td className="dbx-mono">{new Date(b.created_at).toLocaleString()}</td>
                                    <td className="dbx-grid-actions">
                                        <button type="button" className="dbx-icon-btn is-danger" onClick={() => remove(b.filename)} aria-label={`Delete ${b.filename}`}>
                                            <Trash2 size={14} aria-hidden="true" />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
