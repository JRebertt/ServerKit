import { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { DataTable, DataTableFooter, Pill } from '../ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import EmptyState from '../EmptyState';
import { Clock3 } from 'lucide-react';
import Modal from '@/components/Modal';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    PRESET_LABELS,
    OfflineIcon,
    StopIcon,
    PlayIcon,
    TrashIcon,
} from './serverDetailShared';

const CronTab = ({ serverId, serverStatus }) => {
    const toast = useToast();
    const { confirm: confirmCron } = useConfirm();
    const [status, setStatus] = useState(null);
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [showAddModal, setShowAddModal] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [form, setForm] = useState({
        name: '',
        schedule: '0 * * * *',
        command: '',
    });
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-sd-cron-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-sd-cron-cols' });

    const loadJobs = useCallback(async () => {
        try {
            const data = await api.getRemoteCronJobs(serverId);
            setJobs(data?.jobs || []);
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load cron jobs');
        }
    }, [serverId]);

    const loadStatus = useCallback(async () => {
        try {
            const s = await api.getRemoteCronStatus(serverId);
            setStatus(s);
        } catch (err) {
            // Non-critical — log but don't block the table.
            console.error('Failed to load cron status:', err);
        }
    }, [serverId]);

    useEffect(() => {
        if (serverStatus !== 'online') {
            setLoading(false);
            return;
        }
        let cancelled = false;
        (async () => {
            setLoading(true);
            await Promise.all([loadJobs(), loadStatus()]);
            if (!cancelled) setLoading(false);
        })();
        return () => { cancelled = true; };
    }, [serverStatus, loadJobs, loadStatus]);

    async function handleToggle(job) {
        try {
            await api.toggleRemoteCronJob(serverId, job.id, !job.enabled);
            toast.success(`Job ${!job.enabled ? 'enabled' : 'disabled'}`);
            loadJobs();
        } catch (err) {
            toast.error(err.message || 'Failed to toggle job');
        }
    }

    async function handleRemove(job) {
        const ok = await confirmCron({
            title: 'Remove Cron Job',
            message: `Remove this entry from the host crontab?\n\n${job.schedule} ${job.command}`,
            variant: 'danger',
        });
        if (!ok) return;
        try {
            await api.removeRemoteCronJob(serverId, job.id);
            toast.success('Cron job removed');
            loadJobs();
        } catch (err) {
            toast.error(err.message || 'Failed to remove job');
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        if (!form.command.trim()) {
            toast.error('Command is required');
            return;
        }
        if (!form.schedule.trim()) {
            toast.error('Schedule is required');
            return;
        }
        setSubmitting(true);
        try {
            await api.addRemoteCronJob(serverId, {
                name: form.name.trim(),
                schedule: form.schedule.trim(),
                command: form.command.trim(),
            });
            toast.success('Cron job added');
            setShowAddModal(false);
            setForm({ name: '', schedule: '0 * * * *', command: '' });
            loadJobs();
        } catch (err) {
            toast.error(err.message || 'Failed to add cron job');
        } finally {
            setSubmitting(false);
        }
    }

    if (serverStatus !== 'online') {
        return (
            <div className="offline-notice">
                <OfflineIcon />
                <h4>Server Offline</h4>
                <p>Cron management requires the server to be online.</p>
            </div>
        );
    }

    if (loading) {
        return <EmptyState loading title="Loading cron jobs" />;
    }

    // Jobs table columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace so the .cron-tab / .data-table SCSS
    // keeps applying (.cron-tab__name, .cron-tab__command, .mono).
    const cronColumns = [
        {
            key: 'schedule',
            header: 'Schedule',
            sortable: true,
            hideable: false,
            sortValue: (job) => job.schedule || '',
            render: (job) => (
                <>
                    <span className="mono" title={job.schedule}>{job.schedule}</span>
                    {job.description && job.description !== job.schedule && (
                        <div className="cron-tab__description">{job.description}</div>
                    )}
                </>
            ),
        },
        {
            key: 'command',
            header: 'Command',
            sortable: true,
            sortValue: (job) => job.command || '',
            render: (job) => (
                <>
                    {job.name && <div className="cron-tab__name">{job.name}</div>}
                    <code className="cron-tab__command">{job.command}</code>
                </>
            ),
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (job) => (job.enabled ? 'enabled' : 'disabled'),
            render: (job) => (
                <Pill kind={job.enabled ? 'green' : 'gray'}>
                    {job.enabled ? 'enabled' : 'disabled'}
                </Pill>
            ),
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            className: 'actions-cell',
            cellClassName: 'actions-cell',
            render: (job) => (
                <>
                    <button type="button"
                        className="btn-icon"
                        onClick={() => handleToggle(job)}
                        title={job.enabled ? 'Disable' : 'Enable'}
                    >
                        {job.enabled ? <StopIcon /> : <PlayIcon />}
                    </button>
                    <button type="button"
                        className="btn-icon danger"
                        onClick={() => handleRemove(job)}
                        title="Remove"
                    >
                        <TrashIcon />
                    </button>
                </>
            ),
        },
    ];

    return (
        <div className="cron-tab">
            <div className="cron-tab__header">
                <div className="cron-tab__status">
                    {status?.available === false ? (
                        <Pill kind="amber">cron not available: {status.reason || 'unknown'}</Pill>
                    ) : status?.running === false ? (
                        <Pill kind="amber">cron daemon not running</Pill>
                    ) : (
                        <Pill kind="green">cron daemon active{status?.daemon ? ` (${status.daemon})` : ''}</Pill>
                    )}
                    <span className="cron-tab__count">{jobs.length} job{jobs.length === 1 ? '' : 's'}</span>
                </div>
                <div className="cron-tab__actions">
                    <Button variant="outline" onClick={loadJobs}>Refresh</Button>
                    <Button onClick={() => setShowAddModal(true)} disabled={status?.available === false}>
                        Add Job
                    </Button>
                </div>
            </div>

            {error && (
                <div className="alert alert-danger">{error}</div>
            )}

            {jobs.length === 0 ? (
                <EmptyState
                    icon={Clock3}
                    title="No cron jobs"
                    description="No scheduled jobs on this server. Use Add Job to schedule one."
                />
            ) : (
                <DataTable
                    columns={cronColumns}
                    data={jobs}
                    keyField="id"
                    sorts={sorts}
                    onSortsChange={setSorts}
                    hiddenKeys={hiddenKeys}
                    onHiddenKeysChange={setHiddenKeys}
                    rowClassName={(job) => (!job.enabled ? 'row-disabled' : '')}
                    tableClassName="data-table"
                    footer={(
                        <DataTableFooter
                            shown={jobs.length}
                            total={jobs.length}
                            noun="job"
                        />
                    )}
                />
            )}

            <Modal
                open={showAddModal}
                onClose={() => { if (!submitting) setShowAddModal(false); }}
                title="Add Cron Job"
            >
                <p className="sk-modal__subtitle">
                    Schedule a command on the host crontab. Runs as the agent user.
                </p>
                <form onSubmit={handleSubmit} className="space-y-4">
                        <div className="space-y-1.5">
                            <Label htmlFor="cron-name">Name (optional)</Label>
                            <Input
                                id="cron-name"
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder="Backup database"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="cron-schedule">Schedule</Label>
                            <Select
                                value={Object.keys(PRESET_LABELS).includes(form.schedule) ? form.schedule : 'custom'}
                                onValueChange={(value) => {
                                    if (value === 'custom') return;
                                    setForm({ ...form, schedule: value });
                                }}
                            >
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {Object.entries(PRESET_LABELS).map(([cron, label]) => (
                                        <SelectItem key={cron} value={cron}>{label} — {cron}</SelectItem>
                                    ))}
                                    <SelectItem value="custom">Custom…</SelectItem>
                                </SelectContent>
                            </Select>
                            <Input
                                id="cron-schedule"
                                value={form.schedule}
                                onChange={(e) => setForm({ ...form, schedule: e.target.value })}
                                placeholder="* * * * *"
                                className="font-mono"
                            />
                            <p className="text-xs text-muted-foreground">5 fields: minute, hour, day, month, weekday.</p>
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="cron-command">Command</Label>
                            <Textarea
                                id="cron-command"
                                rows={3}
                                value={form.command}
                                onChange={(e) => setForm({ ...form, command: e.target.value })}
                                placeholder="/usr/local/bin/my-script.sh"
                                required
                            />
                            <p className="text-xs text-muted-foreground">Absolute path. Shell operators (;, &amp;&amp;, |, $(), &gt;, &lt;) are not allowed.</p>
                        </div>
                        <div className="modal-actions">
                            <Button type="button" variant="outline" onClick={() => setShowAddModal(false)} disabled={submitting}>Cancel</Button>
                            <Button type="submit" disabled={submitting}>{submitting ? 'Adding…' : 'Add Job'}</Button>
                        </div>
                    </form>
            </Modal>
        </div>
    );
};

export default CronTab;
