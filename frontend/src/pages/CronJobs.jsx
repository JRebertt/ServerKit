import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';
import { useConfirm } from '../hooks/useConfirm';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import {
    Clock, Plus, RefreshCw, Play, Pause, Trash2, Pencil,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Switch } from '@/components/ui/switch';
import { Pill, SegControl, SearchField, PageTopbar, DataTable, Drawer } from '@/components/ds';

// Fallback humanizer for the handful of schedules the backend can't describe.
const SCHEDULE_LABELS = {
    '* * * * *': 'Every minute',
    '0 * * * *': 'Every hour',
    '0 0 * * *': 'Daily at midnight',
    '0 0 * * 0': 'Weekly on Sunday',
    '0 0 1 * *': 'Monthly on the 1st',
    '0 0 * * 1-5': 'Weekdays at midnight',
    '0 */6 * * *': 'Every 6 hours',
    '0 */12 * * *': 'Every 12 hours',
    '*/5 * * * *': 'Every 5 minutes',
    '*/15 * * * *': 'Every 15 minutes',
    '*/30 * * * *': 'Every 30 minutes',
};

const describeSchedule = (job) => (
    job.schedule_human || SCHEDULE_LABELS[job.schedule] || job.schedule
);

// The browser's zone, not the host's — times are ISO strings rendered client
// side, so this is what the reader is actually seeing. Say so rather than
// implying the schedule's own timezone.
const VIEWER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'local time';

function formatWhen(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const diffMs = Date.now() - d.getTime();
    const mins = Math.round(Math.abs(diffMs) / 60000);
    const ago = diffMs >= 0;
    let rel;
    if (mins < 1) rel = 'just now';
    else if (mins < 60) rel = `${mins}m`;
    else if (mins < 1440) rel = `${Math.round(mins / 60)}h`;
    else rel = `${Math.round(mins / 1440)}d`;
    if (rel === 'just now') return rel;
    return ago ? `${rel} ago` : `in ${rel}`;
}

