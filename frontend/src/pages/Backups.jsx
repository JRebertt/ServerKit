import { useState, useEffect } from 'react';
import useTabParam from '../hooks/useTabParam';
import { Upload, Check, AlertTriangle, Archive, Clock, Database, Package, FolderArchive, HardDrive, History, Cloud, RefreshCw, Trash2, Plus, FileArchive, DollarSign } from 'lucide-react';
import api from '../services/api';
import { formatBytes } from '@/utils/formatBytes';
import { useToast } from '../contexts/ToastContext';
import { useConfirm } from '../hooks/useConfirm';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import { FormField, FormRow } from '../components/FormField';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Pill, SearchField, SegControl } from '@/components/ds';
import BackupsOverview from '../components/backups/BackupsOverview';
import SchedulesTable from '../components/backups/SchedulesTable';
import StorageDestinations from '../components/backups/StorageDestinations';
import { useTopbarActions } from '@/hooks/useTopbarActions';

// `backups` is kept as an alias so old /backups/backups links still resolve to
// the archive, which now answers to `snapshots`.
const VALID_TABS = ['overview', 'schedules', 'snapshots', 'storage', 'settings'];
const TAB_ALIASES = { backups: 'snapshots' };

const PROVIDER_LABELS = { local: 'Local only', s3: 'S3-Compatible', b2: 'Backblaze B2' };

