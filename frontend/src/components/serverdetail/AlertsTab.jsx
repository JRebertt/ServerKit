import EmptyState from '../EmptyState';
import { BellRing } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
    SecurityAlertItem,
    AlertIcon,
    InfoCircleIcon,
} from './serverDetailShared';

const AlertsTab = ({ notifications, securityAlerts, onAcknowledge, onResolve }) => {
    const { t } = useTranslation();
    const sysItems = notifications || [];
    const secItems = securityAlerts || [];
    const openSec = secItems.filter(a => a.status === 'open');
    const ackSec = secItems.filter(a => a.status === 'acknowledged');

    if (sysItems.length === 0 && secItems.length === 0) {
        return (
            <div className="alerts-tab">
                <EmptyState
                    icon={BellRing}
                    title={t('app.alertsTab.allClear', 'All clear')}
                    description={t('app.alertsTab.noActiveAlertsForThisServer', 'No active alerts for this server.')}
                />
            </div>
        );
    }

    return (
        <div className="alerts-tab">
            {sysItems.length > 0 && (
                <section className="alerts-section">
                    <header className="alerts-section__header">
                        <h3>{t('common.labels.system', 'System')}</h3>
                        <span className="alerts-section__count">{sysItems.length}</span>
                    </header>
                    <ul className="notifications-list">
                        {sysItems.map((n) => (
                            <li key={n.id} className={`notification notification--${n.severity || 'info'}`}>
                                <span className="notification__icon">
                                    {n.severity === 'warning' || n.severity === 'danger' ? <AlertIcon /> : <InfoCircleIcon />}
                                </span>
                                <div className="notification__body">
                                    <div className="notification__title">{n.title}</div>
                                    <p className="notification__message">{n.message}</p>
                                </div>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {openSec.length > 0 && (
                <section className="alerts-section">
                    <header className="alerts-section__header">
                        <h3>{t('common.labels.security', 'Security')}</h3>
                        <span className="alerts-section__count">{openSec.length} open</span>
                    </header>
                    <ul className="notifications-list">
                        {openSec.map(a => (
                            <SecurityAlertItem
                                key={a.id}
                                alert={a}
                                onAcknowledge={onAcknowledge}
                                onResolve={onResolve}
                            />
                        ))}
                    </ul>
                </section>
            )}

            {ackSec.length > 0 && (
                <section className="alerts-section alerts-section--muted">
                    <header className="alerts-section__header">
                        <h3>{t('app.alertsTab.acknowledged', 'Acknowledged')}</h3>
                        <span className="alerts-section__count">{ackSec.length}</span>
                    </header>
                    <ul className="notifications-list">
                        {ackSec.map(a => (
                            <SecurityAlertItem
                                key={a.id}
                                alert={a}
                                onAcknowledge={onAcknowledge}
                                onResolve={onResolve}
                            />
                        ))}
                    </ul>
                </section>
            )}
        </div>
    );
};

export default AlertsTab;
