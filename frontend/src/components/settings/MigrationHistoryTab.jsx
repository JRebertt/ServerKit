import { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';
import { Database, Loader, CheckCircle, ArrowUpCircle, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { DataTable, DataTableFooter } from '@/components/ds';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import useSettingFocus from '../../hooks/useSettingFocus';

// Revisions in this project are short descriptive slugs (e.g. 016_resource_grants),
// so show them in full rather than truncating mid-word.
const short = (rev) => rev || '';

const MigrationHistoryTab = () => {
    const toast = useToast();
    const { confirm } = useConfirm();
    const register = useSettingFocus();

    const [revisions, setRevisions] = useState([]);
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [applying, setApplying] = useState(false);
    const [backupFirst, setBackupFirst] = useState(true);

    const load = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const [hist, stat] = await Promise.all([
                api.getMigrationHistory(),
                api.getMigrationStatus(),
            ]);
            setRevisions(hist.revisions || []);
            setStatus(stat);
        } catch (err) {
            setError(err.message || 'Failed to load migration history');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    // History is returned oldest -> newest along a linear chain. Everything after
    // the applied (current) revision is unapplied, through head. status.pending_count
    // is computed once at boot and can be stale, so trust the ordered history.
    const currentIdx = revisions.findIndex((r) => r.is_current);
    const pending = currentIdx >= 0 ? revisions.slice(currentIdx + 1) : revisions.slice();
    const pendingIds = new Set(pending.map((r) => r.revision));
    const hasPending = pending.length > 0;

    const currentRev = status?.current_revision;
    const headRev = status?.head_revision;
    const count = pending.length;
    const plural = count === 1 ? '' : 's';

    // The DB records a revision that no longer exists in the migration scripts
    // (renamed during development). The schema is already in sync, so applying
    // re-stamps the version pointer rather than running DDL.
    const orphaned = Boolean(currentRev) && currentIdx === -1 && revisions.length > 0;

    // Columns for the shared DataTable. Cell markup is identical to the
    // hand-rolled table it replaces, so the .data-table rules keep applying.
    const columns = [
        {
            key: 'revision',
            header: 'Revision',
            sortable: true,
            hideable: false,
            sortValue: (rev) => rev.revision || '',
            render: (rev) => <code>{short(rev.revision)}</code>,
        },
        {
            key: 'description',
            header: 'Description',
            sortable: true,
            sortValue: (rev) => rev.description || 'Schema update',
            render: (rev) => rev.description || 'Schema update',
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            // current -> applied -> pending keeps the lifecycle order sensible.
            sortValue: (rev) => (rev.is_current ? 0 : pendingIds.has(rev.revision) ? 2 : 1),
            render: (rev) => (
                rev.is_current ? (
                    <Badge variant="success">
                        <CheckCircle size={12} /> Current
                    </Badge>
                ) : pendingIds.has(rev.revision) ? (
                    <Badge variant="warning">
                        <ArrowUpCircle size={12} /> Pending
                    </Badge>
                ) : (
                    <Badge variant="secondary">Applied</Badge>
                )
            ),
        },
    ];

    async function runMigrations() {
        const ok = await confirm({
            title: orphaned ? 'Re-sync database version?' : `Apply ${count} migration${plural}?`,
            message: orphaned
                ? `Your schema already matches ${short(headRev) || 'head'}; this repairs the version pointer${backupFirst ? ' after creating a backup' : ' (no backup will be created)'}.`
                : backupFirst
                    ? `A database backup is created first, then the schema is upgraded from ${short(currentRev) || 'none'} to ${short(headRev) || 'head'}.`
                    : `The schema is upgraded from ${short(currentRev) || 'none'} to ${short(headRev) || 'head'}. No backup will be created.`,
            confirmText: orphaned ? 'Re-sync database' : `Apply migration${plural}`,
            cancelText: 'Cancel',
            variant: 'warning',
        });
        if (!ok) return;

        setApplying(true);
        try {
            if (backupFirst) {
                try {
                    const b = await api.createMigrationBackup();
                    const name = b?.path ? b.path.split(/[\\/]/).pop() : null;
                    toast.success(name ? `Database backed up (${name})` : 'Database backed up');
                } catch (err) {
                    toast.error(`Backup failed: ${err.message || 'unknown error'} — migrations not applied`);
                    return;
                }
            }
            const res = await api.applyMigrations();
            toast.success(`Migrations applied — now at ${short(res?.revision || headRev)}`);
            await load();
        } catch (err) {
            toast.error(`Migration failed: ${err.message || 'unknown error'}`);
        } finally {
            setApplying(false);
        }
    }

    if (loading) {
        return (
            <div className="settings-section">
                <div className="loading-state">
                    <Loader size={20} className="spin" />
                    <span>Loading migration history...</span>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="settings-section">
                <div className="empty-state">
                    <p>{error}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="settings-section">
            <div className="settings-section-header">
                <h2>Database Migrations</h2>
                <p className="settings-section-description">
                    Schema versions applied to this instance. Apply pending updates after upgrading ServerKit.
                </p>
            </div>

            {hasPending ? (
                <div {...register('migrations-apply', 'migration-pending-banner')}>
                    <ArrowUpCircle size={20} className="migration-pending-icon" aria-hidden="true" />
                    <div className="migration-pending-body">
                        <p className="migration-pending-title">
                            {orphaned ? 'Database version needs repair' : `${count} migration${plural} pending`}
                        </p>
                        <p className="migration-pending-desc">
                            {orphaned ? (
                                <>
                                    Recorded version <code>{short(currentRev)}</code> isn’t in the migration
                                    history (it was renamed). Your schema already matches{' '}
                                    <code>{short(headRev) || 'head'}</code> — re-sync to repair the version pointer.
                                </>
                            ) : (
                                <>
                                    Your database is at <code>{short(currentRev) || 'none'}</code>, latest is{' '}
                                    <code>{short(headRev) || 'unknown'}</code>. Apply to bring the schema up to date.
                                </>
                            )}
                        </p>
                        <div className="migration-pending-actions">
                            <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={runMigrations}
                                disabled={applying}
                            >
                                {applying ? (
                                    <><Loader size={14} className="spin" /> {orphaned ? 'Repairing…' : 'Applying…'}</>
                                ) : orphaned ? (
                                    <><Database size={14} /> Re-sync database</>
                                ) : (
                                    <><Database size={14} /> Apply {count} migration{plural}</>
                                )}
                            </button>
                            <label className="migration-backup-toggle">
                                <input
                                    type="checkbox"
                                    checked={backupFirst}
                                    onChange={(e) => setBackupFirst(e.target.checked)}
                                    disabled={applying}
                                />
                                Back up database first
                            </label>
                        </div>
                    </div>
                </div>
            ) : (
                revisions.length > 0 && (
                    <div className="migration-uptodate">
                        <ShieldCheck size={16} aria-hidden="true" />
                        Schema is up to date{currentRev && <> — revision <code>{short(currentRev)}</code></>}.
                    </div>
                )
            )}

            {revisions.length === 0 ? (
                <div className="empty-state">
                    <Database size={32} />
                    <p>No migration history found.</p>
                </div>
            ) : (
                <div {...register('migrations-history', 'table-container')}>
                    <DataTable
                        columns={columns}
                        data={revisions}
                        keyField="revision"
                        storageKey="serverkit-table-settings-migrations"
                        tableClassName="data-table"
                        footer={(
                            <DataTableFooter
                                shown={revisions.length}
                                total={revisions.length}
                                noun="migration"
                            />
                        )}
                    />
                </div>
            )}
        </div>
    );
};

export default MigrationHistoryTab;