const Backups = () => {
    const toast = useToast();
    const { confirm } = useConfirm();
    const [backups, setBackups] = useState([]);
    const [stats, setStats] = useState(null);
    const [schedules, setSchedules] = useState([]);
    const [config, setConfig] = useState(null);
    const [storageConfig, setStorageConfig] = useState(null);
    const [costSummary, setCostSummary] = useState(null);
    const [apps, setApps] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [rawTab, setActiveTab] = useTabParam('/backups', VALID_TABS);
    const activeTab = TAB_ALIASES[rawTab] || rawTab;
    const [filterType, setFilterType] = useState('all');
    const [search, setSearch] = useState('');

    // Modal states
    const [showBackupModal, setShowBackupModal] = useState(false);
    const [showScheduleModal, setShowScheduleModal] = useState(false);
    const [showRestoreModal, setShowRestoreModal] = useState(false);
    const [selectedBackup, setSelectedBackup] = useState(null);
    const [uploadingBackup, setUploadingBackup] = useState(null);
    const [testingConnection, setTestingConnection] = useState(false);

    // Backup form state
    const [backupForm, setBackupForm] = useState({
        type: 'application',
        applicationId: '',
        includeDb: false,
        dbType: 'mysql',
        dbName: '',
        dbUser: '',
        dbPassword: '',
        dbHost: 'localhost',
        filePaths: '',
        fileName: ''
    });

    // Schedule form state
    const [scheduleForm, setScheduleForm] = useState({
        name: '',
        backupType: 'application',
        target: '',
        scheduleTime: '02:00',
        days: ['daily'],
        uploadRemote: false
    });

    // Config form state
    const [configForm, setConfigForm] = useState({
        enabled: false,
        retention_days: 30
    });

    // Cost rates form state ($/GB/month). Local is the operator's own server disk.
    const [ratesForm, setRatesForm] = useState({ local: 0, s3: 0.023, b2: 0.006 });
    const [savingRates, setSavingRates] = useState(false);

    // Storage config form state
    const [storageForm, setStorageForm] = useState({
        provider: 'local',
        s3: { bucket: '', region: 'us-east-1', access_key: '', secret_key: '', endpoint_url: '', path_prefix: 'serverkit-backups' },
        b2: { bucket: '', key_id: '', application_key: '', endpoint_url: '', path_prefix: 'serverkit-backups' },
        auto_upload: false,
        keep_local_copy: true
    });

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        try {
            setLoading(true);
            const [backupsRes, statsRes, schedulesRes, configRes, appsRes, storageRes, costRes, ratesRes] = await Promise.all([
                api.getBackups(),
                api.getBackupStats(),
                api.getBackupSchedules(),
                api.getBackupConfig(),
                api.getApps(),
                api.getStorageConfig().catch(() => null),
                api.getBackupCostSummary().catch(() => null),
                api.getBackupCostRates().catch(() => null)
            ]);

            setBackups(backupsRes.backups || []);
            setStats(statsRes);
            setSchedules(schedulesRes.schedules || []);
            setConfig(configRes);
            setApps(appsRes.applications || []);
            setCostSummary(costRes || null);

            if (storageRes) {
                setStorageConfig(storageRes);
                setStorageForm(storageRes);
            }

            if (ratesRes?.rates) {
                setRatesForm({
                    local: ratesRes.rates.local ?? 0,
                    s3: ratesRes.rates.s3 ?? 0,
                    b2: ratesRes.rates.b2 ?? 0
                });
            }

            if (configRes) {
                setConfigForm({
                    enabled: configRes.enabled || false,
                    retention_days: configRes.retention_days || 30
                });
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleCreateBackup = async (e) => {
        e.preventDefault();
        try {
            if (backupForm.type === 'application') {
                const dbConfig = backupForm.includeDb ? {
                    type: backupForm.dbType,
                    name: backupForm.dbName,
                    user: backupForm.dbUser,
                    password: backupForm.dbPassword,
                    host: backupForm.dbHost
                } : null;
                await api.backupApplication(parseInt(backupForm.applicationId), backupForm.includeDb, dbConfig);
                toast.success('Application backup created');
            } else if (backupForm.type === 'database') {
                await api.backupDatabase(
                    backupForm.dbType,
                    backupForm.dbName,
                    backupForm.dbUser,
                    backupForm.dbPassword,
                    backupForm.dbHost
                );
                toast.success('Database backup created');
            } else if (backupForm.type === 'files') {
                const paths = backupForm.filePaths.split('\n').map(p => p.trim()).filter(Boolean);
                if (paths.length === 0) {
                    toast.error('Enter at least one file path');
                    return;
                }
                await api.backupFiles(paths, backupForm.fileName || null);
                toast.success('File backup created');
            }
            setShowBackupModal(false);
            resetBackupForm();
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleDeleteBackup = async (backupPath) => {
        const confirmed = await confirm({ title: 'Delete Backup', message: 'Are you sure you want to delete this backup?' });
        if (!confirmed) return;
        try {
            await api.deleteBackup(backupPath);
            toast.success('Backup deleted');
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleUploadToRemote = async (backup) => {
        setUploadingBackup(backup.path);
        try {
            await api.uploadBackupToRemote(backup.path);
            toast.success('Backup uploaded to remote storage');
            loadData();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setUploadingBackup(null);
        }
    };

    const handleRestore = async () => {
        if (!selectedBackup) return;
        const restoreConfirmed = await confirm({ title: 'Restore Backup', message: 'Are you sure you want to restore this backup? This may overwrite existing data.', variant: 'warning' });
        if (!restoreConfirmed) return;

        try {
            if (selectedBackup.type === 'application') {
                await api.restoreApplication(selectedBackup.path);
            } else {
                await api.restoreDatabase(
                    selectedBackup.path,
                    selectedBackup.database_type,
                    selectedBackup.database_name
                );
            }
            setShowRestoreModal(false);
            setSelectedBackup(null);
            toast.success('Backup restored successfully');
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleAddSchedule = async (e) => {
        e.preventDefault();
        try {
            await api.addBackupSchedule(
                scheduleForm.name,
                scheduleForm.backupType,
                scheduleForm.target,
                scheduleForm.scheduleTime,
                scheduleForm.days,
                scheduleForm.uploadRemote
            );
            toast.success('Schedule added');
            setShowScheduleModal(false);
            resetScheduleForm();
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleToggleSchedule = async (schedule) => {
        try {
            await api.updateBackupSchedule(schedule.id, { enabled: !schedule.enabled });
            toast.success(`Schedule ${schedule.enabled ? 'disabled' : 'enabled'}`);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleRemoveSchedule = async (scheduleId) => {
        const confirmed = await confirm({ title: 'Remove Schedule', message: 'Are you sure you want to remove this schedule?' });
        if (!confirmed) return;
        try {
            await api.removeBackupSchedule(scheduleId);
            toast.success('Schedule removed');
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleSaveConfig = async (e) => {
        e.preventDefault();
        try {
            await api.updateBackupConfig(configForm);
            toast.success('Settings saved');
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleSaveRates = async (e) => {
        e.preventDefault();
        setSavingRates(true);
        try {
            await api.updateBackupCostRates({
                local: Number(ratesForm.local) || 0,
                s3: Number(ratesForm.s3) || 0,
                b2: Number(ratesForm.b2) || 0
            });
            toast.success('Storage cost rates saved');
            const summary = await api.getBackupCostSummary().catch(() => null);
            setCostSummary(summary || null);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setSavingRates(false);
        }
    };

    const handleSaveStorageConfig = async (e) => {
        e.preventDefault();
        try {
            await api.updateStorageConfig(storageForm);
            toast.success('Storage configuration saved');
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleTestConnection = async () => {
        setTestingConnection(true);
        try {
            const result = await api.testStorageConnection(storageForm);
            if (result.success) {
                toast.success(result.message);
            } else {
                toast.error(result.error);
            }
        } catch (err) {
            toast.error(err.message);
        } finally {
            setTestingConnection(false);
        }
    };

    const handleCleanup = async () => {
        const confirmed = await confirm({ title: 'Cleanup Backups', message: `This will delete backups older than ${configForm.retention_days} days. Continue?`, variant: 'warning' });
        if (!confirmed) return;
        try {
            const result = await api.cleanupBackups(configForm.retention_days);
            toast.success(result.message);
            loadData();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const resetBackupForm = () => {
        setBackupForm({
            type: 'application',
            applicationId: '',
            includeDb: false,
            dbType: 'mysql',
            dbName: '',
            dbUser: '',
            dbPassword: '',
            dbHost: 'localhost',
            filePaths: '',
            fileName: ''
        });
    };

    const resetScheduleForm = () => {
        setScheduleForm({
            name: '',
            backupType: 'application',
            target: '',
            scheduleTime: '02:00',
            days: ['daily'],
            uploadRemote: false
        });
    };

    const formatTimestamp = (timestamp) => {
        return new Date(timestamp).toLocaleString();
    };

    const formatMoney = (n) => {
        const v = Number(n || 0);
        return v === 0 || v >= 0.01 ? `$${v.toFixed(2)}` : `$${v.toFixed(4)}`;
    };

    const getBackupIcon = (type) => {
        switch (type) {
            case 'application': return <Package size={16} />;
            case 'database': return <Database size={16} />;
            case 'files': return <FolderArchive size={16} />;
            default: return <FileArchive size={16} />;
        }
    };

    const getRemoteStatusPill = (status) => {
        switch (status) {
            case 'synced':
                return <Pill kind="green" dot={false}><Cloud size={11} /> Synced</Pill>;
            case 'remote-only':
                return <Pill kind="cyan" dot={false}><Cloud size={11} /> Remote</Pill>;
            default:
                return <Pill kind="gray" dot={false}><HardDrive size={11} /> Local</Pill>;
        }
    };

    // Search narrows first so the segment counts always describe what a click
    // on that segment would actually show.
    const searchedBackups = (() => {
        const q = search.trim().toLowerCase();
        if (!q) return backups;
        return backups.filter(b => (
            (b.name || '').toLowerCase().includes(q)
            || (b.app_name || '').toLowerCase().includes(q)
            || (b.type || '').toLowerCase().includes(q)
        ));
    })();
    const filteredBackups = filterType === 'all'
        ? searchedBackups
        : searchedBackups.filter(b => b.type === filterType);

    // One primary action per section, the way the mock does it: Schedules
    // offers "New schedule", everything else offers "Back up now". A Create
    // Backup button on the Schedules tab was answering a question nobody on
    // that tab was asking.
    useTopbarActions(() => (
        <>
            {activeTab === 'schedules' ? (
                <Button size="sm" onClick={() => setShowScheduleModal(true)}>
                    <Plus size={16} />
                    New schedule
                </Button>
            ) : (
                <Button size="sm" onClick={() => setShowBackupModal(true)}>
                    <Archive size={16} />
                    Back up now
                </Button>
            )}
            {activeTab === 'snapshots' && (
                <SearchField
                    value={search}
                    onSearch={setSearch}
                    placeholder="Search snapshots…"
                />
            )}
        </>
    ), [activeTab, search]);

    if (loading) {
        return (
            <div className="sk-tabgroup__inner backups-page">
                <EmptyState loading loadingVariant="table" size="lg" title="Loading backup data..." />
            </div>
        );
    }

    return (
        <div className="sk-tabgroup__inner backups-page">
            {error && (
                <div className="alert alert-danger">
                    {error}
                    <button type="button" onClick={() => setError(null)} className="alert-close">&times;</button>
                </div>
            )}

            {/* Overview answers "is my data safe?" — the KPI band, the
                activity heatmap, the destinations and the recent feed. The
                archive table it used to sit on top of is now its own section. */}
            {activeTab === 'overview' && (
                <BackupsOverview
                    stats={stats}
                    storageConfig={storageConfig}
                    costSummary={costSummary}
                    schedules={schedules}
                    backups={backups}
                    onGo={setActiveTab}
                />
            )}

            {activeTab === 'snapshots' && (
                <>
                    {/* Search lives in the top bar with every other list page;
                        the segments carry the counts. */}
                    <div className="bk-listhead">
                        <SegControl
                            value={filterType}
                            onChange={setFilterType}
                            options={[
                                { value: 'all', label: 'All', count: searchedBackups.length },
                                { value: 'application', label: 'Applications', count: searchedBackups.filter(b => b.type === 'application').length },
                                { value: 'database', label: 'Databases', count: searchedBackups.filter(b => b.type === 'database').length },
                                { value: 'files', label: 'Files', count: searchedBackups.filter(b => b.type === 'files').length },
                            ]}
                        />
                        <Button size="sm" variant="outline" onClick={loadData}>
                            <RefreshCw size={14} />
                            Refresh
                        </Button>
                    </div>
                    {backups.length === 0 ? (
                        <EmptyState
                            icon={FileArchive}
                            title="No Backups"
                            description="No backups found. Create your first backup to get started."
                            action={<Button onClick={() => setShowBackupModal(true)}>Create Backup</Button>}
                        />
                    ) : filteredBackups.length === 0 ? (
                        <div className="bk-empty">
                            {search.trim()
                                ? `No snapshots match “${search.trim()}”.`
                                : 'No snapshots match the current filter.'}
                        </div>
                    ) : (
                        <div className="bk-card">
                            <table className="sk-dtable bk-table">
                                <thead>
                                    <tr>
                                        <th>Name</th>
                                        <th>Type</th>
                                        <th>Site/Service</th>
                                        <th>Size</th>
                                        <th>Storage</th>
                                        <th>Created</th>
                                        <th>Cost</th>
                                        <th aria-label="Actions" />
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredBackups.map((backup, index) => (
                                        <tr key={index}>
                                            <td>
                                                <div className="sk-cell-name bk-name">
                                                    <span className={`bk-ico bk-ico--${backup.type}`}>
                                                        {getBackupIcon(backup.type)}
                                                    </span>
                                                    <span title={backup.name || backup.app_name}>
                                                        {backup.name || backup.app_name}
                                                    </span>
                                                </div>
                                            </td>
                                            <td>
                                                <span className="sk-tag">{backup.type}</span>
                                            </td>
                                            <td>{backup.app_name || backup.name?.split('_')[0] || '—'}</td>
                                            <td className="sk-cell-mono">{formatBytes(backup.size, { defaultValue: '0 B' })}</td>
                                            <td>{getRemoteStatusPill(backup.remote_status)}</td>
                                            <td className="bk-when">{formatTimestamp(backup.timestamp)}</td>
                                            <td className="sk-cell-mono">{formatMoney(((backup.size || 0) / (1024 ** 3)) * (costSummary?.cost_rates?.local || 0))}</td>
                                            <td>
                                                <div className="bk-actions">
                                                    {backup.type !== 'files' && (
                                                        <button
                                                            type="button"
                                                            className="bk-iconbtn"
                                                            onClick={() => {
                                                                setSelectedBackup(backup);
                                                                setShowRestoreModal(true);
                                                            }}
                                                            title="Restore this snapshot"
                                                            aria-label={`Restore ${backup.name}`}
                                                        >
                                                            <History size={15} />
                                                        </button>
                                                    )}
                                                    {storageConfig?.provider !== 'local' && backup.remote_status !== 'synced' && (
                                                        <button
                                                            type="button"
                                                            className="bk-iconbtn"
                                                            onClick={() => handleUploadToRemote(backup)}
                                                            disabled={uploadingBackup === backup.path}
                                                            title="Copy to remote storage"
                                                            aria-label={`Upload ${backup.name} to remote storage`}
                                                        >
                                                            {uploadingBackup === backup.path
                                                                ? <RefreshCw size={15} className="spinning" />
                                                                : <Upload size={15} />}
                                                        </button>
                                                    )}
                                                    <button
                                                        type="button"
                                                        className="bk-iconbtn bk-iconbtn--danger"
                                                        onClick={() => handleDeleteBackup(backup.path)}
                                                        title="Delete this snapshot"
                                                        aria-label={`Delete ${backup.name}`}
                                                    >
                                                        <Trash2 size={15} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}

            {activeTab === 'schedules' && (
                <>
                    {schedules.length === 0 ? (
                        <EmptyState
                            icon={Clock}
                            title="No schedules yet"
                            description="A schedule runs a backup on its own so you don't have to remember to. Add one and it will appear here with its next fire time."
                            action={<Button onClick={() => setShowScheduleModal(true)}>New schedule</Button>}
                        />
                    ) : (
                        <SchedulesTable
                            schedules={schedules}
                            retentionDays={config?.retention_days || 30}
                            remoteLabel={PROVIDER_LABELS[storageConfig?.provider] || 'Local disk'}
                            onToggle={handleToggleSchedule}
                            onRemove={handleRemoveSchedule}
                        />
                    )}
                </>
            )}

            {activeTab === 'storage' && (
                <>
                    <StorageDestinations
                        stats={stats}
                        storageConfig={storageConfig}
                        costSummary={costSummary}
                        testing={testingConnection}
                        onTest={handleTestConnection}
                        onBrowse={() => setActiveTab('snapshots')}
                        onAdd={() => {
                            document.getElementById('bk-storage-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }}
                    />

                    <div className="card" id="bk-storage-form">
                        <div className="card-header">
                            <h3>Configure destination</h3>
                        </div>
                        <div className="card-body">
                            <form onSubmit={handleSaveStorageConfig}>
                                <FormField label="Storage Provider" hint="S3-Compatible works with AWS S3, MinIO and Wasabi.">
                                    <SegControl
                                        value={storageForm.provider}
                                        onChange={(provider) => setStorageForm({...storageForm, provider})}
                                        options={[
                                            { value: 'local', label: 'Local Only' },
                                            { value: 's3', label: 'S3-Compatible' },
                                            { value: 'b2', label: 'Backblaze B2' },
                                        ]}
                                    />
                                </FormField>

                                {storageForm.provider === 's3' && (
                                    <div className="storage-provider-config">
                                        <h4>S3-Compatible Storage</h4>
                                        <FormRow>
                                            <FormField label="Bucket Name" htmlFor="s3-bucket">
                                                <Input
                                                    id="s3-bucket"
                                                    type="text"
                                                    value={storageForm.s3.bucket}
                                                    onChange={(e) => setStorageForm({...storageForm, s3: {...storageForm.s3, bucket: e.target.value}})}
                                                    placeholder="my-backup-bucket"
                                                    required
                                                />
                                            </FormField>
                                            <FormField label="Region" htmlFor="s3-region">
                                                <Input
                                                    id="s3-region"
                                                    type="text"
                                                    value={storageForm.s3.region}
                                                    onChange={(e) => setStorageForm({...storageForm, s3: {...storageForm.s3, region: e.target.value}})}
                                                    placeholder="us-east-1"
                                                />
                                            </FormField>
                                        </FormRow>
                                        <FormRow>
                                            <FormField label="Access Key" htmlFor="s3-access-key">
                                                <Input
                                                    id="s3-access-key"
                                                    type="text"
                                                    value={storageForm.s3.access_key}
                                                    onChange={(e) => setStorageForm({...storageForm, s3: {...storageForm.s3, access_key: e.target.value}})}
                                                    placeholder="AKIA..."
                                                    required
                                                />
                                            </FormField>
                                            <FormField label="Secret Key" htmlFor="s3-secret-key">
                                                <Input
                                                    id="s3-secret-key"
                                                    type="password"
                                                    value={storageForm.s3.secret_key}
                                                    onChange={(e) => setStorageForm({...storageForm, s3: {...storageForm.s3, secret_key: e.target.value}})}
                                                    required
                                                />
                                            </FormField>
                                        </FormRow>
                                        <FormRow>
                                            <FormField label="Custom Endpoint URL" htmlFor="s3-endpoint" hint="Optional, for MinIO/Wasabi">
                                                <Input
                                                    id="s3-endpoint"
                                                    type="text"
                                                    value={storageForm.s3.endpoint_url}
                                                    onChange={(e) => setStorageForm({...storageForm, s3: {...storageForm.s3, endpoint_url: e.target.value}})}
                                                    placeholder="https://s3.example.com"
                                                />
                                            </FormField>
                                            <FormField label="Path Prefix" htmlFor="s3-path-prefix">
                                                <Input
                                                    id="s3-path-prefix"
                                                    type="text"
                                                    value={storageForm.s3.path_prefix}
                                                    onChange={(e) => setStorageForm({...storageForm, s3: {...storageForm.s3, path_prefix: e.target.value}})}
                                                    placeholder="serverkit-backups"
                                                />
                                            </FormField>
                                        </FormRow>
                                    </div>
                                )}

                                {storageForm.provider === 'b2' && (
                                    <div className="storage-provider-config">
                                        <h4>Backblaze B2</h4>
                                        <FormRow>
                                            <FormField label="Bucket Name" htmlFor="b2-bucket">
                                                <Input
                                                    id="b2-bucket"
                                                    type="text"
                                                    value={storageForm.b2.bucket}
                                                    onChange={(e) => setStorageForm({...storageForm, b2: {...storageForm.b2, bucket: e.target.value}})}
                                                    placeholder="my-backup-bucket"
                                                    required
                                                />
                                            </FormField>
                                            <FormField label="S3-Compatible Endpoint URL" htmlFor="b2-endpoint">
                                                <Input
                                                    id="b2-endpoint"
                                                    type="text"
                                                    value={storageForm.b2.endpoint_url}
                                                    onChange={(e) => setStorageForm({...storageForm, b2: {...storageForm.b2, endpoint_url: e.target.value}})}
                                                    placeholder="https://s3.us-west-004.backblazeb2.com"
                                                    required
                                                />
                                            </FormField>
                                        </FormRow>
                                        <FormRow>
                                            <FormField label="Application Key ID" htmlFor="b2-key-id">
                                                <Input
                                                    id="b2-key-id"
                                                    type="text"
                                                    value={storageForm.b2.key_id}
                                                    onChange={(e) => setStorageForm({...storageForm, b2: {...storageForm.b2, key_id: e.target.value}})}
                                                    required
                                                />
                                            </FormField>
                                            <FormField label="Application Key" htmlFor="b2-app-key">
                                                <Input
                                                    id="b2-app-key"
                                                    type="password"
                                                    value={storageForm.b2.application_key}
                                                    onChange={(e) => setStorageForm({...storageForm, b2: {...storageForm.b2, application_key: e.target.value}})}
                                                    required
                                                />
                                            </FormField>
                                        </FormRow>
                                        <FormField label="Path Prefix" htmlFor="b2-path-prefix">
                                            <Input
                                                id="b2-path-prefix"
                                                type="text"
                                                value={storageForm.b2.path_prefix}
                                                onChange={(e) => setStorageForm({...storageForm, b2: {...storageForm.b2, path_prefix: e.target.value}})}
                                                placeholder="serverkit-backups"
                                            />
                                        </FormField>
                                    </div>
                                )}

                                {storageForm.provider !== 'local' && (
                                    <>
                                        <FormField>
                                            <label className="checkbox-label">
                                                <input
                                                    type="checkbox"
                                                    checked={storageForm.auto_upload}
                                                    onChange={(e) => setStorageForm({...storageForm, auto_upload: e.target.checked})}
                                                />
                                                <span>Auto-upload new backups to remote storage</span>
                                            </label>
                                        </FormField>

                                        <FormField>
                                            <label className="checkbox-label">
                                                <input
                                                    type="checkbox"
                                                    checked={storageForm.keep_local_copy}
                                                    onChange={(e) => setStorageForm({...storageForm, keep_local_copy: e.target.checked})}
                                                />
                                                <span>Keep local copy after uploading</span>
                                            </label>
                                        </FormField>
                                    </>
                                )}

                                <div className="form-actions">
                                    <Button type="submit">Save Storage Config</Button>
                                    {storageForm.provider !== 'local' && (
                                        <Button
                                            type="button"
                                            variant="outline"
                                            onClick={handleTestConnection}
                                            disabled={testingConnection}
                                        >
                                            {testingConnection ? (
                                                <><RefreshCw size={16} className="spinning" /> Testing...</>
                                            ) : (
                                                <><Check size={16} /> Test Connection</>
                                            )}
                                        </Button>
                                    )}
                                </div>
                            </form>
                        </div>
                    </div>
                </>
            )}

            {activeTab === 'settings' && (
                <>
                    <div className="card">
                        <div className="card-header">
                            <h3>Backup Settings</h3>
                        </div>
                        <div className="card-body">
                            <form onSubmit={handleSaveConfig}>
                                <FormField>
                                    <label className="checkbox-label">
                                        <input
                                            type="checkbox"
                                            checked={configForm.enabled}
                                            onChange={(e) => setConfigForm({...configForm, enabled: e.target.checked})}
                                        />
                                        <span>Enable Scheduled Backups</span>
                                    </label>
                                </FormField>

                                <FormField label="Retention Period (days)" htmlFor="retention-days" hint="Backups older than this will be deleted during cleanup">
                                    <Input
                                        id="retention-days"
                                        type="number"
                                        value={configForm.retention_days}
                                        onChange={(e) => setConfigForm({...configForm, retention_days: parseInt(e.target.value)})}
                                        min="1"
                                        max="365"
                                    />
                                </FormField>

                                <div className="form-actions">
                                    <Button type="submit">Save Settings</Button>
                                    <Button type="button" variant="outline" onClick={handleCleanup}>
                                        <Trash2 size={16} />
                                        Run Cleanup Now
                                    </Button>
                                </div>
                            </form>
                        </div>
                    </div>

                    <div className="card">
                        <div className="card-header">
                            <h3>Storage cost rates</h3>
                        </div>
                        <div className="card-body">
                            <p className="form-help">
                                ServerKit is free &mdash; these are your own storage costs. Local is your server disk
                                (leave at 0 if you don&apos;t track it). S3/B2 are your cloud provider&apos;s $/GB/month.
                            </p>
                            <form onSubmit={handleSaveRates}>
                                <FormRow>
                                    <FormField label="Local ($/GB/month)" htmlFor="rate-local" hint="Your server disk — usually free">
                                        <Input
                                            id="rate-local"
                                            type="number"
                                            min={0}
                                            step="0.001"
                                            value={ratesForm.local}
                                            onChange={(e) => setRatesForm({...ratesForm, local: e.target.value})}
                                        />
                                    </FormField>
                                    <FormField label="S3 ($/GB/month)" htmlFor="rate-s3">
                                        <Input
                                            id="rate-s3"
                                            type="number"
                                            min={0}
                                            step="0.001"
                                            value={ratesForm.s3}
                                            onChange={(e) => setRatesForm({...ratesForm, s3: e.target.value})}
                                        />
                                    </FormField>
                                    <FormField label="B2 ($/GB/month)" htmlFor="rate-b2">
                                        <Input
                                            id="rate-b2"
                                            type="number"
                                            min={0}
                                            step="0.001"
                                            value={ratesForm.b2}
                                            onChange={(e) => setRatesForm({...ratesForm, b2: e.target.value})}
                                        />
                                    </FormField>
                                </FormRow>
                                <div className="form-actions">
                                    <Button type="submit" disabled={savingRates}>
                                        {savingRates ? (
                                            <><RefreshCw size={16} className="spinning" /> Saving...</>
                                        ) : (
                                            <><DollarSign size={16} /> Save rates</>
                                        )}
                                    </Button>
                                </div>
                            </form>
                        </div>
                    </div>
                </>
            )}

            {/* Create Backup Modal */}
            <Modal open={showBackupModal} onClose={() => setShowBackupModal(false)} title="Create Backup">
                        <form onSubmit={handleCreateBackup}>
                                <div className="form-group">
                                    <label>Backup Type</label>
                                    <select
                                        value={backupForm.type}
                                        onChange={(e) => setBackupForm({...backupForm, type: e.target.value})}
                                    >
                                        <option value="application">Application</option>
                                        <option value="database">Database Only</option>
                                        <option value="files">Files / Directories</option>
                                    </select>
                                </div>

                                {backupForm.type === 'application' && (
                                    <>
                                        <div className="form-group">
                                            <label>Application</label>
                                            <select
                                                value={backupForm.applicationId}
                                                onChange={(e) => setBackupForm({...backupForm, applicationId: e.target.value})}
                                                required
                                            >
                                                <option value="">Select Application</option>
                                                {apps.map(app => (
                                                    <option key={app.id} value={app.id}>{app.name}</option>
                                                ))}
                                            </select>
                                        </div>

                                        <div className="form-group">
                                            <label className="checkbox-label">
                                                <input
                                                    type="checkbox"
                                                    checked={backupForm.includeDb}
                                                    onChange={(e) => setBackupForm({...backupForm, includeDb: e.target.checked})}
                                                />
                                                <span>Include Database</span>
                                            </label>
                                        </div>
                                    </>
                                )}

                                {backupForm.type === 'files' && (
                                    <>
                                        <div className="form-group">
                                            <label>Backup Name (optional)</label>
                                            <Input
                                                type="text"
                                                value={backupForm.fileName}
                                                onChange={(e) => setBackupForm({...backupForm, fileName: e.target.value})}
                                                placeholder="my-config-backup"
                                            />
                                        </div>
                                        <div className="form-group">
                                            <label>File/Directory Paths (one per line)</label>
                                            <Textarea
                                                value={backupForm.filePaths}
                                                onChange={(e) => setBackupForm({...backupForm, filePaths: e.target.value})}
                                                placeholder={"/etc/nginx/nginx.conf\n/var/www/mysite/config\n/home/user/.env"}
                                                rows={5}
                                                required
                                            />
                                            <span className="form-help">Enter absolute paths to files or directories to backup</span>
                                        </div>
                                    </>
                                )}

                                {(backupForm.type === 'database' || backupForm.includeDb) && (
                                    <>
                                        <div className="form-group">
                                            <label>Database Type</label>
                                            <select
                                                value={backupForm.dbType}
                                                onChange={(e) => setBackupForm({...backupForm, dbType: e.target.value})}
                                            >
                                                <option value="mysql">MySQL</option>
                                                <option value="postgresql">PostgreSQL</option>
                                            </select>
                                        </div>

                                        <div className="form-group">
                                            <label>Database Name</label>
                                            <Input
                                                type="text"
                                                value={backupForm.dbName}
                                                onChange={(e) => setBackupForm({...backupForm, dbName: e.target.value})}
                                                required
                                            />
                                        </div>

                                        <div className="form-row">
                                            <div className="form-group">
                                                <label>Username</label>
                                                <Input
                                                    type="text"
                                                    value={backupForm.dbUser}
                                                    onChange={(e) => setBackupForm({...backupForm, dbUser: e.target.value})}
                                                />
                                            </div>

                                            <div className="form-group">
                                                <label>Password</label>
                                                <Input
                                                    type="password"
                                                    value={backupForm.dbPassword}
                                                    onChange={(e) => setBackupForm({...backupForm, dbPassword: e.target.value})}
                                                />
                                            </div>
                                        </div>

                                        <div className="form-group">
                                            <label>Host</label>
                                            <Input
                                                type="text"
                                                value={backupForm.dbHost}
                                                onChange={(e) => setBackupForm({...backupForm, dbHost: e.target.value})}
                                            />
                                        </div>
                                    </>
                                )}
                            <div className="modal-actions">
                                <Button type="button" variant="outline" onClick={() => setShowBackupModal(false)}>
                                    Cancel
                                </Button>
                                <Button type="submit">Create Backup</Button>
                            </div>
                        </form>
            </Modal>

            {/* Add Schedule Modal */}
            <Modal open={showScheduleModal} onClose={() => setShowScheduleModal(false)} title="Add Backup Schedule">
                        <form onSubmit={handleAddSchedule}>
                                <div className="form-group">
                                    <label>Schedule Name</label>
                                    <Input
                                        type="text"
                                        value={scheduleForm.name}
                                        onChange={(e) => setScheduleForm({...scheduleForm, name: e.target.value})}
                                        placeholder="Daily App Backup"
                                        required
                                    />
                                </div>

                                <div className="form-group">
                                    <label>Backup Type</label>
                                    <select
                                        value={scheduleForm.backupType}
                                        onChange={(e) => setScheduleForm({...scheduleForm, backupType: e.target.value})}
                                    >
                                        <option value="application">Application</option>
                                        <option value="database">Database</option>
                                        <option value="files">Files / Directories</option>
                                    </select>
                                </div>

                                <div className="form-group">
                                    <label>
                                        {scheduleForm.backupType === 'files'
                                            ? 'Paths (comma-separated)'
                                            : scheduleForm.backupType === 'database'
                                            ? 'Database (format: mysql:dbname or postgresql:dbname)'
                                            : 'Application Name'
                                        }
                                    </label>
                                    <Input
                                        type="text"
                                        value={scheduleForm.target}
                                        onChange={(e) => setScheduleForm({...scheduleForm, target: e.target.value})}
                                        placeholder={
                                            scheduleForm.backupType === 'files'
                                                ? '/etc/nginx,/var/www/config'
                                                : scheduleForm.backupType === 'database'
                                                ? 'mysql:mydb'
                                                : 'my-app'
                                        }
                                        required
                                    />
                                </div>

                                <div className="form-group">
                                    <label>Time</label>
                                    <Input
                                        type="time"
                                        value={scheduleForm.scheduleTime}
                                        onChange={(e) => setScheduleForm({...scheduleForm, scheduleTime: e.target.value})}
                                        required
                                    />
                                </div>

                                {storageConfig?.provider !== 'local' && (
                                    <div className="form-group">
                                        <label className="checkbox-label">
                                            <input
                                                type="checkbox"
                                                checked={scheduleForm.uploadRemote}
                                                onChange={(e) => setScheduleForm({...scheduleForm, uploadRemote: e.target.checked})}
                                            />
                                            <span>Upload to remote storage after backup</span>
                                        </label>
                                    </div>
                                )}
                            <div className="modal-actions">
                                <Button type="button" variant="outline" onClick={() => setShowScheduleModal(false)}>
                                    Cancel
                                </Button>
                                <Button type="submit">Add Schedule</Button>
                            </div>
                        </form>
            </Modal>

            {/* Restore Modal */}
            <Modal open={showRestoreModal && !!selectedBackup} onClose={() => setShowRestoreModal(false)} title="Restore Backup">
                        {selectedBackup && (<>
                            <div className="bk-restore-warn">
                                <AlertTriangle size={18} />
                                <span><b>Warning:</b> restoring this backup will overwrite existing data. This action cannot be undone.</span>
                            </div>
                            <div className="bk-restore-details">
                                <div className="sk-info-row">
                                    <span className="k">Backup Name</span>
                                    <span className="v">{selectedBackup.name || selectedBackup.app_name}</span>
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">Type</span>
                                    <span className="v">{selectedBackup.type}</span>
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">Created</span>
                                    <span className="v">{formatTimestamp(selectedBackup.timestamp)}</span>
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">Size</span>
                                    <span className="v">{formatBytes(selectedBackup.size, { defaultValue: '0 B' })}</span>
                                </div>
                            </div>
                        </>)}
                        <div className="modal-actions">
                            <Button variant="outline" onClick={() => setShowRestoreModal(false)}>
                                Cancel
                            </Button>
                            <Button variant="destructive" onClick={handleRestore}>
                                Restore Backup
                            </Button>
                        </div>
            </Modal>
        </div>
    );
};

export default Backups;
