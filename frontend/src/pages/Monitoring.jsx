import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import useTabParam from '../hooks/useTabParam';
import api from '../services/api';
import { formatBytes } from '@/utils/formatBytes';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import DoctorPanel from '../components/monitoring/DoctorPanel';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MetricCard, Pill, Gauge } from '@/components/ds';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import {
    Activity,
    ArrowDown,
    ArrowUp,
    Bell,
    Clock,
    Cpu,
    Gauge as GaugeIcon,
    HardDrive,
    Mail,
    MemoryStick,
    PlayCircle,
    RefreshCw,
    Settings,
    Siren,
    Timer,
    Webhook,
    Zap,
} from 'lucide-react';

const VALID_TABS = ['overview', 'alerts', 'config', 'thresholds', 'doctor'];

const DEFAULT_THRESHOLDS = {
    cpu_percent: 80,
    memory_percent: 85,
    disk_percent: 90,
    load_average: 5.0,
};

const CHANNEL_META = {
    discord: { label: 'Discord', icon: Webhook },
    slack: { label: 'Slack', icon: Webhook },
    telegram: { label: 'Telegram', icon: Bell },
    email: { label: 'Email', icon: Mail },
    generic_webhook: { label: 'Webhook', icon: Webhook },
};

// Gauge tints follow the Servers list convention (CPU accent / RAM cyan / disk green).
const METRIC_COLORS = {
    cpu_percent: 'var(--accent-bright)',
    memory_percent: 'var(--cyan)',
    disk_percent: 'var(--green)',
    load_average: 'var(--violet)',
};

function formatTimestamp(timestamp) {
    if (!timestamp) return 'Never';
    return new Date(timestamp).toLocaleString();
}

function formatNumber(value, digits = 1) {
    if (typeof value !== 'number' || Number.isNaN(value)) return '-';
    return value.toFixed(digits);
}

function formatMetric(value, unit = '%') {
    if (typeof value !== 'number' || Number.isNaN(value)) return '-';
    return `${value.toFixed(unit === '' ? 2 : 1)}${unit}`;
}

function formatSpeedValue(value, digits = 1) {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—';
    return value.toFixed(digits);
}

const SPEEDTEST_POLL_INTERVAL_MS = 3000;
const SPEEDTEST_POLL_TIMEOUT_MS = 90000;

