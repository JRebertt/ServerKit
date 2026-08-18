import { useState, useEffect, useCallback } from 'react';
import { Copy, ShieldCheck, Trash2, RefreshCw, Link2, Users } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { Button } from '@/components/ui/button';
import { Pill } from '../ds';
import AdminerSsoButton from './AdminerSsoButton';
import DbUsersPanel from './DbUsersPanel';
import { copyToClipboard } from '@/utils/clipboard';

// Durable list of the databases ServerKit tracks (provisioned or adopted),
// beside the live explorer. Reveal/copy a real connection string (audited),
// protect it with a backup policy (real FK), or untrack/drop it.
export default function ManagedDatabasesPanel() {
    const toast = useToast();
    const { confirm } = useConfirm();
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState(null);
    const [usersOpenId, setUsersOpenId] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getManagedDatabases();
            setRows(data?.databases || []);
        } catch (err) {
            toast.error(err.message || 'Failed to load managed databases');
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => { load(); }, [load]);

    async function copyConnectionUri(row) {
        setBusyId(row.id);
        try {
            const data = await api.revealManagedConnectionUri(row.id);
            const uri = data?.connection_uri;
            if (uri && await copyToClipboard(uri)) {
                toast.success('Connection string copied (reveal was audited)');
            } else if (uri) {
                toast.info(uri);
            }
        } catch (err) {
            toast.error(err.message || 'Failed to reveal connection string');
        } finally {
            setBusyId(null);
        }
    }

    async function protect(row) {
        setBusyId(row.id);
        try {
            await api.protectManagedDatabase(row.id);
            toast.success('Backup policy created. Tune it under Backups.');
        } catch (err) {
            toast.error(err.message || 'Failed to protect database');
        } finally {
            setBusyId(null);
        }
    }

    async function untrack(row, drop) {
        const ok = await confirm({
            title: drop ? `Drop “${row.name}”?` : `Untrack “${row.name}”?`,
            message: drop
                ? 'This DROPs the database on the server and removes tracking. This cannot be undone.'
                : 'This stops tracking the database. The database itself is left untouched.',
            confirmText: drop ? 'Drop database' : 'Untrack',
            danger: drop,
        });
        if (!ok) return;
        setBusyId(row.id);
        try {
            await api.deleteManagedDatabase(row.id, { drop });
            toast.success(drop ? 'Database dropped and untracked' : 'Database untracked');
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to remove database');
        } finally {
            setBusyId(null);
        }
    }

    if (loading) {
        return <p className="managed-db__hint">Loading managed databases…</p>;
    }

    return (
        <div className="managed-db">
            <div className="managed-db__head">
                <p className="managed-db__hint">
                    Databases ServerKit tracks for backups and connection strings. The live
                    explorer still shows everything on the server.
                </p>
                <Button type="button" size="sm" variant="ghost" onClick={load} aria-label="Refresh">
                    <RefreshCw size={14} /> Refresh
                </Button>
            </div>

            {rows.length === 0 ? (
                <p className="managed-db__empty">
                    <Link2 size={15} /> No tracked databases yet. Provisioning a database tracks it
                    automatically; you can also adopt an existing one.
                </p>
            ) : (
                <div className="managed-db__list">
                    {rows.map((row) => (
                        <div key={row.id} className="managed-db__item">
                            <div className="managed-db__row">
                                <div className="managed-db__info">
                                    <strong>{row.name}</strong>
                                    <span className="managed-db__meta">
                                        {row.engine} · {row.host}:{row.port}
                                        {row.admin_username ? ` · ${row.admin_username}` : ''}
                                    </span>
                                </div>
                                <Pill kind={row.origin === 'provisioned' ? 'green' : 'gray'}>{row.origin}</Pill>
                                <div className="managed-db__actions">
                                    {(row.engine === 'mysql' || row.engine === 'postgresql') && (
                                        <AdminerSsoButton databaseId={row.id} disabled={busyId === row.id} />
                                    )}
                                    <Button type="button" size="sm" variant="outline" disabled={busyId === row.id}
                                        onClick={() => copyConnectionUri(row)}>
                                        <Copy size={14} /> Connection string
                                    </Button>
                                    <Button type="button" size="sm" variant="outline" disabled={busyId === row.id}
                                        onClick={() => protect(row)}>
                                        <ShieldCheck size={14} /> Protect
                                    </Button>
                                    {(row.engine === 'mysql' || row.engine === 'postgresql') && (
                                        <Button type="button" size="sm" variant="ghost" disabled={busyId === row.id}
                                            onClick={() => setUsersOpenId(usersOpenId === row.id ? null : row.id)}
                                            aria-expanded={usersOpenId === row.id}>
                                            <Users size={14} /> Users
                                        </Button>
                                    )}
                                    <Button type="button" size="sm" variant="ghost" disabled={busyId === row.id}
                                        onClick={() => untrack(row, false)} aria-label={`Untrack ${row.name}`}>
                                        <Trash2 size={14} /> Untrack
                                    </Button>
                                </div>
                            </div>
                            {usersOpenId === row.id && <DbUsersPanel databaseId={row.id} />}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