function formatDuration(seconds) {
    if (seconds == null) return '—';
    if (seconds < 10) return `${Number(seconds).toFixed(1)}s`;
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${String(s).padStart(2, '0')}s`;
}

// One status per job, folding "is it on?" and "did it last succeed?" together —
// the two questions the list exists to answer.
function jobState(job) {
    if (!job.enabled) return { key: 'paused', kind: 'gray', label: 'Paused' };
    if (job.last_status === 'failure') return { key: 'failed', kind: 'red', label: 'Failed' };
    if (job.last_status === 'success') return { key: 'active', kind: 'green', label: 'Healthy' };
    // Enabled but nothing recorded: either never fired yet, or not tracked.
    return { key: 'active', kind: 'cyan', label: job.tracked ? 'No runs yet' : 'Untracked' };
}

const CronJobs = () => {
    const toast = useToast();
    const { isAdmin } = useAuth();
    const { confirm } = useConfirm();
    const [status, setStatus] = useState(null);
    const [jobs, setJobs] = useState([]);
    const [presets, setPresets] = useState({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // List filters (client-side, over already-loaded jobs)
    const [filter, setFilter] = useState('all');
    const [search, setSearch] = useState('');

    // Drawer + modal states
    const [drawerJob, setDrawerJob] = useState(null);
    const [showJobModal, setShowJobModal] = useState(false);
    const [editingJob, setEditingJob] = useState(null);
    const [runningJobId, setRunningJobId] = useState(null);
    const [runOutput, setRunOutput] = useState(null);

    // Form state
    const [jobForm, setJobForm] = useState({
        name: '',
        command: '',
        schedule: '',
        description: '',
        usePreset: true,
        preset: 'daily',
    });

    const loadData = useCallback(async () => {
        try {
            setLoading(true);
            const [statusRes, jobsRes, presetsRes] = await Promise.all([
                api.getCronStatus(),
                api.getCronJobs(),
                api.getCronPresets(),
            ]);
            setStatus(statusRes);
            setJobs(jobsRes.jobs || []);
            setPresets(presetsRes.presets || {});
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadData();
    }, [loadData]);

    const resetForm = () => {
        setJobForm({
            name: '',
            command: '',
            schedule: '',
            description: '',
            usePreset: true,
            preset: 'daily',
        });
    };

    const openCreateModal = () => {
        setEditingJob(null);
        resetForm();
        setShowJobModal(true);
    };

    const openEditModal = (job) => {
        setEditingJob(job);
        const presetKey = Object.entries(presets).find(([, v]) => v === job.schedule)?.[0];
        setJobForm({
            name: job.name || '',
            command: job.command || '',
            schedule: job.schedule || '',
            description: job.description || '',
            usePreset: !!presetKey,
            preset: presetKey || 'daily',
        });
        setShowJobModal(true);
    };

    const closeJobModal = () => {
        setShowJobModal(false);
        setEditingJob(null);
        resetForm();
    };

    const handleSubmitJob = async (e) => {
        e.preventDefault();
        try {
            const schedule = jobForm.usePreset ? presets[jobForm.preset] : jobForm.schedule;
            const payload = {
                name: jobForm.name,
                command: jobForm.command,
                schedule,
                description: jobForm.description,
            };

            if (editingJob) {
                await api.updateCronJob(editingJob.id, payload);
                toast.success('Cron job updated successfully');
            } else {
                await api.createCronJob(payload);
                toast.success('Cron job created successfully');
            }

            closeJobModal();
            setDrawerJob(null);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleDeleteJob = async (jobId) => {
        const confirmed = await confirm({
            title: 'Delete Cron Job',
            message: 'Are you sure you want to delete this cron job?',
        });
        if (!confirmed) return;
        try {
            await api.deleteCronJob(jobId);
            toast.success('Cron job deleted');
            setDrawerJob(null);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleToggleJob = async (jobId, currentEnabled) => {
        try {
            await api.toggleCronJob(jobId, !currentEnabled);
            toast.success(`Cron job ${!currentEnabled ? 'enabled' : 'disabled'}`);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleRunJob = async (jobId) => {
        try {
            setRunningJobId(jobId);
            const result = await api.runCronJob(jobId);
            if (result.success) {
                setRunOutput({
                    jobId,
                    jobName: jobs.find(j => j.id === jobId)?.name || jobId,
                    exitCode: result.exit_code,
                    stdout: result.stdout,
                    stderr: result.stderr,
                });
                loadData();
            } else {
                toast.error(result.error || 'Job execution failed');
            }
        } catch (err) {
            toast.error(err.message);
        } finally {
            setRunningJobId(null);
        }
    };

    const enabledCount = jobs.filter(j => j.enabled).length;
    const failedCount = jobs.filter(j => j.enabled && j.last_status === 'failure').length;
    const pausedCount = jobs.length - enabledCount;

    const q = search.trim().toLowerCase();
    const shown = jobs.filter((job) => {
        const state = jobState(job);
        const matchesFilter = filter === 'all'
            || (filter === 'failed' ? state.key === 'failed'
                : filter === 'paused' ? state.key === 'paused'
                    : state.key === 'active');
        const matchesQuery = !q
            || (job.name || '').toLowerCase().includes(q)
            || (job.command || '').toLowerCase().includes(q);
        return matchesFilter && matchesQuery;
    });

    const filterOptions = [
        { value: 'all', label: 'All', count: jobs.length },
        { value: 'active', label: 'Active', count: enabledCount - failedCount },
        { value: 'failed', label: 'Failed', count: failedCount },
        { value: 'paused', label: 'Paused', count: pausedCount },
    ];

    const serviceNote = status?.available === false
        ? 'Cron service unavailable'
        : status?.type === 'cron'
            ? (status?.running ? null : 'cron daemon stopped')
            : (status?.type === 'serverkit_scheduler' ? 'internal scheduler' : null);

    return (
        <div className="page-container cron-page">
            <PageTopbar
                icon={<Clock size={18} />}
                title="Cron Jobs"
                actions={(
                    <>
                        <Button variant="outline" size="sm" onClick={loadData}>
                            <RefreshCw size={15} /> Refresh
                        </Button>
                        <Button size="sm" onClick={openCreateModal}>
                            <Plus size={15} /> Create job
                        </Button>
                        <SearchField
                            value={search}
                            onSearch={setSearch}
                            placeholder="Search jobs or commands…"
                        />
                    </>
                )}
            />

            {error && (
                <div className="error-banner">
                    {error}
                    <button
                        type="button"
                        className="error-banner__close"
                        onClick={() => setError(null)}
                        aria-label="Dismiss error"
                    >
                        ×
                    </button>
                </div>
            )}

            {loading ? (
                <EmptyState loading loadingVariant="table" title="Loading cron jobs..." />
            ) : jobs.length === 0 ? (
                <EmptyState
                    icon={Clock}
                    title="No cron jobs"
                    description="No scheduled jobs found. Create your first cron job to automate tasks."
                    action={<Button onClick={openCreateModal}><Plus size={16} /> Create job</Button>}
                />
            ) : (
                <div className="cron-body">
                    {/* No KPI strip: every number it carried is already on the
                        segment you'd click to act on it (mirrors /domains). */}
                    <div className="cron-listhead">
                        <SegControl value={filter} onChange={setFilter} options={filterOptions} />
                        {serviceNote && <span className="cron-servicenote">{serviceNote}</span>}
                    </div>

                    {shown.length === 0 ? (
                        <div className="cron-empty">
                            {q ? `No jobs match “${search.trim()}”.` : 'No jobs match this filter.'}
                        </div>
                    ) : (
                        <div className="cron-card">
                            <DataTable
                                tableClassName="sk-dtable cron-table"
                                sortable={false}
                                data={shown}
                                keyField="id"
                                onRowClick={setDrawerJob}
                                rowClassName={(job) => (job.enabled ? undefined : 'is-disabled')}
                                columns={[
                                    {
                                        key: 'name',
                                        header: 'Job',
                                        render: (job) => (
                                            <div className="sk-cell-name">
                                                <span className="cron-ico"><Clock size={15} /></span>
                                                <div className="cron-jobcell">
                                                    <div className="cron-jobcell__name">
                                                        {job.name || 'Unnamed job'}
                                                    </div>
                                                    <div className="sk-cell-sub cron-jobcell__cmd" title={job.command}>
                                                        {job.command}
                                                    </div>
                                                </div>
                                            </div>
                                        ),
                                    },
                                    {
                                        key: 'schedule',
                                        header: 'Schedule',
                                        render: (job) => (
                                            <>
                                                <span className="cron-sched">
                                                    <Clock size={11} />{job.schedule}
                                                </span>
                                                <div className="cron-sched-readable">
                                                    {describeSchedule(job)}
                                                </div>
                                            </>
                                        ),
                                    },
                                    {
                                        key: 'last_run',
                                        header: 'Last run',
                                        cellClassName: 'cron-cell-mono',
                                        render: (job) => formatWhen(job.last_run),
                                    },
                                    {
                                        key: 'next_run',
                                        header: 'Next run',
                                        cellClassName: 'cron-cell-mono',
                                        render: (job) => (
                                            job.enabled ? formatWhen(job.next_run) : 'paused'
                                        ),
                                    },
                                    {
                                        key: 'status',
                                        header: 'Status',
                                        render: (job) => {
                                            const state = jobState(job);
                                            return <Pill kind={state.kind}>{state.label}</Pill>;
                                        },
                                    },
                                    {
                                        key: 'enabled',
                                        header: 'On',
                                        render: (job) => (
                                            <span
                                                className="cron-switch"
                                                onClick={(e) => e.stopPropagation()}
                                                role="presentation"
                                            >
                                                <Switch
                                                    checked={!!job.enabled}
                                                    onCheckedChange={() => handleToggleJob(job.id, job.enabled)}
                                                    aria-label={job.enabled ? 'Disable job' : 'Enable job'}
                                                />
                                            </span>
                                        ),
                                    },
                                    {
                                        key: 'run',
                                        header: '',
                                        cellClassName: 'cron-cell-actions',
                                        render: (job) => (
                                            <span onClick={(e) => e.stopPropagation()} role="presentation">
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => handleRunJob(job.id)}
                                                    disabled={runningJobId === job.id}
                                                    title="Run now"
                                                >
                                                    {runningJobId === job.id
                                                        ? <span className="spinner-inline" />
                                                        : <Play size={14} />}
                                                </Button>
                                            </span>
                                        ),
                                    },
                                ]}
                            />
                        </div>
                    )}

                    <div className="cron-tznote">
                        <Clock size={13} /> Times shown in your local timezone · {VIEWER_TZ}
                    </div>
                </div>
            )}

            <CronDrawer
                job={drawerJob}
                isAdmin={isAdmin}
                running={drawerJob ? runningJobId === drawerJob.id : false}
                onClose={() => setDrawerJob(null)}
                onRefresh={loadData}
                onRun={handleRunJob}
                onEdit={(j) => { setDrawerJob(null); openEditModal(j); }}
                onDelete={handleDeleteJob}
                onToggle={handleToggleJob}
            />

            {/* Create/Edit Job Modal */}
            <Modal open={showJobModal} onClose={closeJobModal} title={editingJob ? 'Edit Cron Job' : 'Create Cron Job'}>
                <form onSubmit={handleSubmitJob}>
                    <div className="form-group">
                        <Label htmlFor="job-name">Job Name</Label>
                        <Input
                            id="job-name"
                            type="text"
                            value={jobForm.name}
                            onChange={(e) => setJobForm({ ...jobForm, name: e.target.value })}
                            placeholder="My Backup Job"
                            required
                        />
                    </div>

                    <div className="form-group">
                        <Label htmlFor="job-command">Command</Label>
                        <Input
                            id="job-command"
                            type="text"
                            value={jobForm.command}
                            onChange={(e) => setJobForm({ ...jobForm, command: e.target.value })}
                            placeholder="/usr/bin/backup.sh"
                            required
                        />
                        <span className="form-help">The command or script to execute</span>
                    </div>

                    <div className="form-group">
                        <label className="checkbox-label">
                            <Checkbox
                                checked={jobForm.usePreset}
                                onCheckedChange={(checked) => setJobForm({ ...jobForm, usePreset: !!checked })}
                            />
                            <span>Use preset schedule</span>
                        </label>
                    </div>

                    {jobForm.usePreset ? (
                        <div className="form-group">
                            <Label htmlFor="job-preset">Schedule Preset</Label>
                            <select
                                id="job-preset"
                                value={jobForm.preset}
                                onChange={(e) => setJobForm({ ...jobForm, preset: e.target.value })}
                            >
                                {Object.entries(presets).map(([key, value]) => (
                                    <option key={key} value={key}>
                                        {key.replace(/_/g, ' ')} ({value})
                                    </option>
                                ))}
                            </select>
                        </div>
                    ) : (
                        <div className="form-group">
                            <Label htmlFor="job-schedule">Cron Schedule</Label>
                            <Input
                                id="job-schedule"
                                type="text"
                                value={jobForm.schedule}
                                onChange={(e) => setJobForm({ ...jobForm, schedule: e.target.value })}
                                placeholder="0 0 * * *"
                                required={!jobForm.usePreset}
                            />
                            <span className="form-help">
                                Format: minute hour day month weekday (e.g., &quot;0 0 * * *&quot; for daily at midnight)
                            </span>
                        </div>
                    )}

                    <div className="form-group">
                        <Label htmlFor="job-description">Description (optional)</Label>
                        <Textarea
                            id="job-description"
                            value={jobForm.description}
                            onChange={(e) => setJobForm({ ...jobForm, description: e.target.value })}
                            placeholder="What does this job do?"
                            rows={2}
                        />
                    </div>
                    <div className="modal-actions">
                        <Button type="button" variant="outline" onClick={closeJobModal}>
                            Cancel
                        </Button>
                        <Button type="submit">
                            {editingJob ? 'Save Changes' : 'Create Job'}
                        </Button>
                    </div>
                </form>
            </Modal>

            {/* Run Output Modal */}
            <Modal open={!!runOutput} onClose={() => setRunOutput(null)} title={runOutput ? `Run Output: ${runOutput.jobName}` : ''}>
                {runOutput && (
                    <div className="run-output">
                        <div className="run-output-exit">
                            <span className="run-output-label">Exit Code</span>
                            <Pill kind={runOutput.exitCode === 0 ? 'green' : 'red'}>
                                {runOutput.exitCode}
                            </Pill>
                        </div>
                        {runOutput.stdout && (
                            <div className="run-output-section">
                                <span className="run-output-label">stdout</span>
                                <pre className="run-output-pre">{runOutput.stdout}</pre>
                            </div>
                        )}
                        {runOutput.stderr && (
                            <div className="run-output-section">
                                <span className="run-output-label">stderr</span>
                                <pre className="run-output-pre run-output-pre--error">{runOutput.stderr}</pre>
                            </div>
                        )}
                        {!runOutput.stdout && !runOutput.stderr && (
                            <p className="text-muted">No output produced.</p>
                        )}
                    </div>
                )}
                <div className="modal-actions">
                    <Button variant="outline" onClick={() => setRunOutput(null)}>Close</Button>
                </div>
            </Modal>
        </div>
    );
};

// Row-click drawer: the job's configuration plus its recorded run history.
// History comes from GET /cron/jobs/<id>/runs, which is admin-only and only
// returns anything for jobs whose crontab line carries the tracking shim — both
// of which are surfaced rather than silently rendering an empty table.
function CronDrawer({ job, isAdmin, running, onClose, onRefresh, onRun, onEdit, onDelete, onToggle }) {
    const toast = useToast();
    const [history, setHistory] = useState(null);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [trackingBusy, setTrackingBusy] = useState(false);

    const loadHistory = useCallback(async (jobId) => {
        setHistoryLoading(true);
        try {
            const res = await api.getCronJobRuns(jobId);
            setHistory({ runs: res.runs || [], stats: res.stats || {} });
        } catch {
            // Non-admin (403) or a transient failure: fall back to the
            // config-only drawer rather than blocking it behind an error.
            setHistory(null);
        } finally {
            setHistoryLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!job || !isAdmin) {
            setHistory(null);
            return;
        }
        loadHistory(job.id);
    }, [job, isAdmin, loadHistory]);

    // The Drawer stays mounted with open={!!job} (same as /domains) so closing
    // it plays the slide-out instead of vanishing; the body is what unmounts.
    const state = job ? jobState(job) : { kind: 'gray', label: '' };
    const stats = history?.stats || {};
    const runs = history?.runs || [];
    const lastOutput = runs.find(r => r.output_tail)?.output_tail;
    const successRate = stats.success_rate == null ? null : Math.round(stats.success_rate * 1000) / 10;
    const rateTone = successRate == null ? 'none'
        : successRate > 99 ? 'good'
            : successRate > 95 ? 'warn' : 'bad';

    const handleTracking = async () => {
        setTrackingBusy(true);
        try {
            await api.setCronTracking(job.id, { enabled: !job.tracked });
            toast.success(job.tracked ? 'Run tracking disabled' : 'Run tracking enabled');
            onClose();
            onRefresh?.();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setTrackingBusy(false);
        }
    };

    return (
        <Drawer
            open={!!job}
            onOpenChange={(open) => { if (!open) onClose(); }}
            title={job?.name || 'Unnamed job'}
            subtitle={job ? `${job.schedule} · ${describeSchedule(job)}` : ''}
            icon={<Clock size={18} />}
            width={640}
            headerExtra={job && (
                <div className="cron-drawer__headeractions">
                    <Button
                        size="sm"
                        onClick={() => onRun(job.id)}
                        disabled={running}
                    >
                        {running ? <span className="spinner-inline" /> : <Play size={14} />} Run now
                    </Button>
                </div>
            )}
        >
            {job && (
            <div className="cron-drawer">
                <section className="cron-drawer__section">
                    <h3 className="cron-drawer__sectiontitle">Configuration</h3>
                    <div className="cron-drawer__info">
                        <div className="cron-inforow">
                            <span className="k">Schedule</span>
                            <span className="v">{job.schedule}</span>
                        </div>
                        <div className="cron-inforow">
                            <span className="k">Command</span>
                            <span className="v cron-inforow__cmd">{job.command}</span>
                        </div>
                        {job.description && (
                            <div className="cron-inforow">
                                <span className="k">Description</span>
                                <span className="v">{job.description}</span>
                            </div>
                        )}
                        <div className="cron-inforow">
                            <span className="k">Next run</span>
                            <span className="v">{job.enabled ? formatWhen(job.next_run) : 'paused'}</span>
                        </div>
                        <div className="cron-inforow">
                            <span className="k">Status</span>
                            <span className="v"><Pill kind={state.kind}>{state.label}</Pill></span>
                        </div>
                    </div>
                </section>

                <section className="cron-drawer__section">
                    <h3 className="cron-drawer__sectiontitle">Run history</h3>

                    {!isAdmin ? (
                        <p className="cron-drawer__hint">
                            Run history is an admin-only surface.
                        </p>
                    ) : !job.tracked ? (
                        <div className="cron-drawer__tracking">
                            <p className="cron-drawer__hint">
                                Run tracking is off for this job, so nothing is recorded. Turning it
                                on rewrites the crontab line to report each run&apos;s exit code,
                                duration, and output tail.
                            </p>
                            <Button variant="outline" size="sm" onClick={handleTracking} disabled={trackingBusy}>
                                {trackingBusy ? 'Enabling…' : 'Enable run tracking'}
                            </Button>
                        </div>
                    ) : historyLoading ? (
                        <EmptyState loading loadingVariant="table" title="Loading run history..." />
                    ) : runs.length === 0 ? (
                        <p className="cron-drawer__hint">No runs recorded yet.</p>
                    ) : (
                        <>
                            <div className="cron-specs">
                                <div className="cron-spec">
                                    <div className="l">Success rate</div>
                                    <div className={`v v--${rateTone}`}>
                                        {successRate == null ? '—' : `${successRate}%`}
                                    </div>
                                    <div className="s">
                                        {stats.failure || 0} failed of last {stats.total || 0}
                                    </div>
                                </div>
                                <div className="cron-spec">
                                    <div className="l">Last run</div>
                                    <div className="v">{formatWhen(stats.last_run)}</div>
                                    <div className="s">{stats.last_status || 'unknown'}</div>
                                </div>
                                <div className="cron-spec">
                                    <div className="l">Cadence</div>
                                    <div className="v">{describeSchedule(job)}</div>
                                    <div className="s">next {job.enabled ? formatWhen(job.next_run) : 'paused'}</div>
                                </div>
                            </div>

                            <div className="cron-drawer__table">
                                <DataTable
                                    tableClassName="sk-dtable"
                                    sortable={false}
                                    data={runs}
                                    keyField="id"
                                    columns={[
                                        {
                                            key: 'when',
                                            header: 'When',
                                            render: (r) => formatWhen(r.finished_at || r.started_at),
                                        },
                                        {
                                            key: 'duration',
                                            header: 'Duration',
                                            render: (r) => formatDuration(r.duration_seconds),
                                        },
                                        {
                                            key: 'exit',
                                            header: 'Exit',
                                            render: (r) => (
                                                <span className={r.exit_code ? 'cron-exit--bad' : undefined}>
                                                    {r.exit_code ?? '—'}
                                                </span>
                                            ),
                                        },
                                        {
                                            key: 'status',
                                            header: 'Status',
                                            render: (r) => (
                                                <Pill kind={r.status === 'success' ? 'green' : 'red'}>
                                                    {r.status}
                                                </Pill>
                                            ),
                                        },
                                    ]}
                                />
                            </div>
                        </>
                    )}
                </section>

                {lastOutput && (
                    <section className="cron-drawer__section">
                        <h3 className="cron-drawer__sectiontitle">Last output</h3>
                        <pre className="run-output-pre">{lastOutput}</pre>
                    </section>
                )}

                <section className="cron-drawer__section cron-drawer__danger">
                    <div className="cron-drawer__actions">
                        <Button variant="outline" size="sm" onClick={() => onEdit(job)}>
                            <Pencil size={14} /> Edit
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => onToggle(job.id, job.enabled)}>
                            {job.enabled ? <><Pause size={14} /> Disable</> : <><Play size={14} /> Enable</>}
                        </Button>
                        {job.tracked && (
                            <Button variant="outline" size="sm" onClick={handleTracking} disabled={trackingBusy}>
                                {trackingBusy ? 'Disabling…' : 'Disable run tracking'}
                            </Button>
                        )}
                        <Button variant="destructive" size="sm" onClick={() => onDelete(job.id)}>
                            <Trash2 size={14} /> Delete
                        </Button>
                    </div>
                </section>
            </div>
            )}
        </Drawer>
    );
}

export default CronJobs;
