import { statusKind } from '@/components/ds/status';
import { useState } from 'react';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { Pill, ScoreGauge, KpiBand, MetricCard } from '@/components/ds';
import { useTranslation } from 'react-i18next';
import {
    ShieldCheck,
    RefreshCw,
    CheckCircle2,
    AlertTriangle,
    Circle,
    Siren,
    Bug,
    Radar,
} from 'lucide-react';

const capitalize = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// Status glyph per check state — paired with the label so state never relies on
// color alone (color-blind operators), per the product a11y bar.
const STATE_ICON = { pass: CheckCircle2, warn: AlertTriangle, unknown: Circle };

const OverviewTab = ({ status, clamavStatus, clamavLoading, onRefresh, onNavigateTab }) => {
    const { t } = useTranslation();
    // One action runs at a time; `busyKey` names it so only that row spins and
    // the rest disable (no double-submits against the same daemon).
    const [busyKey, setBusyKey] = useState(null);
    const [error, setError] = useState(null);

    const alerts = status?.recent_alerts || {};
    const integrity = status?.file_integrity || {};
    const integrityChanges = alerts.integrity_changes || 0;
    const scanRunning = status?.scan_status === 'running';

    async function runFix(key, fn) {
        setBusyKey(key);
        setError(null);
        try {
            await fn();
            await onRefresh?.();
        } catch (err) {
            setError(err.message || 'That action failed. Check the server logs and try again.');
        } finally {
            setBusyKey(null);
        }
    }

    // Posture checks — real boolean signals from this tab's props. Each failing
    // check carries a `fix`: a server action (re-pulls status on success) or a
    // `nav` jump to the tab that resolves it. Checks that can't be evaluated yet
    // (ClamAV still loading) stay 'unknown' and are excluded from the score.
    const checks = [
        {
            key: 'clamav-install',
            labelKey: 'app.overviewTab.clamavAntivirusInstalled', label: 'ClamAV antivirus installed',
            state: clamavLoading ? 'unknown' : (clamavStatus?.installed ? 'pass' : 'warn'),
            detail: clamavLoading ? 'checking…' : (clamavStatus?.installed ? 'installed' : 'not installed'),
            fix: !clamavLoading && !clamavStatus?.installed
                ? { labelKey: 'app.overviewTab.installClamav', label: 'Install ClamAV', run: () => api.installClamAV() }
                : null,
        },
        {
            key: 'clamav-service',
            labelKey: 'app.overviewTab.clamavServiceRunning', label: 'ClamAV service running',
            state: clamavLoading || !clamavStatus?.installed
                ? 'unknown'
                : (clamavStatus?.service_running ? 'pass' : 'warn'),
            detail: clamavLoading
                ? 'checking…'
                : (!clamavStatus?.installed ? 'n/a' : (clamavStatus?.service_running ? 'running' : 'stopped')),
            fix: !clamavLoading && clamavStatus?.installed && !clamavStatus?.service_running
                ? { labelKey: 'app.overviewTab.startService', label: 'Start service', run: () => api.startClamAV() }
                : null,
        },
        {
            key: 'integrity-enabled',
            labelKey: 'app.overviewTab.fileIntegrityMonitoringEnabled', label: 'File integrity monitoring enabled',
            state: integrity.enabled ? 'pass' : 'warn',
            detail: integrity.enabled ? 'enabled' : 'disabled',
            fix: integrity.enabled
                ? null
                : { labelKey: 'app.overviewTab.enableMonitoring', label: 'Enable monitoring', run: () => api.updateSecurityConfig({ file_integrity: { enabled: true } }) },
        },
        {
            key: 'integrity-baseline',
            labelKey: 'app.overviewTab.integrityBaselineInitialized', label: 'Integrity baseline initialized',
            state: integrity.database_exists ? 'pass' : 'warn',
            detail: integrity.database_exists ? 'initialized' : 'not initialized',
            fix: integrity.database_exists
                ? null
                : { labelKey: 'app.overviewTab.initializeBaseline', label: 'Initialize baseline', run: () => api.initializeIntegrityDatabase() },
        },
        {
            key: 'integrity-clean',
            labelKey: 'app.overviewTab.noIntegrityChanges24h', label: 'No integrity changes (24h)',
            state: integrityChanges > 0 ? 'warn' : 'pass',
            detail: integrityChanges > 0 ? `${integrityChanges} detected` : 'clean',
            fix: integrityChanges > 0
                ? { labelKey: 'app.overviewTab.reviewChanges', label: 'Review changes', run: () => onNavigateTab?.('integrity'), nav: true }
                : null,
        },
        {
            key: 'alerts',
            labelKey: 'app.overviewTab.securityAlertsConfigured', label: 'Security alerts configured',
            state: status?.notifications_enabled ? 'pass' : 'warn',
            detail: status?.notifications_enabled ? 'enabled' : 'disabled',
            fix: status?.notifications_enabled
                ? null
                : {
                    labelKey: 'app.overviewTab.enableAlerts', label: 'Enable alerts',
                    run: () => api.updateSecurityConfig({
                        notifications: { on_malware_found: true, on_integrity_change: true, on_suspicious_activity: true },
                    }),
                },
        },
    ];

    const scored = checks.filter((c) => c.state !== 'unknown');
    const score = scored.length
        ? Math.round((scored.filter((c) => c.state === 'pass').length / scored.length) * 100)
        : null;
    const scoreColor = score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--red)';
    const warnCount = checks.filter((c) => c.state === 'warn').length;

    // Live event counts — the at-a-glance readouts that used to be a page-wide
    // KPI strip on every tab. They live here now, where they're relevant.
    const kpis = [
        { key: 'alerts', icon: Siren, value: alerts.total || 0, labelKey: 'app.overviewTab.alerts24h', label: 'Alerts · 24h', tone: alerts.total > 0 ? 'amber' : 'green' },
        { key: 'malware', icon: Bug, value: alerts.malware_detections || 0, labelKey: 'app.overviewTab.malware', label: 'Malware', tone: alerts.malware_detections > 0 ? 'red' : 'green' },
        { key: 'scan', icon: Radar, value: capitalize(status?.scan_status) || 'Idle', labelKey: 'app.overviewTab.scan', label: 'Scan', tone: scanRunning ? 'cyan' : 'accent' },
    ];

    const defsUpdated = clamavStatus?.last_update ? new Date(clamavStatus.last_update).toLocaleDateString() : null;
    const busy = busyKey !== null;

    return (
        <div className="security-overview">
            {error && <div className="alert alert-danger">{error}</div>}

            <div className="card sec-posture-card">
                <div className="card-header">
                    <h3><ShieldCheck size={13} /> {t('app.overviewTab.securityPosture', 'Security posture')}</h3>
                    <Button variant="outline" size="sm" onClick={() => runFix('recheck', async () => {})} disabled={busy}>
                        <RefreshCw size={13} className={busyKey === 'recheck' ? 'sec-spin' : undefined} /> {t('app.overviewTab.reCheck', 'Re-check')}
                    </Button>
                </div>
                <div className="card-body">
                    <div className="sec-posture__top">
                        {score !== null ? (
                            <ScoreGauge value={score} size={104} stroke={9} color={scoreColor} label="posture" />
                        ) : (
                            <div className="sec-posture__pending">
                                <RefreshCw size={18} className="sec-spin" />
                                <span>{t('app.overviewTab.computing', 'Computing…')}</span>
                            </div>
                        )}

                        <div className="sec-posture__summary">
                            <p className="sec-posture__verdict">
                                {score === null
                                    ? 'Checking this server…'
                                    : warnCount === 0
                                        ? 'All hardening checks pass.'
                                        : `${warnCount} ${warnCount === 1 ? 'check needs' : 'checks need'} attention.`}
                            </p>
                            <KpiBand dense className="sec-posture__kpis">
                                {kpis.map((k) => {
                                    const Icon = k.icon;
                                    return (
                                        <MetricCard
                                            key={k.key}
                                            icon={<Icon size={16} />}
                                            tone={k.tone}
                                            value={k.value}
                                            label={k.label}
                                        />
                                    );
                                })}
                            </KpiBand>
                        </div>
                    </div>

                    <div className="sec-posture__checks">
                        {checks.map((c) => {
                            const Icon = STATE_ICON[c.state];
                            const rowBusy = busyKey === c.key;
                            return (
                                <div key={c.key} className={`sec-posture__check sec-posture__check--${c.state}`}>
                                    <Icon size={15} className="sec-posture__ico" />
                                    <span className="sec-posture__label">{c.label}</span>
                                    <span className="sec-posture__detail">{c.detail}</span>
                                    {c.fix ? (
                                        <Button
                                            variant={c.fix.nav ? 'ghost' : 'outline'}
                                            size="sm"
                                            className="sec-posture__fix"
                                            onClick={() => (c.fix.nav ? c.fix.run() : runFix(c.key, c.fix.run))}
                                            disabled={busy}
                                        >
                                            {rowBusy ? 'Working…' : c.fix.label}
                                        </Button>
                                    ) : (
                                        <Pill kind={statusKind(c.state)}>{c.state === 'unknown' ? 'pending' : c.state}</Pill>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    <p className="sec-hint sec-posture__foot">
                        {clamavStatus?.installed && (
                            <>
                                {t('app.overviewTab.virusDefinitions', 'Virus definitions')} {defsUpdated ? `updated ${defsUpdated}` : 'status unknown'}
                                {' · '}
                                <Button
                                    variant="link"
                                    size="sm"
                                    className="sec-posture__inline"
                                    onClick={() => runFix('defs', () => api.updateVirusDefinitions())}
                                    disabled={busy}
                                >
                                    {busyKey === 'defs' ? 'Updating…' : 'Update definitions'}
                                </Button>
                                {'. '}
                            </>
                        )}
                        {t('app.overviewTab.addAlertDeliveryChannelsDiscordSlack', 'Add alert delivery channels (Discord, Slack, Telegram) in Settings → Notifications.')}
                    </p>
                </div>
            </div>
        </div>
    );
};

export default OverviewTab;
