import { useState, useEffect, useCallback } from 'react';
import { statusKind } from '@/components/ds/status';
import { RefreshCw, ArrowUpCircle, Moon, Sun, Gauge as GaugeIcon, Boxes } from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { Pill } from '../ds';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useTranslation } from 'react-i18next';

// Short SHA helper for image digests (handles "sha256:abcdef..." or bare hashes)
function shortDigest(digest) {
    if (!digest) return '—';
    const value = String(digest).includes(':') ? String(digest).split(':').pop() : String(digest);
    return value.slice(0, 12);
}


function formatStatusLabel(status) {
    if (!status) return 'Not checked';
    return status.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

// ============================================================
// Image update section
// ============================================================
const ImageUpdateSection = ({ app, onChanged }) => {
    const { t } = useTranslation();
    const toast = useToast();
    const { confirm } = useConfirm();
    const [info, setInfo] = useState(app.image_update || null);
    const [checking, setChecking] = useState(false);
    const [applying, setApplying] = useState(false);

    const isCompose = app.app_type === 'docker';

    useEffect(() => {
        let active = true;
        (async () => {
            try {
                const data = await api.getImageUpdate(app.id);
                if (active && data) setInfo(data);
            } catch {
                /* no prior check is fine — fall back to the badge on app */
            }
        })();
        return () => { active = false; };
    }, [app.id]);

    async function handleCheck() {
        setChecking(true);
        try {
            const data = await api.checkImageUpdate(app.id);
            setInfo(data);
            if (data.update_available) {
                toast.info(t('app.containerOpsPanel.anImageUpdateIsAvailable', 'An image update is available.'));
            } else {
                toast.success(t('app.containerOpsPanel.imageIsUpToDate', 'Image is up to date.'));
            }
            onChanged?.();
        } catch (err) {
            toast.error(err.message || t('app.containerOpsPanel.failedToCheckForUpdates', 'Failed to check for updates'));
        } finally {
            setChecking(false);
        }
    }

    async function handleApply() {
        const confirmed = await confirm({
            title: t('app.containerOpsPanel.updateImage', 'Update image'),
            message: t('app.containerOpsPanel.pullTheLatestImageAndRecreate', 'Pull the latest image and recreate the container? The app will briefly restart.'),
            confirmText: t('app.containerOpsPanel.updateNow', 'Update now'),
        });
        if (!confirmed) return;

        setApplying(true);
        try {
            const data = await api.applyImageUpdate(app.id);
            toast.success(data.message || t('app.containerOpsPanel.imageUpdated', 'Image updated.'));
            onChanged?.();
            // Refresh the local check after applying
            try {
                const refreshed = await api.getImageUpdate(app.id);
                if (refreshed) setInfo(refreshed);
            } catch { /* optional */ }
        } catch (err) {
            toast.error(err.message || t('app.containerOpsPanel.failedToApplyUpdate', 'Failed to apply update'));
        } finally {
            setApplying(false);
        }
    }

    const status = info?.status;
    const updateAvailable = info?.update_available;
    const checkedAt = info?.checked_at;

    return (
        <div className="app-panel container-ops__section">
            <div className="app-panel-header">
                <RefreshCw />
                <span>{t('app.containerOpsPanel.imageUpdate', 'Image Update')}</span>
                <span className="app-panel-header-actions">
                    {status && (
                        <Pill kind={statusKind(status)}>
                            {formatStatusLabel(status)}
                        </Pill>
                    )}
                </span>
            </div>
            <div className="app-panel-body">
                {!isCompose && (
                    <p className="app-panel-hint">
                        {t('app.containerOpsPanel.imageUpdatesApplyToDockerCompose', 'Image updates apply to Docker Compose apps. You can still check this app\'s digest, but "Update now" is only available for docker-compose apps.')}
                    </p>
                )}

                <div className="app-info-grid container-ops__digests">
                    <div className="app-info-item">
                        <span className="app-info-label">{t('app.containerOpsPanel.currentDigest', 'Current digest')}</span>
                        <span className="app-info-value mono">{shortDigest(info?.current_digest)}</span>
                    </div>
                    <div className="app-info-item">
                        <span className="app-info-label">{t('app.containerOpsPanel.latestDigest', 'Latest digest')}</span>
                        <span className="app-info-value mono">{shortDigest(info?.latest_digest)}</span>
                    </div>
                    <div className="app-info-item">
                        <span className="app-info-label">{t('app.containerOpsPanel.lastChecked', 'Last checked')}</span>
                        <span className="app-info-value">
                            {checkedAt ? new Date(checkedAt).toLocaleString() : 'Never'}
                        </span>
                    </div>
                </div>

                <div className="app-detail-actions container-ops__actions">
                    <Button variant="outline" size="sm" onClick={handleCheck} disabled={checking}>
                        {checking ? 'Checking…' : 'Check for update'}
                    </Button>
                    {updateAvailable && isCompose && (
                        <Button size="sm" onClick={handleApply} disabled={applying}>
                            <ArrowUpCircle size={15} />
                            {applying ? 'Updating…' : 'Update now'}
                        </Button>
                    )}
                </div>
            </div>
        </div>
    );
};

// ============================================================
// Private registry section — which stored registry credentials to
// authenticate with before pulling this app's image (docker login).
// ============================================================
const RegistrySection = ({ app, onChanged }) => {
    const { t } = useTranslation();
    const toast = useToast();
    const [registries, setRegistries] = useState([]);
    const [selected, setSelected] = useState(app.registry_id ?? '');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    useEffect(() => { setSelected(app.registry_id ?? ''); }, [app.registry_id]);

    useEffect(() => {
        let active = true;
        (async () => {
            try {
                const data = await api.getContainerRegistries();
                if (active) setRegistries(data?.registries || []);
            } catch {
                /* listing failing just means no picker options */
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => { active = false; };
    }, []);

    async function handleChange(value) {
        const next = value === '' ? null : Number(value);
        setSelected(value);
        setSaving(true);
        try {
            await api.updateApp(app.id, { registry_id: next });
            toast.success(next ? t('app.containerOpsPanel.registryAttached', 'Registry attached.') : t('app.containerOpsPanel.registryDetachedPullsAreAnonymous', 'Registry detached — pulls are anonymous.'));
            onChanged?.();
        } catch (err) {
            toast.error(err.message || t('app.containerOpsPanel.failedToUpdateRegistry', 'Failed to update registry'));
            setSelected(app.registry_id ?? '');
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="app-panel container-ops__section">
            <div className="app-panel-header">
                <Boxes />
                <span>{t('app.containerOpsPanel.privateRegistry', 'Private Registry')}</span>
            </div>
            <div className="app-panel-body">
                <p className="app-panel-hint">
                    {t('app.containerOpsPanel.authenticateWithStoredCredentialsBeforePulling', 'Authenticate with stored credentials before pulling this app\'s image. Add registries under')} <Link to="/settings/connections">{t('app.containerOpsPanel.settingsConnections', 'Settings → Connections')}</Link>.
                </p>

                <div className="container-ops__field">
                    <div className="container-ops__field-text">
                        <Label htmlFor={`registry-${app.id}`}>{t('app.containerOpsPanel.registry', 'Registry')}</Label>
                        <span className="container-ops__field-hint">
                            {t('app.containerOpsPanel.publicImagesPullAnonymouslyPickA', 'Public images pull anonymously; pick a registry for private images.')}
                        </span>
                    </div>
                    <select
                        id={`registry-${app.id}`}
                        className="container-ops__select"
                        value={selected}
                        onChange={(e) => handleChange(e.target.value)}
                        disabled={loading || saving}
                    >
                        <option value="">{t('app.containerOpsPanel.publicNoAuth', 'Public (no auth)')}</option>
                        {registries.map((r) => (
                            <option key={r.id} value={r.id}>
                                {r.name} · {r.login_host}
                            </option>
                        ))}
                    </select>
                </div>
            </div>
        </div>
    );
};

// ============================================================
// Auto-sleep section
// ============================================================
const AutoSleepSection = ({ app, onChanged }) => {
    const { t } = useTranslation();
    const toast = useToast();
    const [policy, setPolicy] = useState(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [busy, setBusy] = useState(false);
    const [idleTimeout, setIdleTimeout] = useState(30);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getSleepPolicy(app.id);
            setPolicy(data);
            if (data?.idle_timeout_minutes != null) {
                setIdleTimeout(data.idle_timeout_minutes);
            }
        } catch (err) {
            console.error('Failed to load sleep policy:', err);
        } finally {
            setLoading(false);
        }
    }, [app.id]);

    useEffect(() => { load(); }, [load]);

    async function savePolicy(next) {
        setSaving(true);
        try {
            const data = await api.updateSleepPolicy(app.id, next);
            setPolicy((prev) => ({ ...prev, ...(data || next) }));
            toast.success(t('app.containerOpsPanel.autoSleepPolicySaved', 'Auto-sleep policy saved.'));
            onChanged?.();
        } catch (err) {
            toast.error(err.message || t('app.containerOpsPanel.failedToSavePolicy', 'Failed to save policy'));
            load();
        } finally {
            setSaving(false);
        }
    }

    function handleToggle(enabled) {
        setPolicy((prev) => ({ ...prev, enabled }));
        savePolicy({ enabled, idle_timeout_minutes: idleTimeout });
    }

    function handleTimeoutCommit() {
        const value = Math.max(1, parseInt(idleTimeout, 10) || 1);
        setIdleTimeout(value);
        if (value !== policy?.idle_timeout_minutes) {
            savePolicy({ enabled: policy?.enabled ?? false, idle_timeout_minutes: value });
        }
    }

    async function handleSleepWake() {
        setBusy(true);
        try {
            if (policy?.asleep) {
                await api.wakeApp(app.id);
                toast.success(t('app.containerOpsPanel.appWoken', 'App woken.'));
            } else {
                await api.sleepApp(app.id);
                toast.success(t('app.containerOpsPanel.appPutToSleep', 'App put to sleep.'));
            }
            await load();
            onChanged?.();
        } catch (err) {
            toast.error(err.message || t('app.containerOpsPanel.actionFailed', 'Action failed'));
        } finally {
            setBusy(false);
        }
    }

    const asleep = policy?.asleep;

    return (
        <div className="app-panel container-ops__section">
            <div className="app-panel-header">
                <Moon />
                <span>{t('app.containerOpsPanel.autoSleep', 'Auto-Sleep')}</span>
                <span className="app-panel-header-actions">
                    {!loading && (
                        <Pill kind={asleep ? 'gray' : 'green'}>{asleep ? 'Asleep' : 'Awake'}</Pill>
                    )}
                </span>
            </div>
            <div className="app-panel-body">
                <p className="app-panel-hint">
                    {t('app.containerOpsPanel.stopTheContainerAfterAPeriod', 'Stop the container after a period of inactivity to free resources. It wakes automatically on the next request.')}
                </p>

                <div className="container-ops__field">
                    <div className="container-ops__field-text">
                        <Label htmlFor={`sleep-enabled-${app.id}`}>{t('app.containerOpsPanel.enableAutoSleep', 'Enable auto-sleep')}</Label>
                        <span className="container-ops__field-hint">
                            {t('app.containerOpsPanel.idleAppsAreSuspendedAfterThe', 'Idle apps are suspended after the timeout below.')}
                        </span>
                    </div>
                    <Switch
                        id={`sleep-enabled-${app.id}`}
                        checked={!!policy?.enabled}
                        onCheckedChange={handleToggle}
                        disabled={loading || saving}
                    />
                </div>

                <div className="container-ops__field">
                    <div className="container-ops__field-text">
                        <Label htmlFor={`sleep-timeout-${app.id}`}>{t('app.containerOpsPanel.idleTimeoutMinutes', 'Idle timeout (minutes)')}</Label>
                        <span className="container-ops__field-hint">
                            {policy?.last_activity_at
                                ? `Last activity ${new Date(policy.last_activity_at).toLocaleString()}`
                                : 'No recorded activity yet.'}
                        </span>
                    </div>
                    <Input
                        id={`sleep-timeout-${app.id}`}
                        type="number"
                        min={1}
                        className="container-ops__num"
                        value={idleTimeout}
                        onChange={(e) => setIdleTimeout(e.target.value)}
                        onBlur={handleTimeoutCommit}
                        disabled={loading || saving}
                    />
                </div>

                <div className="app-detail-actions container-ops__actions">
                    <Button variant="outline" size="sm" onClick={handleSleepWake} disabled={busy || loading}>
                        {asleep ? <Sun size={15} /> : <Moon size={15} />}
                        {busy ? 'Working…' : asleep ? 'Wake now' : 'Sleep now'}
                    </Button>
                </div>
            </div>
        </div>
    );
};

// ============================================================
// Auto-scale section
// ============================================================
const DEFAULT_SCALE = {
    enabled: false,
    service_name: '',
    min_replicas: 1,
    max_replicas: 3,
    cpu_high_percent: 80,
    cpu_low_percent: 20,
    cooldown_seconds: 300,
    current_replicas: 1,
};

const AutoScaleSection = ({ app, onChanged }) => {
    const { t } = useTranslation();
    const toast = useToast();
    const [form, setForm] = useState(DEFAULT_SCALE);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [scaling, setScaling] = useState(false);
    const [manualReplicas, setManualReplicas] = useState(1);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getScalePolicy(app.id);
            const merged = { ...DEFAULT_SCALE, ...(data || {}) };
            setForm(merged);
            setManualReplicas(merged.current_replicas ?? merged.min_replicas ?? 1);
        } catch (err) {
            console.error('Failed to load scale policy:', err);
        } finally {
            setLoading(false);
        }
    }, [app.id]);

    useEffect(() => { load(); }, [load]);

    function setField(key, value) {
        setForm((prev) => ({ ...prev, [key]: value }));
    }

    async function handleSave() {
        setSaving(true);
        try {
            const payload = {
                enabled: form.enabled,
                service_name: form.service_name,
                min_replicas: parseInt(form.min_replicas, 10) || 1,
                max_replicas: parseInt(form.max_replicas, 10) || 1,
                cpu_high_percent: parseInt(form.cpu_high_percent, 10) || 0,
                cpu_low_percent: parseInt(form.cpu_low_percent, 10) || 0,
                cooldown_seconds: parseInt(form.cooldown_seconds, 10) || 0,
            };
            const data = await api.updateScalePolicy(app.id, payload);
            setForm((prev) => ({ ...prev, ...(data || payload) }));
            toast.success(t('app.containerOpsPanel.autoScalePolicySaved', 'Auto-scale policy saved.'));
            onChanged?.();
        } catch (err) {
            toast.error(err.message || t('app.containerOpsPanel.failedToSavePolicy2', 'Failed to save policy'));
        } finally {
            setSaving(false);
        }
    }

    async function handleManualScale() {
        const replicas = Math.max(0, parseInt(manualReplicas, 10) || 0);
        setScaling(true);
        try {
            await api.scaleApp(app.id, replicas);
            toast.success(t('app.containerOpsPanel.scaledToReplica', 'Scaled to {{replicas}} replica{{value}}.', { replicas: replicas, value: replicas === 1 ? '' : 's' }));
            await load();
            onChanged?.();
        } catch (err) {
            toast.error(err.message || t('app.containerOpsPanel.failedToScale', 'Failed to scale'));
        } finally {
            setScaling(false);
        }
    }

    return (
        <div className="app-panel container-ops__section">
            <div className="app-panel-header">
                <GaugeIcon />
                <span>{t('app.containerOpsPanel.autoScale', 'Auto-Scale')}</span>
                <span className="app-panel-header-actions">
                    {!loading && (
                        <Pill kind={form.enabled ? 'green' : 'gray'}>
                            {form.enabled ? 'Enabled' : 'Disabled'}
                        </Pill>
                    )}
                </span>
            </div>
            <div className="app-panel-body">
                <p className="app-panel-hint">
                    {t('app.containerOpsPanel.adjustReplicaCountBasedOnCpu', 'Adjust replica count based on CPU load. Requires a scale-capable Docker Compose service (one that can run multiple replicas).')}
                </p>

                <div className="container-ops__field">
                    <div className="container-ops__field-text">
                        <Label htmlFor={`scale-enabled-${app.id}`}>{t('app.containerOpsPanel.enableAutoScale', 'Enable auto-scale')}</Label>
                        <span className="container-ops__field-hint">
                            {t('app.containerOpsPanel.currentlyRunning', 'Currently running')} {form.current_replicas ?? '—'} replica(s).
                        </span>
                    </div>
                    <Switch
                        id={`scale-enabled-${app.id}`}
                        checked={!!form.enabled}
                        onCheckedChange={(v) => setField('enabled', v)}
                        disabled={loading}
                    />
                </div>

                <div className="container-ops__grid">
                    <div className="container-ops__input">
                        <Label htmlFor={`scale-service-${app.id}`}>{t('app.containerOpsPanel.serviceName', 'Service name')}</Label>
                        <Input
                            id={`scale-service-${app.id}`}
                            type="text"
                            value={form.service_name || ''}
                            onChange={(e) => setField('service_name', e.target.value)}
                            placeholder="web"
                            disabled={loading}
                        />
                    </div>
                    <div className="container-ops__input">
                        <Label htmlFor={`scale-cooldown-${app.id}`}>{t('app.containerOpsPanel.cooldownSeconds', 'Cooldown (seconds)')}</Label>
                        <Input
                            id={`scale-cooldown-${app.id}`}
                            type="number"
                            min={0}
                            value={form.cooldown_seconds}
                            onChange={(e) => setField('cooldown_seconds', e.target.value)}
                            disabled={loading}
                        />
                    </div>
                    <div className="container-ops__input">
                        <Label htmlFor={`scale-min-${app.id}`}>{t('app.containerOpsPanel.minReplicas', 'Min replicas')}</Label>
                        <Input
                            id={`scale-min-${app.id}`}
                            type="number"
                            min={0}
                            value={form.min_replicas}
                            onChange={(e) => setField('min_replicas', e.target.value)}
                            disabled={loading}
                        />
                    </div>
                    <div className="container-ops__input">
                        <Label htmlFor={`scale-max-${app.id}`}>{t('app.containerOpsPanel.maxReplicas', 'Max replicas')}</Label>
                        <Input
                            id={`scale-max-${app.id}`}
                            type="number"
                            min={1}
                            value={form.max_replicas}
                            onChange={(e) => setField('max_replicas', e.target.value)}
                            disabled={loading}
                        />
                    </div>
                    <div className="container-ops__input">
                        <Label htmlFor={`scale-cpu-high-${app.id}`}>{t('app.containerOpsPanel.cpuHigh', 'CPU high (%)')}</Label>
                        <Input
                            id={`scale-cpu-high-${app.id}`}
                            type="number"
                            min={0}
                            max={100}
                            value={form.cpu_high_percent}
                            onChange={(e) => setField('cpu_high_percent', e.target.value)}
                            disabled={loading}
                        />
                    </div>
                    <div className="container-ops__input">
                        <Label htmlFor={`scale-cpu-low-${app.id}`}>{t('app.containerOpsPanel.cpuLow', 'CPU low (%)')}</Label>
                        <Input
                            id={`scale-cpu-low-${app.id}`}
                            type="number"
                            min={0}
                            max={100}
                            value={form.cpu_low_percent}
                            onChange={(e) => setField('cpu_low_percent', e.target.value)}
                            disabled={loading}
                        />
                    </div>
                </div>

                <div className="app-detail-actions container-ops__actions">
                    <Button size="sm" onClick={handleSave} disabled={saving || loading}>
                        {saving ? 'Saving…' : 'Save policy'}
                    </Button>
                </div>

                <div className="container-ops__manual">
                    <div className="container-ops__input">
                        <Label htmlFor={`scale-manual-${app.id}`}>{t('app.containerOpsPanel.manualReplicas', 'Manual replicas')}</Label>
                        <Input
                            id={`scale-manual-${app.id}`}
                            type="number"
                            min={0}
                            value={manualReplicas}
                            onChange={(e) => setManualReplicas(e.target.value)}
                            disabled={scaling}
                        />
                    </div>
                    <Button variant="outline" size="sm" onClick={handleManualScale} disabled={scaling || loading}>
                        {scaling ? 'Scaling…' : 'Apply'}
                    </Button>
                </div>
            </div>
        </div>
    );
};

// ============================================================
// Panel shell
// ============================================================
const ContainerOpsPanel = ({ app, onChanged }) => {
    if (!app) return null;

    return (
        <div className="container-ops">
            <ImageUpdateSection app={app} onChanged={onChanged} />
            <RegistrySection app={app} onChanged={onChanged} />
            <AutoSleepSection app={app} onChanged={onChanged} />
            <AutoScaleSection app={app} onChanged={onChanged} />
        </div>
    );
};

export default ContainerOpsPanel;
