import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import useTabParam from '../hooks/useTabParam';
import api from '../services/api';
import {
    OverviewTab,
    FirewallTab,
    SSHKeysTab,
    IPListsTab,
    IntegrityTab,
    AuditTab,
    EventsTab,
    SecurityConfigTab,
} from '../components/security';
import EmptyState from '../components/EmptyState';
import { useTranslation } from 'react-i18next';

// Core tabs only. The install-gated tools (fail2ban, malware scanner,
// quarantine, vulnerability scan, auto-updates) are security extensions now:
// they contribute their own tabs + group routes, which mount beside these and
// win over the /security/:tab fallback when installed.
const VALID_TABS = ['overview', 'firewall', 'ssh-keys', 'ip-lists', 'integrity', 'audit', 'events', 'settings'];

const Security = () => {
    const { t } = useTranslation();
    const { isAdmin } = useAuth();
    const [activeTab, setActiveTab] = useTabParam('/security', VALID_TABS);
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadStatus();
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

    // Re-pull the status feed — passed to the Overview so a one-click fix
    // (enable integrity, …) reflects in the posture immediately.
    async function reload() {
        await loadStatus();
    }

    if (loading) {
        return (
            <div className="sk-tabgroup__inner security-page">
                <EmptyState loading loadingVariant="detail" title={t('app.security.loadingSecurityStatus', 'Loading security status…')} />
            </div>
        );
    }

    return (
        <div className="sk-tabgroup__inner security-page">
            <div className="tab-content">
                {activeTab === 'overview' && <OverviewTab status={status} onRefresh={reload} onNavigateTab={setActiveTab} />}
                {activeTab === 'firewall' && <FirewallTab />}
                {activeTab === 'ssh-keys' && <SSHKeysTab />}
                {activeTab === 'ip-lists' && <IPListsTab />}
                {activeTab === 'integrity' && <IntegrityTab />}
                {activeTab === 'audit' && <AuditTab />}
                {activeTab === 'events' && <EventsTab />}
                {activeTab === 'settings' && <SecurityConfigTab />}
            </div>
        </div>
    );
};

export default Security;
