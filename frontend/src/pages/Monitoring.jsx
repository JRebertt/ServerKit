import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import useTabParam from '../hooks/useTabParam';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import DoctorPanel from '../components/monitoring/DoctorPanel';
import MonitoringOverview from '../components/monitoring/MonitoringOverview';
import FleetCapacityPanel from '../components/monitoring/FleetCapacityPanel';
import FleetAlertsPanel from '../components/monitoring/FleetAlertsPanel';
import FleetThresholdsPanel from '../components/monitoring/FleetThresholdsPanel';
import ServerScopePicker from '../components/monitoring/ServerScopePicker';
import { useMonitorScope } from '../components/monitoring/useMonitorScope';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Pill } from '@/components/ds';
import { ProviderBrandIcon } from '../components/icons/ProviderBrands';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import {
    Activity, Bell, Cpu, Gauge as GaugeIcon, HardDrive, MemoryStick,
    PlayCircle, RefreshCw, Settings, Siren,
} from 'lucide-react';

// One section per top-bar tab. There is deliberately no second tab strip inside
// the page: the group's own bar (MONITOR_TABS) carries these, the way the
// design mock does — a nav under a nav reads as two competing headers.
const VALID_TABS = ['overview', 'alerts', 'rules', 'capacity', 'doctor'];

// Old deep links from when Alert Rules and Delivery were separate inner tabs.
const TAB_ALIASES = { thresholds: 'rules', config: 'rules', fleet: 'overview', 'fleet-alerts': 'alerts' };

const DEFAULT_THRESHOLDS = {
    cpu_percent: 80,
    memory_percent: 85,
    disk_percent: 90,
    load_average: 5.0,
};

// Brand glyphs, not three copies of the generic webhook icon: Discord, Slack
// and a raw webhook were all rendering the same shape, which made the tiles
// look broken. `brand` maps to the shared Connections icon set so a channel
// wears the same face here as it does everywhere else in the panel.
const CHANNEL_META = {
    discord: { label: 'Discord', brand: 'chat_discord' },
    slack: { label: 'Slack', brand: 'chat_slack' },
    telegram: { label: 'Telegram', brand: 'chat_telegram' },
    email: { label: 'Email', brand: 'smtp' },
    generic_webhook: { label: 'Webhook', brand: 'chat_webhook' },
};

const RULE_ICONS = {
    cpu_percent: Cpu,
    memory_percent: MemoryStick,
    disk_percent: HardDrive,
    load_average: GaugeIcon,
};

const SPEEDTEST_POLL_INTERVAL_MS = 3000;
const SPEEDTEST_POLL_TIMEOUT_MS = 90000;

function formatTimestamp(timestamp) {
    if (!timestamp) return 'Never';
    return new Date(timestamp).toLocaleString();
}

function formatNumber(value, digits = 1) {
    if (typeof value !== 'number' || Number.isNaN(value)) return '-';
    return value.toFixed(digits);
}

function getSeverityTone(severity) {
    switch (severity) {
        case 'critical': return 'red';
        case 'warning': return 'amber';
        case 'info': return 'cyan';
        default: return 'gray';
    }
}