function getSeverityTone(severity) {
    switch (severity) {
        case 'critical':
            return 'red';
        case 'warning':
            return 'amber';
        case 'info':
            return 'cyan';
        default:
            return 'gray';
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
    const [activeTab, setActiveTab] = useTabParam('/monitoring', VALID_TABS);

    const [configForm, setConfigForm] = useState({
        enabled: false,
        check_interval: 60,
    });

    const [thresholdForm, setThresholdForm] = useState(DEFAULT_THRESHOLDS);
    const [speedTest, setSpeedTest] = useState(null);
    const [speedTestRunning, setSpeedTestRunning] = useState(false);

    const loadSpeedTest = async () => {
        try {
            const res = await api.getSpeedTest();
            setSpeedTest(res);
            return res;
        } catch {
            // Speed test endpoint is optional — never block the page on it.
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
                key: 'cpu_percent',
                label: 'CPU usage',
                description: 'cpu',
                icon: Cpu,
                unit: '%',
                current: metrics.cpu?.percent,
                threshold: thresholdForm.cpu_percent,
                persistedThreshold: thresholds.cpu_percent,
                gaugePct: metrics.cpu?.percent ?? 0,
                mini: [{ k: 'cores', v: metrics.cpu?.cores ?? '-' }],
            },
            {
                key: 'memory_percent',
                label: 'Memory usage',
                description: 'memory',
                icon: MemoryStick,
                unit: '%',
                current: metrics.memory?.percent,
                threshold: thresholdForm.memory_percent,
                persistedThreshold: thresholds.memory_percent,
                gaugePct: metrics.memory?.percent ?? 0,
                mini: [{ k: 'used', v: `${formatBytes(metrics.memory?.used)} / ${formatBytes(metrics.memory?.total)}` }],
            },
            {
                key: 'disk_percent',
                label: 'Disk usage',
                description: 'disk',
                icon: HardDrive,
                unit: '%',
                current: metrics.disk?.percent,
                threshold: thresholdForm.disk_percent,
                persistedThreshold: thresholds.disk_percent,
                gaugePct: metrics.disk?.percent ?? 0,
                mini: [{ k: 'used', v: `${formatBytes(metrics.disk?.used)} / ${formatBytes(metrics.disk?.total)}` }],
            },
            {
                key: 'load_average',
                label: 'Load average',
                description: 'load',
                icon: GaugeIcon,
                unit: '',
                current: metrics.load_average?.['1min'],
                threshold: thresholdForm.load_average,
                persistedThreshold: thresholds.load_average,
                gaugePct: thresholds.load_average > 0
                    ? ((metrics.load_average?.['1min'] ?? 0) / thresholds.load_average) * 100
                    : 0,
                mini: [
                    { k: '5m', v: formatNumber(metrics.load_average?.['5min'], 2) },
                    { k: '15m', v: formatNumber(metrics.load_average?.['15min'], 2) },
                ],
            },
        ];
    }, [status, thresholdForm, thresholds]);

    const notificationChannels = useMemo(() => {
        return Object.entries(status?.notifications || {}).map(([key, channel]) => ({
            key,
            ...channel,
            ...(CHANNEL_META[key] || { label: key, icon: Bell }),
        }));
    }, [status]);

    const activeAlerts = status?.active_alerts || [];
    const enabledChannelCount = notificationChannels.filter((channel) => channel.enabled && channel.configured).length;
    const alertRuleCount = metricRules.length;

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
                if (configForm.enabled) {
                    await api.startMonitoring();
                } else {
                    await api.stopMonitoring();
                }
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
                    if (latest.success === false) {
                        toast.error(latest.error || 'Speed test failed');
                    } else {
                        toast.success('Speed test complete');
                    }
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
        setThresholdForm((current) => ({
            ...current,
            [key]: value,
        }));
    };

    useTopbarActions(() =>
        (
            <>
                <Button size="sm" variant="outline" onClick={loadData}>
                    <RefreshCw size={16} />
                    Refresh
                </Button>
                <Button
                    size="sm"
                    variant={status?.enabled ? 'destructive' : 'default'}
                    onClick={handleToggleMonitoring}
                >
                    {status?.enabled ? (
                        <>
                            <Activity size={16} />
                            Stop Monitoring
                        </>
                    ) : (
                        <>
                            <PlayCircle size={16} />
                            Start Monitoring
                        </>
                    )}
                </Button>
            </>
        ),
        [status?.enabled]
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

            <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList>
                    <TabsTrigger value="overview">Overview</TabsTrigger>
                    <TabsTrigger value="thresholds">Alert Rules</TabsTrigger>
                    <TabsTrigger value="config">Delivery</TabsTrigger>
                    <TabsTrigger value="alerts">History</TabsTrigger>
                    <TabsTrigger value="doctor">Doctor</TabsTrigger>
                </TabsList>

                <TabsContent value="overview">
                    <div className="monitoring-overview">
                        <section className={`monitoring-hero ${status?.enabled ? 'is-active' : ''}`}>
                            <div className="monitoring-hero__main">
                                <Pill kind={status?.enabled ? 'green' : 'gray'}>
                                    {status?.enabled ? 'Monitoring active' : 'Monitoring paused'}
                                </Pill>
                                <h2>{activeAlerts.length > 0 ? `${activeAlerts.length} active alert${activeAlerts.length !== 1 ? 's' : ''}` : 'No active alerts'}</h2>
                                <p>
                                    Checks run every {status?.check_interval || configForm.check_interval || 60} seconds.
                                </p>
                            </div>
                            <div className="monitoring-hero__actions">
                                <Button variant="outline" onClick={handleCheckAlerts} disabled={checkingAlerts}>
                                    <Siren size={16} />
                                    {checkingAlerts ? 'Checking...' : 'Check Now'}
                                </Button>
                            </div>
                        </section>

                        <div className="mon-kpis">
                            <MetricCard
                                tone={activeAlerts.length > 0 ? 'red' : 'green'}
                                icon={<Siren size={16} />}
                                value={activeAlerts.length}
                                label="Active alerts"
                            />
                            <MetricCard
                                tone="accent"
                                icon={<GaugeIcon size={16} />}
                                value={alertRuleCount}
                                label="Alert rules"
                            />
                            <MetricCard
                                tone="cyan"
                                icon={<Bell size={16} />}
                                value={enabledChannelCount}
                                label="Delivery channels"
                            >
                                <div className="sk-kpi__sub"><span>{notificationChannels.length} total</span></div>
                            </MetricCard>
                            <MetricCard
                                tone="violet"
                                icon={<Clock size={16} />}
                                value={alertHistory.length}
                                label="History entries"
                            />
                        </div>

                        <section>
                            <div className="mon-section-head">
                                <h3>Current Metrics</h3>
                                <Button size="sm" variant="outline" onClick={() => setActiveTab('thresholds')}>
                                    <Settings size={14} />
                                    Rules
                                </Button>
                            </div>
                            <div className="mon-host-grid">
                                {metricRules.map((rule) => {
                                    const Icon = rule.icon;
                                    const isTriggered = typeof rule.current === 'number' && rule.current > rule.persistedThreshold;
                                    return (
                                        <article key={rule.key} className={`mon-host-card ${isTriggered ? 'is-alerting' : ''}`}>
                                            <div className="mon-host-card__head">
                                                <span className="mon-ico mon-ico--sm">
                                                    <Icon size={14} />
                                                </span>
                                                <span className="mon-host-card__name">{rule.label}</span>
                                                <Pill kind={isTriggered ? 'amber' : 'green'}>{isTriggered ? 'alerting' : 'ok'}</Pill>
                                            </div>
                                            <div className="mon-host-card__value">{formatMetric(rule.current, rule.unit)}</div>
                                            <Gauge
                                                value={rule.gaugePct}
                                                color={isTriggered ? 'var(--amber)' : METRIC_COLORS[rule.key]}
                                            />
                                            <div className="mon-host-card__mini">
                                                <span>limit <b>{formatMetric(rule.persistedThreshold, rule.unit)}</b></span>
                                                {rule.mini.map((m) => (
                                                    <span key={m.k}>{m.k} <b>{m.v}</b></span>
                                                ))}
                                            </div>
                                        </article>
                                    );
                                })}
                            </div>
                        </section>

                        <section className="monitoring-panel mon-speedtest">
                            <div className="monitoring-panel__header">
                                <h3>Speed Test</h3>
                                <Button size="sm" variant="outline" onClick={handleRunSpeedTest} disabled={speedTestRunning}>
                                    <Zap size={14} />
                                    {speedTestRunning ? 'Running...' : 'Run Test'}
                                </Button>
                            </div>
                            {speedTest?.last_result ? (
                                <>
                                    <div className="mon-speedtest__grid">
                                        <MetricCard
                                            tone="accent"
                                            icon={<ArrowDown size={16} />}
                                            value={formatSpeedValue(speedTest.last_result.download_mbps)}
                                            label="Download (Mbps)"
                                        />
                                        <MetricCard
                                            tone="cyan"
                                            icon={<ArrowUp size={16} />}
                                            value={formatSpeedValue(speedTest.last_result.upload_mbps)}
                                            label="Upload (Mbps)"
                                        />
                                        <MetricCard
                                            tone="violet"
                                            icon={<Timer size={16} />}
                                            value={formatSpeedValue(speedTest.last_result.latency_ms, 0)}
                                            label="Latency (ms)"
                                        />
                                    </div>
                                    <div className="mon-speedtest__meta">
                                        {speedTestRunning || speedTest.running ? (
                                            <Pill kind="amber">running</Pill>
                                        ) : (
                                            <Pill kind={speedTest.last_result.success === false ? 'red' : 'green'}>
                                                {speedTest.last_result.success === false ? 'failed' : 'ok'}
                                            </Pill>
                                        )}
                                        <span>Tested {formatTimestamp(speedTest.last_result.tested_at)}</span>
                                        {speedTest.last_result.success === false && speedTest.last_result.error && (
                                            <span className="mon-speedtest__error">{speedTest.last_result.error}</span>
                                        )}
                                    </div>
                                </>
                            ) : (
                                <div className="mon-speedtest__empty">
                                    <span>No speed test has been run yet. Run one to measure this server&apos;s connection.</span>
                                </div>
                            )}
                        </section>

                        {activeAlerts.length > 0 && (
                            <section className="monitoring-panel monitoring-panel--warning">
                                <div className="monitoring-panel__header">
                                    <h3>Active Alerts</h3>
                                    <span className="mon-firing-count">{activeAlerts.length} firing</span>
                                </div>
                                <div className="mon-alert-list">
                                    {activeAlerts.map((alert, index) => (
                                        <div key={`${alert.type}-${index}`} className="mon-alert-row">
                                            <span className={`mon-sev mon-sev--${alert.severity}`} />
                                            <div className="mon-alert-row__body">
                                                <div className="mon-alert-row__title">{alert.message}</div>
                                                <div className="mon-alert-row__sub">{alert.type} · {formatNumber(alert.value)} / {alert.threshold}</div>
                                            </div>
                                            <span className="mon-state mon-state--red">firing</span>
                                        </div>
                                    ))}
                                </div>
                            </section>
                        )}
                    </div>
                </TabsContent>

                <TabsContent value="thresholds">
                    <form className="monitoring-panel" onSubmit={handleSaveThresholds}>
                        <div className="monitoring-panel__header">
                            <h3>Alert Rules</h3>
                            <Button type="submit" disabled={savingThresholds}>
                                {savingThresholds ? 'Saving...' : 'Save Rules'}
                            </Button>
                        </div>
                        <div className="metric-rule-grid">
                            {metricRules.map((rule) => {
                                const Icon = rule.icon;
                                const isTriggered = typeof rule.current === 'number' && rule.current > rule.threshold;
                                return (
                                    <article key={rule.key} className={`metric-rule-editor ${isTriggered ? 'is-alerting' : ''}`}>
                                        <div className="metric-rule-editor__main">
                                            <span className="mon-ico">
                                                <Icon size={15} />
                                            </span>
                                            <div>
                                                <h4>{rule.label}</h4>
                                                <span>current {formatMetric(rule.current, rule.unit)}</span>
                                            </div>
                                        </div>
                                        <div className="metric-rule-editor__threshold">
                                            <Label htmlFor={`threshold-${rule.key}`}>Trigger above</Label>
                                            <Input
                                                id={`threshold-${rule.key}`}
                                                type="number"
                                                min={rule.key === 'load_average' ? '0.1' : '1'}
                                                max={rule.key === 'load_average' ? '100' : '100'}
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
                </TabsContent>

                <TabsContent value="config">
                    <div className="monitoring-delivery-layout">
                        <form className="monitoring-panel" onSubmit={handleSaveConfig}>
                            <div className="monitoring-panel__header">
                                <h3>Scheduler</h3>
                                <Button type="submit" disabled={savingConfig}>
                                    {savingConfig ? 'Saving...' : 'Save Delivery'}
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
                                <h3>Notification Channels</h3>
                                <Button size="sm" asChild>
                                    <Link to="/settings/notifications">
                                        <Settings size={14} />
                                        Configure
                                    </Link>
                                </Button>
                            </div>
                            <div className="notification-channel-grid">
                                {notificationChannels.map((channel) => {
                                    const Icon = channel.icon;
                                    const ready = channel.enabled && channel.configured;
                                    return (
                                        <article key={channel.key} className={`notification-channel-tile ${ready ? 'is-ready' : ''}`}>
                                            <span className="mon-ico">
                                                <Icon size={15} />
                                            </span>
                                            <div>
                                                <strong>{channel.label}</strong>
                                                <span>{ready ? 'Enabled' : channel.configured ? 'Configured' : 'Not configured'}</span>
                                            </div>
                                            <Pill kind={ready ? 'green' : 'gray'}>{ready ? 'ready' : 'off'}</Pill>
                                        </article>
                                    );
                                })}
                            </div>
                        </section>
                    </div>
                </TabsContent>

                <TabsContent value="alerts">
                    <section className="monitoring-panel">
                        <div className="monitoring-panel__header">
                            <h3>Alert History</h3>
                            <div>
                                <Button variant="outline" size="sm" onClick={handleCheckAlerts} disabled={checkingAlerts}>
                                    <Siren size={14} />
                                    Check Now
                                </Button>
                                <Button variant="outline" size="sm" onClick={loadData}>
                                    <RefreshCw size={14} />
                                    Refresh
                                </Button>
                            </div>
                        </div>
                        {alertHistory.length === 0 ? (
                            <EmptyState
                                icon={Bell}
                                title="No alerts yet"
                                description="Alerts will appear here once a threshold is crossed."
                            />
                        ) : (
                            <div className="mon-alert-list">
                                {alertHistory.map((alert, index) => (
                                    <article key={`${alert.timestamp}-${index}`} className="mon-alert-row">
                                        <span className={`mon-sev mon-sev--${alert.severity}`} />
                                        <div className="mon-alert-row__body">
                                            <div className="mon-alert-row__title">{alert.message}</div>
                                            <div className="mon-alert-row__sub">{alert.type} · {formatNumber(alert.value)} / {alert.threshold}</div>
                                        </div>
                                        <div className="mon-alert-row__end">
                                            <span className={`mon-state mon-state--${getSeverityTone(alert.severity)}`}>{alert.severity}</span>
                                            <span className="mon-alert-row__time">{formatTimestamp(alert.timestamp)}</span>
                                        </div>
                                    </article>
                                ))}
                            </div>
                        )}
                    </section>
                </TabsContent>

                <TabsContent value="doctor">
                    <DoctorPanel />
                </TabsContent>
            </Tabs>
        </div>
    );
};

export default Monitoring;
