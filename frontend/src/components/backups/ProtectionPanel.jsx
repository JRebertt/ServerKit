// Shared "Protection" panel — the upgraded backup experience rendered for both
// WordPress sites and applications (Services). Loads the backup policy + run
// history and owns every mutation (toggle, schedule save, manual backup,
// restore, verify, delete). Three stacked cards plus detail/restore drawers.
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { History, RefreshCw, Loader2, List, CalendarDays, X } from 'lucide-react';

import api from '@/services/api';
import { useToast } from '@/contexts/ToastContext';
import { useConfirm } from '@/hooks/useConfirm';
import { Button } from '@/components/ui/button';

import ProtectionStatusCard from './ProtectionStatusCard';
import ScheduleCard from './ScheduleCard';
import BackupHistoryList from './BackupHistoryList';
import BackupCalendar from './BackupCalendar';
import BackupDetailDrawer from './BackupDetailDrawer';
import RestoreDrawer from './RestoreDrawer';

function sameLocalDay(iso, date) {
    if (!iso) return false;
    const d = new Date(iso);
    return d.getFullYear() === date.getFullYear()
        && d.getMonth() === date.getMonth()
        && d.getDate() === date.getDate();
}

export default function ProtectionPanel({ targetType, targetId, targetName, showMaintenanceModeOption = false }) {
    const toast = useToast();
    const navigate = useNavigate();
    const { confirm } = useConfirm();

    const [view, setView] = useState(null);   // policy view payload
    const [runs, setRuns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [backingUp, setBackingUp] = useState(false);
    const [drilling, setDrilling] = useState(false);
    const [historyView, setHistoryView] = useState('list');  // 'list' | 'calendar'
    const [dayFilter, setDayFilter] = useState(null);        // Date | null
    const [detailRun, setDetailRun] = useState(null);
    const [restoreRun, setRestoreRun] = useState(null);
    // Restore scopes this target type supports, from the target-types API
    // (extension-provided types declare their own — plan 52 D4). Null until
    // loaded; RestoreDrawer falls back to its built-in defaults then.
    const [restoreScopes, setRestoreScopes] = useState(null);
    const reloadTimers = useRef([]);

    // Fetched once per target type, not on every load() (which refires on
    // window focus) — the type catalog changes only when extensions change.
    useEffect(() => {
        let cancelled = false;
        api.getBackupTargetTypes()
            .then((res) => {
                if (cancelled) return;
                const entry = (res?.target_types || []).find(
                    (t) => t.target_type === targetType);
                setRestoreScopes(entry?.restore_scopes || null);
            })
            .catch(() => { /* optional — the drawer has sane fallbacks */ });
        return () => { cancelled = true; };
    }, [targetType]);

    const load = useCallback(async () => {
        if (!targetId) return;
        try {
            const [policyView, runsResp] = await Promise.all([
                api.getBackupPolicy(targetType, targetId),
                api.getBackupRuns(targetType, targetId),
            ]);
            setView(policyView);
            setRuns(runsResp?.runs || []);
        } catch (err) {
            toast.error(err.message || 'Failed to load protection settings');
        } finally {
            setLoading(false);
        }
    }, [targetType, targetId, toast]);

    useEffect(() => {
        setLoading(true);
        load();
    }, [load]);

    // Refresh when the tab regains focus (a background backup may have finished).
    useEffect(() => {
        const onFocus = () => load();
        window.addEventListener('focus', onFocus);
        return () => window.removeEventListener('focus', onFocus);
    }, [load]);

    // Clear any pending delayed reloads on unmount.
    useEffect(() => () => reloadTimers.current.forEach(clearTimeout), []);

    const scheduleReloads = useCallback(() => {
        reloadTimers.current.forEach(clearTimeout);
        reloadTimers.current = [setTimeout(load, 2500), setTimeout(load, 7000)];
    }, [load]);

    const handleToggle = useCallback(async (enabled) => {
        setSaving(true);
        try {
            const updated = await api.updateBackupPolicy(targetType, targetId, { enabled });
            setView(updated);
            toast.success(enabled ? 'Automatic backups enabled' : 'Automatic backups disabled');
        } catch (err) {
            toast.error(err.message || 'Failed to update protection');
        } finally {
            setSaving(false);
        }
    }, [targetType, targetId, toast]);

    const handleSaveSchedule = useCallback(async (fields) => {
        setSaving(true);
        try {
            const updated = await api.updateBackupPolicy(targetType, targetId, fields);
            setView(updated);
            toast.success('Schedule saved');
        } catch (err) {
            toast.error(err.message || 'Failed to save schedule');
        } finally {
            setSaving(false);
        }
    }, [targetType, targetId, toast]);

    const handleBackupNow = useCallback(async () => {
        setBackingUp(true);
        try {
            await api.triggerBackup(targetType, targetId);
            toast.success('Backup started');
            scheduleReloads();
        } catch (err) {
            toast.error(err.message || 'Failed to start backup');
        } finally {
            setBackingUp(false);
        }
    }, [targetType, targetId, toast, scheduleReloads]);

    const handleRunDrill = useCallback(async () => {
        setDrilling(true);
        try {
            await api.runBackupDrill(targetType, targetId);
            toast.success('Restore drill started');
            scheduleReloads();
        } catch (err) {
            toast.error(err.message || 'Failed to start restore drill');
        } finally {
            setDrilling(false);
        }
    }, [targetType, targetId, toast, scheduleReloads]);

    // Restore is always initiated from a run — opening the restore drawer.
    const openRestore = useCallback((run) => setRestoreRun(run), []);

    const handleRestoreConfirm = useCallback(async (options) => {
        if (!restoreRun) return;
        try {
            await api.restoreBackupRun(targetType, targetId, restoreRun.id, {
                ...options,
                maintenance_mode: showMaintenanceModeOption ? options.maintenance_mode : false,
            });
            toast.success('Restore started');
            setRestoreRun(null);
            setDetailRun(null);
            scheduleReloads();
        } catch (err) {
            toast.error(err.message || 'Failed to start restore');
        }
    }, [restoreRun, targetType, targetId, showMaintenanceModeOption, toast, scheduleReloads]);

    const handleVerify = useCallback(async (run) => {
        try {
            const result = await api.verifyBackupRun(targetType, targetId, run.id);
            if (result?.verified) toast.success('Remote copy verified');
            else toast.warning('Remote copy could not be verified');
            load();
        } catch (err) {
            toast.error(err.message || 'Verification failed');
        }
    }, [targetType, targetId, toast, load]);

    const handleDelete = useCallback(async (run) => {
        const ok = await confirm({
            title: 'Delete backup?',
            message: 'This permanently deletes the backup, including any remote copy. This cannot be undone.',
            confirmText: 'Delete',
            variant: 'danger',
        });
        if (!ok) return;
        try {
            await api.deleteBackupRun(targetType, targetId, run.id);
            toast.success('Backup deleted');
            if (detailRun?.id === run.id) setDetailRun(null);
            load();
        } catch (err) {
            toast.error(err.message || 'Failed to delete backup');
        }
    }, [confirm, targetType, targetId, toast, load, detailRun]);

    const visibleRuns = useMemo(
        () => (dayFilter ? runs.filter((r) => sameLocalDay(r.started_at, dayFilter)) : runs),
        [runs, dayFilter],
    );

    return (
        <div className="protection-panel app-overview-grid">
            <div className="app-overview-left">
                <ProtectionStatusCard
                    policyView={view}
                    onToggle={handleToggle}
                    onBackupNow={handleBackupNow}
                    onRunDrill={handleRunDrill}
                    onViewGlobal={() => navigate('/backups')}
                    onViewJobs={() => navigate('/monitoring/jobs')}
                    busy={saving}
                    backingUp={backingUp}
                    drilling={drilling || !!view?.restore_proof?.is_drilling}
                />

                <ScheduleCard
                    policy={view?.policy}
                    remoteConfigured={!!view?.remote_configured}
                    onSave={handleSaveSchedule}
                    saving={saving}
                />

                <div className="app-panel backup-history-card">
                    <div className="app-panel-header">
                        <History size={16} />
                        <span>Backup history</span>
                        <span className="app-panel-header-actions backup-history-card__tools">
                            {dayFilter && (
                                <button
                                    type="button"
                                    className="backup-history-card__chip"
                                    onClick={() => setDayFilter(null)}
                                >
                                    {dayFilter.toLocaleDateString()} <X size={12} />
                                </button>
                            )}
                            <div className="backup-history-card__toggle">
                                <button
                                    type="button"
                                    className={historyView === 'list' ? 'is-active' : ''}
                                    onClick={() => setHistoryView('list')}
                                    aria-label="List view"
                                >
                                    <List size={14} />
                                </button>
                                <button
                                    type="button"
                                    className={historyView === 'calendar' ? 'is-active' : ''}
                                    onClick={() => setHistoryView('calendar')}
                                    aria-label="Calendar view"
                                >
                                    <CalendarDays size={14} />
                                </button>
                            </div>
                            <Button size="sm" variant="outline" onClick={load} disabled={loading} title="Refresh">
                                {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
                            </Button>
                        </span>
                    </div>
                    <div className="app-panel-body">
                        {historyView === 'calendar' ? (
                            <BackupCalendar
                                runs={runs}
                                onDayClick={(date) => { setDayFilter(date); setHistoryView('list'); }}
                            />
                        ) : (
                            <BackupHistoryList
                                runs={visibleRuns}
                                drills={dayFilter ? [] : view?.restore_proof?.recent_drills}
                                loading={loading}
                                onRestore={openRestore}
                                onVerify={handleVerify}
                                onDelete={handleDelete}
                                onRowClick={(run) => setDetailRun(run)}
                            />
                        )}
                    </div>
                </div>
            </div>

            <BackupDetailDrawer
                run={detailRun}
                open={!!detailRun}
                onClose={() => setDetailRun(null)}
                onRestore={(run) => { setDetailRun(null); openRestore(run); }}
                onVerify={handleVerify}
                onDelete={handleDelete}
            />

            <RestoreDrawer
                run={restoreRun}
                open={!!restoreRun}
                onClose={() => setRestoreRun(null)}
                onConfirm={handleRestoreConfirm}
                targetName={targetName}
                targetType={targetType}
                restoreScopes={restoreScopes}
                showMaintenanceModeOption={showMaintenanceModeOption}
            />
        </div>
    );
}