const Monitoring = () => {
    const toast = useToast();
    const [status, setStatus] = useState(null);
    const [thresholds, setThresholds] = useState(DEFAULT_THRESHOLDS);
    const [alertHistory, setAlertHistory] = useState([]);
    const [loading, setLoading] = useState(true);
    const [savingConfig, setSavingConfig] = useState(false);
    const [savingThresholds, setSavingThresholds] = useState(false);
    const [checkingAlerts, setCheckingAlerts] = useState(false);
    const [error, setError] = useState(null);
    const [rawTab] = useTabParam('/monitoring', VALID_TABS);
    const activeTab = TAB_ALIASES[rawTab] || rawTab;

    // Which host every section on this page is describing (URL-backed, so it
    // survives tab changes and shared links).
    const { scope, isHost, server, servers, setScope, label: scopeLabel } = useMonitorScope();

    const [configForm, setConfigForm] = useState({ enabled: false, check_interval: 60 });
    const [thresholdForm, setThresholdForm] = useState(DEFAULT_THRESHOLDS);
    const [speedTest, setSpeedTest] = useState(null);
    const [speedTestRunning, setSpeedTestRunning] = useState(false);
    // Bumped by the top-bar Refresh so the scope-driven panels reload with the
    // host-scoped data instead of each growing a refresh button of its own.
    const [refreshKey, setRefreshKey] = useState(0);

    const loadSpeedTest = async () => {
        try {
            const res = await api.getSpeedTest();
            setSpeedTest(res);
            return res;
        } catch {
            // Optional endpoint — never block the page on it.
            return null;
        }
    };

    const loadData = async () => {
        try {
            setLoading(true);
            setError(null);
            const [statusRes, configRes, thresholdsRes, historyRes] = await Promise.all([
                api.getMonitoringStatus(),
                api.getMonitoringConfig(),
                api.getMonitoringThresholds(),
                api.getAlertHistory(50),
            ]);

            const nextThresholds = { ...DEFAULT_THRESHOLDS, ...(thresholdsRes.thresholds || {}) };
            setStatus(statusRes);
            setThresholds(nextThresholds);
            setThresholdForm(nextThresholds);
            setAlertHistory(historyRes.alerts || []);
            setConfigForm({
                enabled: Boolean(configRes.enabled),
                check_interval: configRes.check_interval || 60,
            });
        } catch (err) {
            setError(err.message || 'Failed to load monitoring data');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadData();
        loadSpeedTest();
    }, []);

    const metricRules = useMemo(() => {
        const metrics = status?.current_metrics || {};
        return [
            {
                key: 'cpu_percent', label: 'CPU usage', unit: '%',
                current: metrics.cpu?.percent,
                threshold: thresholdForm.cpu_percent,
            },
            {
                key: 'memory_percent', label: 'Memory usage', unit: '%',
                current: metrics.memory?.percent,
                threshold: thresholdForm.memory_percent,
            },
            {
                key: 'disk_percent', label: 'Disk usage', unit: '%',
                current: metrics.disk?.percent,
                threshold: thresholdForm.disk_percent,
            },
            {
                key: 'load_average', label: 'Load average', unit: '',
                current: metrics.load_average?.['1min'],
                threshold: thresholdForm.load_average,
            },
        ];
    }, [status, thresholdForm]);

    const notificationChannels = useMemo(() => (
        Object.entries(status?.notifications || {}).map(([key, channel]) => ({
            key,
            ...channel,
            ...(CHANNEL_META[key] || { label: key, brand: null }),
        }))
    ), [status]);

    const activeAlerts = status?.active_alerts || [];

    const handleToggleMonitoring = async () => {
        try {
            if (status?.enabled) {
                await api.stopMonitoring();
                toast.success('Monitoring stopped');
            } else {
                await api.startMonitoring();
                toast.success('Monitoring started');
            }
            await loadData();
        } catch (err) {
            setError(err.message || 'Failed to update monitoring state');
        }
    };

    const handleSaveConfig = async (e) => {
        e.preventDefault();
        try {
            setSavingConfig(true);
            const wasEnabled = Boolean(status?.enabled);
            await api.updateMonitoringConfig({
                enabled: configForm.enabled,
                check_interval: Number(configForm.check_interval) || 60,
            });
            if (configForm.enabled !== wasEnabled) {
                if (configForm.enabled) await api.startMonitoring();
                else await api.stopMonitoring();
            }
            toast.success('Monitoring delivery saved');
            await loadData();
        } catch (err) {
            toast.error(err.message || 'Failed to save monitoring settings');
        } finally {
            setSavingConfig(false);
        }
    };

    const handleSaveThresholds = async (e) => {
        e.preventDefault();
        try {
            setSavingThresholds(true);
            await api.updateMonitoringThresholds({
                cpu_percent: Number(thresholdForm.cpu_percent),
                memory_percent: Number(thresholdForm.memory_percent),
                disk_percent: Number(thresholdForm.disk_percent),
                load_average: Number(thresholdForm.load_average),
            });
            toast.success('Alert rules saved');
            await loadData();
        } catch (err) {
            toast.error(err.message || 'Failed to save alert rules');
        } finally {
            setSavingThresholds(false);
        }
    };

    const handleCheckAlerts = async () => {
        try {
            setCheckingAlerts(true);
            const result = await api.checkAlerts();
            const count = result.alerts?.length || 0;
            toast[count > 0 ? 'warning' : 'success'](`${count} active alert${count !== 1 ? 's' : ''}`);
            await loadData();
        } catch (err) {
            toast.error(err.message || 'Alert check failed');
        } finally {
            setCheckingAlerts(false);
        }
    };

    const handleRunSpeedTest = async () => {
        try {
            setSpeedTestRunning(true);
            await api.runSpeedTest();
            const previousTestedAt = speedTest?.last_result?.tested_at || null;
            const deadline = Date.now() + SPEEDTEST_POLL_TIMEOUT_MS;
            while (Date.now() < deadline) {
                await new Promise((resolve) => setTimeout(resolve, SPEEDTEST_POLL_INTERVAL_MS));
                const res = await loadSpeedTest();
                const latest = res?.last_result;
                if (latest?.tested_at && latest.tested_at !== previousTestedAt) {
                    if (latest.success === false) toast.error(latest.error || 'Speed test failed');
                    else toast.success('Speed test complete');
                    return;
                }
            }
            toast.warning('Speed test is still running — refresh in a moment');
        } catch (err) {
            toast.error(err.message || 'Failed to start speed test');
        } finally {
            setSpeedTestRunning(false);
        }
    };

    const updateThreshold = (key, value) => {
        setThresholdForm((current) => ({ ...current, [key]: value }));
    };

    useTopbarActions(() =>
        (
            <>
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => { loadData(); setRefreshKey((k) => k + 1); }}
                >
                    <RefreshCw size={16} />
                    Refresh
                </Button>
                <Button
                    size="sm"
                    variant={status?.enabled ? 'destructive' : 'default'}
                    onClick={handleToggleMonitoring}
                >
                    {status?.enabled
                        ? <><Activity size={16} />Stop Monitoring</>
                        : <><PlayCircle size={16} />Start Monitoring</>}
                </Button>
                <ServerScopePicker
                    scope={scope}
                    servers={servers}
                    onChange={setScope}
                    label={scopeLabel}
                />
            </>
        ),
        [status?.enabled, scope, servers.length, scopeLabel]
    );

    if (loading) {
        return (
            <div className="sk-tabgroup__inner monitoring-page">
                <EmptyState loading loadingVariant="chart" size="lg" title="Loading monitoring data" />
            </div>
        );
    }

    return (
        <div className="sk-tabgroup__inner monitoring-page">
            {error && (
                <div className="alert alert-danger">
                    {error}
                    <button type="button" onClick={() => setError(null)} className="alert-close">&times;</button>
                </div>
            )}

            {activeTab === 'overview' && (
                <MonitoringOverview
                    scope={scope}
                    isHost={isHost}
                    scopeLabel={isHost ? 'This server' : (server?.name || scopeLabel)}
                    status={status}
                    activeAlerts={activeAlerts}
                    speedTest={speedTest}
                    speedTestRunning={speedTestRunning}
                    onRunSpeedTest={handleRunSpeedTest}
                    thresholds={thresholds}
                    onScopeChange={setScope}
                    refreshKey={refreshKey}
                />
            )}

            {activeTab === 'alerts' && (
                <div className="monitoring-stack">
                    <section className="monitoring-panel">
                        <div className="monitoring-panel__header">
                            <div>
                                <h3>This server</h3>
                                <span className="mon-panel-sub">
                                    {activeAlerts.length} firing · {alertHistory.length} in history
                                </span>
                            </div>
                            <Button variant="outline" size="sm" onClick={handleCheckAlerts} disabled={checkingAlerts}>
                                <Siren size={14} />
                                {checkingAlerts ? 'Checking…' : 'Check now'}
                            </Button>
                        </div>
                        {alertHistory.length === 0 && activeAlerts.length === 0 ? (
                            <p className="mon-panel-hint">
                                Nothing has crossed a limit yet. Rules live one tab over.
                            </p>
                        ) : (
                            <div className="mon-alert-list">
                                {[...activeAlerts.map((a) => ({ ...a, firing: true })), ...alertHistory]
                                    .map((alert, index) => (
                                        <article key={`${alert.timestamp || 'now'}-${index}`} className="mon-alert-row">
                                            <span className={`mon-sev mon-sev--${alert.severity}`} />
                                            <div className="mon-alert-row__body">
                                                <div className="mon-alert-row__title">{alert.message}</div>
                                                <div className="mon-alert-row__sub">
                                                    {alert.type} · {formatNumber(alert.value)} / {alert.threshold}
                                                </div>
                                            </div>
                                            <div className="mon-alert-row__end">
                                                <span className={`mon-state mon-state--${alert.firing ? 'red' : getSeverityTone(alert.severity)}`}>
                                                    {alert.firing ? 'firing' : alert.severity}
                                                </span>
                                                <span className="mon-alert-row__time">
                                                    {alert.firing ? 'now' : formatTimestamp(alert.timestamp)}
                                                </span>
                                            </div>
                                        </article>
                                    ))}
                            </div>
                        )}
                    </section>

                    {servers.length > 0 && <FleetAlertsPanel scope={scope} refreshKey={refreshKey} />}
                </div>
            )}

            {activeTab === 'rules' && (
                <div className="monitoring-stack">
                    <form className="monitoring-panel" onSubmit={handleSaveThresholds}>
                        <div className="monitoring-panel__header">
                            <div>
                                <h3>This server</h3>
                                <span className="mon-panel-sub">Limits for the machine running the panel</span>
                            </div>
                            <Button type="submit" size="sm" disabled={savingThresholds}>
                                {savingThresholds ? 'Saving…' : 'Save rules'}
                            </Button>
                        </div>
                        <div className="metric-rule-grid">
                            {metricRules.map((rule) => {
                                const Icon = RULE_ICONS[rule.key] || GaugeIcon;
                                const isTriggered = typeof rule.current === 'number' && rule.current > rule.threshold;
                                return (
                                    <article key={rule.key} className={`metric-rule-editor ${isTriggered ? 'is-alerting' : ''}`}>
                                        <div className="metric-rule-editor__main">
                                            <span className="mon-ico"><Icon size={15} /></span>
                                            <div>
                                                <h4>{rule.label}</h4>
                                                <span>
                                                    current {formatNumber(rule.current, rule.unit === '' ? 2 : 1)}{rule.unit}
                                                </span>
                                            </div>
                                        </div>
                                        <div className="metric-rule-editor__threshold">
                                            <Label htmlFor={`threshold-${rule.key}`}>Trigger above</Label>
                                            <Input
                                                id={`threshold-${rule.key}`}
                                                type="number"
                                                min={rule.key === 'load_average' ? '0.1' : '1'}
                                                max="100"
                                                step={rule.key === 'load_average' ? '0.1' : '1'}
                                                value={rule.threshold}
                                                onChange={(e) => updateThreshold(rule.key, e.target.value)}
                                            />
                                        </div>
                                        <Pill kind={isTriggered ? 'amber' : 'gray'}>
                                            {isTriggered ? 'would alert now' : 'quiet'}
                                        </Pill>
                                    </article>
                                );
                            })}
                        </div>
                    </form>

                    {servers.length > 0 && (
                        <FleetThresholdsPanel servers={servers} refreshKey={refreshKey} />
                    )}

                    <div className="monitoring-delivery-layout">
                        <form className="monitoring-panel" onSubmit={handleSaveConfig}>
                            <div className="monitoring-panel__header">
                                <div>
                                    <h3>Scheduler</h3>
                                    <span className="mon-panel-sub">How often the checks run</span>
                                </div>
                                <Button type="submit" size="sm" disabled={savingConfig}>
                                    {savingConfig ? 'Saving…' : 'Save'}
                                </Button>
                            </div>
                            <div className="monitoring-switch-row">
                                <div>
                                    <strong>Run resource checks</strong>
                                    <span>{configForm.enabled ? 'Enabled' : 'Paused'}</span>
                                </div>
                                <Switch
                                    checked={configForm.enabled}
                                    onCheckedChange={(checked) => setConfigForm({ ...configForm, enabled: checked })}
                                />
                            </div>
                            <div className="form-group">
                                <Label htmlFor="monitoring-interval">Check interval</Label>
                                <Input
                                    id="monitoring-interval"
                                    type="number"
                                    min="10"
                                    max="3600"
                                    value={configForm.check_interval}
                                    onChange={(e) => setConfigForm({ ...configForm, check_interval: e.target.value })}
                                />
                                <span className="form-help">Seconds between checks.</span>
                            </div>
                        </form>

                        <section className="monitoring-panel">
                            <div className="monitoring-panel__header">
                                <div>
                                    <h3>Delivery</h3>
                                    <span className="mon-panel-sub">Where an alert goes when it fires</span>
                                </div>
                                <Button size="sm" asChild>
                                    <Link to="/settings/notifications">
                                        <Settings size={14} /> Configure
                                    </Link>
                                </Button>
                            </div>
                            <div className="notification-channel-grid">
                                {notificationChannels.map((channel) => {
                                    const ready = channel.enabled && channel.configured;
                                    return (
                                        <article
                                            key={channel.key}
                                            className={`notification-channel-tile${ready ? ' is-ready' : ''}${channel.configured ? '' : ' is-unset'}`}
                                        >
                                            <span className="mon-ico">
                                                {channel.brand
                                                    ? <ProviderBrandIcon provider={channel.brand} size={16} />
                                                    : <Bell size={15} />}
                                            </span>
                                            <div>
                                                <strong>{channel.label}</strong>
                                                <span>
                                                    {ready
                                                        ? 'Sending alerts'
                                                        : channel.configured
                                                            ? 'Configured but off'
                                                            : 'Not configured'}
                                                </span>
                                            </div>
                                            <Pill kind={ready ? 'green' : channel.configured ? 'amber' : 'gray'}>
                                                {ready ? 'on' : 'off'}
                                            </Pill>
                                        </article>
                                    );
                                })}
                            </div>
                        </section>
                    </div>
                </div>
            )}

            {activeTab === 'capacity' && (
                <FleetCapacityPanel scope={scope} refreshKey={refreshKey} />
            )}

            {activeTab === 'doctor' && <DoctorPanel />}
        </div>
    );
};

export default Monitoring;
