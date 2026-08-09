import { Archive, Database, Globe, HardDrive, Package, Play, ShieldCheck, Trash2 } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { DataTable, DataTableFooter } from '@/components/ds';

const KIND_ICON = {
    application: Package,
    database: Database,
    files: Archive,
    wordpress: Globe,
    server: HardDrive,
};

const DAY_INDEX = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
const DAY_LABEL = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// Next fire of a schedule row. Deliberately the same walk-forward the overview
// tile uses, so "in 4h 48m" here and on Overview can never disagree.
function nextFire(schedule) {
    const [hh, mm] = String(schedule.schedule_time || '').split(':').map(Number);
    if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
    const days = Array.isArray(schedule.days) ? schedule.days : ['daily'];
    const daily = days.length === 0 || days.includes('daily');
    const wanted = daily
        ? null
        : new Set(days.map((d) => DAY_INDEX[String(d).slice(0, 3).toLowerCase()]).filter((n) => n != null));
    if (!daily && (!wanted || wanted.size === 0)) return null;
    for (let offset = 0; offset <= 7; offset += 1) {
        const candidate = new Date();
        candidate.setDate(candidate.getDate() + offset);
        candidate.setHours(hh, mm, 0, 0);
        if (candidate.getTime() <= Date.now()) continue;
        if (daily || wanted.has(candidate.getDay())) return candidate;
    }
    return null;
}

function untilLabel(date) {
    const ms = date.getTime() - Date.now();
    if (ms <= 0) return 'due now';
    const mins = Math.round(ms / 60000);
    if (mins < 60) return `in ${mins}m`;
    const h = Math.floor(mins / 60);
    if (h < 24) return `in ${h}h ${mins % 60}m`;
    return `in ${Math.round(h / 24)}d`;
}

function agoLabel(iso) {
    if (!iso) return 'Never';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (Number.isNaN(diff)) return 'Never';
    if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    if (diff < 172800) return 'yesterday';
    return `${Math.round(diff / 86400)}d ago`;
}

// Frequency in the mock's phrasing: "Daily · 03:00" / "Weekly · Sun 02:00".
function frequencyLabel(schedule) {
    const time = schedule.schedule_time || '—';
    const days = Array.isArray(schedule.days) ? schedule.days : ['daily'];
    if (days.length === 0 || days.includes('daily')) return `Daily · ${time}`;
    if (days.length === 1) {
        const idx = DAY_INDEX[String(days[0]).slice(0, 3).toLowerCase()];
        return `Weekly · ${idx == null ? days[0] : DAY_LABEL[idx]} ${time}`;
    }
    return `${days.length}×/week · ${time}`;
}

// Policy list in the design mock's shape: what runs, how often, how long it is
// kept, where it lands, and whether it is on. The columns the mock fills from
// its fixtures but this panel has no source for (per-policy size, run-now) are
// left out rather than faked.
export default function SchedulesTable({
    schedules, retentionDays, remoteLabel, onToggle, onRemove, onRun,
}) {
    // DataTable columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace, so _backups.scss keeps applying
    // (.bk-name, .bk-ret, .bk-lastrun, .bk-paused, .bk-col-on, .bk-actions).
    const columns = [
        {
            key: 'policy',
            header: 'Policy',
            sortable: true,
            hideable: false,
            sortValue: (s) => s.name || '',
            render: (schedule) => {
                const Icon = KIND_ICON[schedule.backup_type] || Archive;
                return (
                    <div className="sk-cell-name bk-name">
                        <span className={`bk-ico bk-ico--${schedule.backup_type}`}>
                            <Icon size={15} />
                        </span>
                        <span>
                            <div>{schedule.name}</div>
                            <div className="sk-cell-sub">
                                {[schedule.target, schedule.backup_type,
                                    schedule.upload_remote ? 'off-box copy' : null]
                                    .filter(Boolean).join(' · ')}
                            </div>
                        </span>
                    </div>
                );
            },
        },
        {
            key: 'frequency',
            header: 'Frequency',
            sortable: true,
            sortValue: (s) => frequencyLabel(s),
            cellClassName: 'sk-cell-mono',
            render: (schedule) => frequencyLabel(schedule),
        },
        {
            // Same retentionDays on every row — sorting it would be noise.
            key: 'retention',
            header: 'Retention',
            render: () => (
                <span className="bk-ret">
                    <span>{retentionDays} d</span>
                </span>
            ),
        },
        {
            key: 'destination',
            header: 'Destination',
            sortable: true,
            sortValue: (s) => (s.upload_remote ? remoteLabel : 'Local disk'),
            cellClassName: 'sk-cell-mono',
            render: (schedule) => (schedule.upload_remote ? remoteLabel : 'Local disk'),
        },
        {
            key: 'lastRun',
            header: 'Last run',
            sortable: true,
            sortValue: (s) => (s.last_run ? new Date(s.last_run).getTime() : null),
            render: (schedule) => {
                const failed = schedule.last_status === 'failed';
                return failed ? (
                    <span className="bk-lastrun is-failed">
                        <i />{agoLabel(schedule.last_run)}
                    </span>
                ) : (
                    <span className="bk-lastrun">{agoLabel(schedule.last_run)}</span>
                );
            },
        },
        {
            key: 'next',
            header: 'Next',
            sortable: true,
            sortValue: (s) => {
                const next = s.enabled ? nextFire(s) : null;
                return next ? next.getTime() : null;
            },
            cellClassName: 'sk-cell-mono',
            render: (schedule) => {
                const next = schedule.enabled ? nextFire(schedule) : null;
                return schedule.enabled
                    ? (next ? untilLabel(next) : '—')
                    : <span className="bk-paused">paused</span>;
            },
        },
        {
            key: 'on',
            header: 'On',
            sortable: true,
            sortValue: (s) => (s.enabled ? 1 : 0),
            className: 'bk-col-on',
            cellClassName: 'bk-col-on',
            render: (schedule) => (
                <Switch
                    checked={Boolean(schedule.enabled)}
                    onCheckedChange={() => onToggle(schedule)}
                    aria-label={`${schedule.enabled ? 'Disable' : 'Enable'} ${schedule.name}`}
                />
            ),
        },
        {
            key: 'actions',
            header: '',
            sortable: false,
            hideable: false,
            render: (schedule) => (
                <div className="bk-actions">
                    {onRun && (
                        <button
                            type="button"
                            className="bk-iconbtn"
                            onClick={() => onRun(schedule)}
                            title="Run this policy now"
                            aria-label={`Run ${schedule.name} now`}
                        >
                            <Play size={15} />
                        </button>
                    )}
                    <button
                        type="button"
                        className="bk-iconbtn bk-iconbtn--danger"
                        onClick={() => onRemove(schedule.id)}
                        title="Delete this policy"
                        aria-label={`Delete ${schedule.name}`}
                    >
                        <Trash2 size={15} />
                    </button>
                </div>
            ),
        },
    ];

    return (
        <>
            <div className="bk-card">
                <DataTable
                    columns={columns}
                    data={schedules}
                    keyField="id"
                    storageKey="serverkit-table-backup-schedules"
                    rowClassName={(schedule) => (schedule.enabled ? undefined : 'is-off')}
                    tableClassName="bk-table bk-table--schedules"
                    footer={(
                        <DataTableFooter
                            shown={schedules.length}
                            total={schedules.length}
                            noun="schedule"
                        />
                    )}
                />
            </div>
            <p className="bk-hint bk-hint--foot">
                <ShieldCheck size={13} />
                Snapshots older than {retentionDays} days are pruned automatically. Per-resource
                policies (with their own retention) are set on each site or database.
            </p>
        </>
    );
}
