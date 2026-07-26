import { useState, useEffect } from 'react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useConfirm } from '../hooks/useConfirm';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import {
    Clock, CheckCircle, Monitor, Activity, Plus, RefreshCw,
    Play, Pause, Pencil, Trash2, Search,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { MetricCard, Pill, SegControl, PageTopbar } from '@/components/ds';

const CronJobs = () => {
    const toast = useToast();
    const { confirm } = useConfirm();
    const [status, setStatus] = useState(null);
    const [jobs, setJobs] = useState([]);
    const [presets, setPresets] = useState({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // List filters (client-side, over already-loaded jobs)
    const [filter, setFilter] = useState('all');
    const [query, setQuery] = useState('');

    // Modal states
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
        preset: 'daily'
    });

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        try {
            setLoading(true);
            const [statusRes, jobsRes, presetsRes] = await Promise.all([
                api.getCronStatus(),
                api.getCronJobs(),
                api.getCronPresets()
            ]);

            setStatus(statusRes);
            setJobs(jobsRes.jobs || []);
            setPresets(presetsRes.presets || {});
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
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
            preset: presetKey || 'daily'
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
            const schedule = jobForm.usePreset
                ? presets[jobForm.preset]
                : jobForm.schedule;

            const payload = {
                name: jobForm.name,
                command: jobForm.command,
                schedule: schedule,
                description: jobForm.description
            };

            if (editingJob) {
                await api.updateCronJob(editingJob.id, payload);
                toast.success('Cron job updated successfully');
            } else {
                await api.createCronJob(payload);
                toast.success('Cron job created successfully');
            }

            closeJobModal();
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleDeleteJob = async (jobId) => {
        const confirmed = await confirm({ title: 'Delete Cron Job', message: 'Are you sure you want to delete this cron job?' });
        if (!confirmed) return;
        try {
            await api.deleteCronJob(jobId);
            toast.success('Cron job deleted');
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
                    stderr: result.stderr
                });
            } else {
                toast.error(result.error || 'Job execution failed');
            }
        } catch (err) {
            toast.error(err.message);
        } finally {
            setRunningJobId(null);
        }
    };

    const resetForm = () => {
        setJobForm({
            name: '',
            command: '',
            schedule: '',
            description: '',
            usePreset: true,
            preset: 'daily'
        });
    };

    const getScheduleDescription = (schedule) => {
        const descriptions = {
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
            '*/30 * * * *': 'Every 30 minutes'
        };
        return descriptions[schedule] || schedule;
    };

    const enabledCount = jobs.filter(j => j.enabled).length;
    const disabledCount = jobs.length - enabledCount;

    const serviceSub = status?.type === 'cron'
        ? (status?.running ? 'daemon running' : 'daemon stopped')
        : (status?.type === 'serverkit_scheduler' ? 'internal scheduler' : null);

    const q = query.trim().toLowerCase();
    const shownJobs = jobs.filter(job => (
        (filter === 'all' || (filter === 'enabled' ? job.enabled : !job.enabled))
        && (!q
            || (job.name || '').toLowerCase().includes(q)
            || (job.command || '').toLowerCase().includes(q))
    ));

    if (loading) {
        return (
            <div className="page-container cron-page">
                <EmptyState loading loadingVariant="table" size="lg" title="Loading cron jobs..." />
            </div>
        );
    }

    return (
        <div className="page-container cron-page">
            <PageTopbar
                icon={<Clock size={18} />}
                title="Cron Jobs"
                actions={(
                    <>
                        <Button variant="outline" onClick={loadData}>
                            <RefreshCw size={15} />
                            Refresh
                        </Button>
                        <Button onClick={openCreateModal}>
                            <Plus size={15} />
                            Create Job
                        </Button>
                    </>
                )}
            />

            {error && (
                <div className="alert alert-danger">
                    {error}
                    <button type="button" onClick={() => setError(null)} className="alert-close">&times;</button>
                </div>
            )}

            {/* KPI strip */}
            <div className="cron-kpis">
                <MetricCard tone="accent" icon={<Clock size={16} />} value={jobs.length} label="Cron jobs">
                    <div className="sk-kpi__sub"><span>{enabledCount} enabled</span></div>
                </MetricCard>
                <MetricCard tone="green" icon={<CheckCircle size={16} />} value={enabledCount} label="Active jobs">
                    {disabledCount > 0 && (
                        <div className="sk-kpi__sub"><span>{disabledCount} disabled</span></div>
                    )}
                </MetricCard>
                <MetricCard
                    tone={status?.available ? 'green' : 'amber'}
                    icon={<Activity size={16} />}
                    value={status?.available ? 'Available' : 'Not Available'}
                    label="Cron service"
                >
                    {serviceSub && (
                        <div className="sk-kpi__sub"><span>{serviceSub}</span></div>
                    )}
                </MetricCard>
                <MetricCard tone="cyan" icon={<Monitor size={16} />} value={status?.platform || 'Unknown'} label="Platform" />
            </div>

            {/* Jobs list */}
            {jobs.length === 0 ? (
                <EmptyState
                    icon={Clock}
                    title="No Cron Jobs"
                    description="No scheduled jobs found. Create your first cron job to automate tasks."
                    action={<Button onClick={openCreateModal}>Create Job</Button>}
                />
            ) : (
                <>
                    <div className="cron-listhead">
                        <h2>Scheduled jobs</h2>
                        <div className="cron-search">
                            <Search size={15} />
                            <input
                                type="text"
                                placeholder="Search jobs or commands…"
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                            />
                        </div>
                        <SegControl
                            value={filter}
                            onChange={setFilter}
                            options={[
                                { value: 'all', label: 'All' },
                                { value: 'enabled', label: 'Enabled' },
                                { value: 'disabled', label: 'Disabled' },
                            ]}
                        />
                    </div>

                    {shownJobs.length === 0 ? (
                        <div className="cron-empty">No jobs match the current filter.</div>
                    ) : (
                        <div className="cron-card">
                            <table className="sk-dtable cron-table">
                                <thead>
                                    <tr>
                                        <th>Job</th>
                                        <th>Schedule</th>
                                        <th>Status</th>
                                        <th aria-label="Actions" />
                                    </tr>
                                </thead>
                                <tbody>
                                    {shownJobs.map((job) => {
                                        const readable = getScheduleDescription(job.schedule);
                                        return (
                                            <tr
                                                key={job.id}
                                                className={`is-clickable${job.enabled ? '' : ' is-disabled'}`}
                                                onClick={() => openEditModal(job)}
                                            >
                                                <td>
                                                    <div className="sk-cell-name">
                                                        <span className="cron-ico"><Clock size={15} /></span>
                                                        <div className="cron-jobcell">
                                                            <div className="cron-jobcell__name">{job.name || 'Unnamed Job'}</div>
                                                            {job.description && (
                                                                <div className="cron-jobcell__desc">{job.description}</div>
                                                            )}
                                                            <div className="sk-cell-sub cron-jobcell__cmd" title={job.command}>
                                                                {job.command}
                                                            </div>
                                                        </div>
                                                    </div>
                                                </td>
                                                <td>
                                                    <span className="cron-sched"><Clock size={11} />{job.schedule}</span>
                                                    {readable !== job.schedule && (
                                                        <div className="cron-sched-readable">{readable}</div>
                                                    )}
                                                </td>
                                                <td>
                                                    <Pill kind={job.enabled ? 'green' : 'gray'}>
                                                        {job.enabled ? 'Enabled' : 'Disabled'}
                                                    </Pill>
                                                </td>
                                                <td onClick={e => e.stopPropagation()}>
                                                    <div className="cron-actions">
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() => handleRunJob(job.id)}
                                                            disabled={runningJobId === job.id}
                                                            title="Run now"
                                                        >
                                                            {runningJobId === job.id ? (
                                                                <span className="spinner-inline"></span>
                                                            ) : (
                                                                <Play size={14} />
                                                            )}
                                                        </Button>
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() => openEditModal(job)}
                                                            title="Edit"
                                                        >
                                                            <Pencil size={14} />
                                                        </Button>
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() => handleToggleJob(job.id, job.enabled)}
                                                            title={job.enabled ? 'Disable' : 'Enable'}
                                                        >
                                                            {job.enabled ? <Pause size={14} /> : <Play size={14} />}
                                                        </Button>
                                                        <Button
                                                            variant="destructive"
                                                            size="sm"
                                                            onClick={() => handleDeleteJob(job.id)}
                                                            title="Delete"
                                                        >
                                                            <Trash2 size={14} />
                                                        </Button>
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}

            {/* Create/Edit Job Modal */}
            <Modal open={showJobModal} onClose={closeJobModal} title={editingJob ? 'Edit Cron Job' : 'Create Cron Job'}>
                        <form onSubmit={handleSubmitJob}>
                                <div className="form-group">
                                    <Label htmlFor="job-name">Job Name</Label>
                                    <Input
                                        id="job-name"
                                        type="text"
                                        value={jobForm.name}
                                        onChange={(e) => setJobForm({...jobForm, name: e.target.value})}
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
                                        onChange={(e) => setJobForm({...jobForm, command: e.target.value})}
                                        placeholder="/usr/bin/backup.sh"
                                        required
                                    />
                                    <span className="form-help">The command or script to execute</span>
                                </div>

                                <div className="form-group">
                                    <label className="checkbox-label">
                                        <Checkbox
                                            checked={jobForm.usePreset}
                                            onCheckedChange={(checked) => setJobForm({...jobForm, usePreset: !!checked})}
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
                                            onChange={(e) => setJobForm({...jobForm, preset: e.target.value})}
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
                                            onChange={(e) => setJobForm({...jobForm, schedule: e.target.value})}
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
                                        onChange={(e) => setJobForm({...jobForm, description: e.target.value})}
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

export default CronJobs;
