import { Pill, MetricCard, KpiBand } from '@/components/ds';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Archive, Clock, DollarSign, HardDrive, Play, ExternalLink, Loader2 } from 'lucide-react';
import { humanSize, formatMoney, formatWhen, formatDateTime } from './format';

// Card 1 of the backup "Protection" panel: a presentational status summary.
// Derives a single status (Protected / Pending / Failed / Running / Off) from
// the policy snapshot, then renders the toggle, status line, KPIs, and actions.
// All data is pre-shaped by the parent (policyView); this component holds no
// state and triggers behavior purely through the supplied callbacks.

// Status kinds map to a Pill colour + the label shown both top-right and inline.
const STATUS_PILL = {
    protected: { kind: 'green', label: 'Protected' },
    pending: { kind: 'amber', label: 'Pending' },
    failed: { kind: 'red', label: 'Failed' },
    running: { kind: 'cyan', label: 'Running' },
    off: { kind: 'gray', label: 'Off' },
};

// Pick the status key from the policy snapshot. Failure wins over everything so
// a broken last run is never hidden behind an "enabled" badge.
function resolveStatus(policy, isRunning) {
    if (policy.last_status === 'failed') return 'failed';
    if (policy.enabled && (policy.last_status === 'running' || isRunning)) return 'running';
    if (!policy.enabled) return 'off';
    if (!policy.last_run) return 'pending';
    if (policy.last_status === 'success') return 'protected';
    // Enabled but no definitive status yet (e.g. queued first run).
    return 'pending';
}

const ProtectionStatusCard = ({
    policyView,
    onToggle,
    onBackupNow,
    onViewGlobal,
    onViewJobs,
    busy,
    backingUp,
}) => {
    if (!policyView) {
        return (
            <div className="app-panel protection-status-card">
                <div className="app-panel-header">
                    <Archive size={16} />
                    <span>Protection</span>
                </div>
                <div className="app-panel-body" />
            </div>
        );
    }

    const policy = policyView.policy || {};
    const enabled = !!policy.enabled;
    const isRunning = !!policyView.is_running;
    const nextRunAt = policyView.next_run_at;

    const statusKey = resolveStatus(policy, isRunning);
    const { kind, label } = STATUS_PILL[statusKey];
    const statusPill = <Pill kind={kind}>{label}</Pill>;

    const subtitle = enabled
        ? 'Backups run on the configured schedule.'
        : 'Turn on to back up this site automatically.';

    // Inline status line (and, for the failed state, a deep-link to Jobs).
    let statusLine = null;
    let statusAction = null;
    if (statusKey === 'failed') {
        statusLine = `Last backup failed at ${formatWhen(policy.last_run_at)}`;
        statusAction = (
            <Button variant="ghost" size="sm" onClick={onViewJobs}>
                View in Jobs
            </Button>
        );
    } else if (statusKey === 'running') {
        statusLine = 'A backup is in progress…';
    } else if (statusKey === 'protected') {
        const cost = formatMoney((policy.last_cost_local || 0) + (policy.last_cost_remote || 0));
        statusLine = `Last backup: ${formatWhen(policy.last_run_at)} · ${humanSize(policy.last_size)} · ${cost}`;
    } else if (statusKey === 'pending') {
        statusLine = nextRunAt
            ? `First backup will run at ${formatDateTime(nextRunAt)}`
            : 'First backup will run soon';
    } else {
        statusLine = 'Backups are not running automatically';
    }

    const nextBackupValue = enabled && nextRunAt ? formatDateTime(nextRunAt) : '—';

    return (
        <div className="app-panel protection-status-card">
            <div className="app-panel-header">
                <Archive size={16} />
                <span>Protection</span>
                <span className="app-panel-header-actions">{statusPill}</span>
            </div>
            <div className="app-panel-body">
                <div className="protection-status-card__toggle">
                    <Switch
                        id="auto-backups"
                        checked={enabled}
                        onCheckedChange={onToggle}
                        disabled={busy}
                    />
                    <label htmlFor="auto-backups">
                        <span className="protection-status-card__toggle-title">Automatic backups</span>
                        <span className="protection-status-card__toggle-sub">{subtitle}</span>
                    </label>
                </div>

                <div className="protection-status-card__status">
                    {statusPill}
                    <span>{statusLine}</span>
                    {statusAction}
                </div>

                <KpiBand>
                    <MetricCard
                        tone="accent"
                        icon={<Clock size={16} />}
                        value={nextBackupValue}
                        label="Next backup"
                    />
                    <MetricCard
                        tone="green"
                        icon={<DollarSign size={16} />}
                        value={policyView.monthly_cost_display}
                        label="Monthly cost"
                    />
                    <MetricCard
                        tone="cyan"
                        icon={<HardDrive size={16} />}
                        value={policyView.storage_used_human}
                        label="Storage used"
                    />
                </KpiBand>

                <div className="protection-status-card__actions">
                    <Button variant="primary" size="sm" onClick={onBackupNow} disabled={backingUp}>
                        {backingUp ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
                        Back up now
                    </Button>
                    <Button variant="ghost" size="sm" onClick={onViewGlobal}>
                        <ExternalLink size={14} />
                        View in global backups
                    </Button>
                </div>
            </div>
        </div>
    );
};

export default ProtectionStatusCard;
