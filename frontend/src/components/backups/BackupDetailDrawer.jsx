// Right-side drawer for the backup "Protection" panel: shows one backup run's
// details (status, timing, size, cost, storage, verification) plus the run-level
// actions (restore, verify remote, download, delete). Always renders the Drawer
// so its open/close slide animation plays even when there's no run selected.
import { Drawer, Pill } from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Archive, RotateCcw, ShieldCheck, Download, Trash2, ExternalLink } from 'lucide-react';
import { humanSize, formatMoney, formatDateTime, statusKind, storageLabel } from './format';

export default function BackupDetailDrawer({ run, open, onClose, onRestore, onVerify, onDelete, onDownload }) {
    // No run selected: render an empty Drawer so the close animation still plays.
    if (!run) {
        return (
            <Drawer open={open} onOpenChange={(v) => !v && onClose()} title="Backup" width={560}>
                <div />
            </Drawer>
        );
    }

    const title = run.metadata?.backup_name || `Backup #${run.id}`;
    const verification = run.remote_key
        ? (run.verified ? 'Verified' : 'Unverified')
        : 'Local only';

    return (
        <Drawer
            open={open}
            onOpenChange={(v) => !v && onClose()}
            title={title}
            subtitle={run.kind}
            icon={<Archive size={18} />}
            width={560}
        >
            <div className="backup-detail-drawer">
                <div className="backup-detail-drawer__head">
                    <Pill kind={statusKind(run.status)}>{run.status}</Pill>
                    {run.verified && <Pill kind="green" dot={false}>Verified</Pill>}
                </div>

                {run.status === 'failed' && run.error_message && (
                    <p className="backup-detail-drawer__error">{run.error_message}</p>
                )}

                <div className="backup-detail-drawer__meta">
                    <div className="backup-detail-drawer__row"><span>Created</span><span>{formatDateTime(run.started_at)}</span></div>
                    <div className="backup-detail-drawer__row"><span>Finished</span><span>{formatDateTime(run.finished_at)}</span></div>
                    <div className="backup-detail-drawer__row"><span>Duration</span><span>{run.duration_seconds != null ? `${run.duration_seconds}s` : '—'}</span></div>
                    <div className="backup-detail-drawer__row"><span>Type</span><span>{run.kind}</span></div>
                    <div className="backup-detail-drawer__row"><span>Compression</span><span>{run.compression || '—'}</span></div>
                    <div className="backup-detail-drawer__row"><span>Storage</span><span>{storageLabel(run)}</span></div>
                    <div className="backup-detail-drawer__row"><span>Size (local)</span><span>{humanSize(run.size_local)}</span></div>
                    <div className="backup-detail-drawer__row"><span>Size (remote)</span><span>{run.size_remote ? humanSize(run.size_remote) : '—'}</span></div>
                    <div className="backup-detail-drawer__row"><span>Verification</span><span>{verification}</span></div>
                </div>

                <div className="backup-detail-drawer__cost">
                    Estimated cost: {formatMoney(run.cost_local)} (local) + {formatMoney(run.cost_remote)} (remote) = {formatMoney(run.cost_total)} total
                </div>

                <div className="backup-detail-drawer__actions">
                    <Button variant="primary" size="sm" disabled={run.status !== 'success'} onClick={() => onRestore(run)}>
                        <RotateCcw size={14} /> Restore
                    </Button>
                    {run.remote_key && (
                        <Button variant="outline" size="sm" onClick={() => onVerify(run)}>
                            <ShieldCheck size={14} /> Verify remote
                        </Button>
                    )}
                    {onDownload && run.storage_path && (
                        <Button variant="outline" size="sm" onClick={() => onDownload(run)}>
                            <Download size={14} /> Download
                        </Button>
                    )}
                    <Button variant="destructive" size="sm" onClick={() => onDelete(run)}>
                        <Trash2 size={14} /> Delete
                    </Button>
                </div>

                {run.job_id && (
                    <a className="backup-detail-drawer__joblink" href="/monitoring/jobs">
                        <ExternalLink size={13} /> View job
                    </a>
                )}
            </div>
        </Drawer>
    );
}
