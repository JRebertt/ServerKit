import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import useTabParam from '../hooks/useTabParam';
import api from '../services/api';
import {
    OverviewTab,
    FirewallTab,
    Fail2banTab,
    SSHKeysTab,
    IPListsTab,
    ScannerTab,
    QuarantineTab,
    IntegrityTab,
    AuditTab,
    VulnerabilityTab,
    AutoUpdatesTab,
    EventsTab,
    SecurityConfigTab,
} from '../components/security';
import EmptyState from '../components/EmptyState';
import { useTranslation } from 'react-i18next';

const VALID_TABS = ['overview', 'firewall', 'fail2ban', 'ssh-keys', 'ip-lists', 'scanner', 'quarantine', 'integrity', 'audit', 'vulnerability', 'updates', 'events', 'settings'];

const Security = () => {
    const { t } = useTranslation();
    const { isAdmin } = useAuth();
    const [activeTab, setActiveTab] = useTabParam('/security', VALID_TABS);
    const [status, setStatus] = useState(null);
    const [clamav, setClamav] = useState(null);
    const [clamavLoading, setClamavLoading] = useState(true);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadStatus();
        loadClamav();
    }, []);

    async function loadStatus() {
        try {
            const data = await api.getSecurityStatus();
            setStatus(data);
        } catch (err) {
            console.error('Failed to load security status:', err);
        } finally {
            setLoading(false);
        }
    }

    async function loadClamav() {
        try {
            const data = await api.getClamAVStatus();
            setClamav(data);
        } catch (err) {
            console.error('Failed to load ClamAV status:', err);
        } finally {
            setClamavLoading(false);
        }
    }

    // Re-pull both status feeds — passed to the Overview so a one-click fix
    // (install ClamAV, enable integrity, …) reflects in the posture immediately.
    async function reload() {
        await Promise.all([loadStatus(), loadClamav()]);
    }

    if (loading) {
        return (
            <div className="sk-tabgroup__inner security-page">
                <EmptyState loading loadingVariant="detail" title={t('app.security.loadingSecurityStatus', 'Loading security status...')} />
            </div>
        );
    }

    return (
        <div className="sk-tabgroup__inner security-page">
            <div className="tab-content">
                {activeTab === 'overview' && <OverviewTab status={status} clamavStatus={clamav} clamavLoading={clamavLoading} onRefresh={reload} onNavigateTab={setActiveTab} />}
                {activeTab === 'firewall' && <FirewallTab />}
                {activeTab === 'fail2ban' && <Fail2banTab />}
                {activeTab === 'ssh-keys' && <SSHKeysTab />}
                {activeTab === 'ip-lists' && <IPListsTab />}
                {activeTab === 'scanner' && <ScannerTab />}
                {activeTab === 'quarantine' && <QuarantineTab />}
                {activeTab === 'integrity' && <IntegrityTab />}
                {activeTab === 'audit' && <AuditTab />}
                {activeTab === 'vulnerability' && <VulnerabilityTab />}
                {activeTab === 'updates' && <AutoUpdatesTab />}
                {activeTab === 'events' && <EventsTab />}
                {activeTab === 'settings' && <SecurityConfigTab />}
            </div>
        </div>
    );
};

export default Security;
