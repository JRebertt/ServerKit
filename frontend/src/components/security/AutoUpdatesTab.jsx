import { useState, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import EmptyState from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { Pill } from '@/components/ds';

const AutoUpdatesTab = () => {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const toast = useToast();

    useEffect(() => {
        loadStatus();
    }, []);

    const loadStatus = async () => {
        setLoading(true);
        try {
            const data = await api.getAutoUpdatesStatus();
            setStatus(data);
        } catch (error) {
            console.error('Failed to load auto-updates status:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleInstall = async () => {
        setActionLoading(true);
        try {
            await api.installAutoUpdates();
            toast.success('Auto-updates package installed');
            await loadStatus();
        } catch (error) {
            toast.error(`Failed to install: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleEnable = async () => {
        setActionLoading(true);
        try {
            await api.enableAutoUpdates();
            toast.success('Automatic updates enabled');
            await loadStatus();
        } catch (error) {
            toast.error(`Failed to enable: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleDisable = async () => {
        setActionLoading(true);
        try {
            await api.disableAutoUpdates();
            toast.success('Automatic updates disabled');
            await loadStatus();
        } catch (error) {
            toast.error(`Failed to disable: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    if (loading) {
        return <div className="loading-sm">Loading auto-updates status...</div>;
    }

    if (!status?.supported) {
        return (
            <div className="auto-updates-tab">
                <EmptyState
                    icon={AlertTriangle}
                    title="Not Supported"
                    description="Automatic security updates are not supported on this system."
                />
            </div>
        );
    }

    return (
        <div className="auto-updates-tab">
            <div className="card">
                <div className="card-header">
                    <h3>Automatic Security Updates</h3>
                    <Button variant="outline" size="sm" onClick={loadStatus}>Refresh</Button>
                </div>
                <div className="card-body">
                    <div className="sec-rows">
                        <div className="sk-info-row">
                            <span className="k">Package</span>
                            <span className="v">{status.package}</span>
                        </div>
                        <div className="sk-info-row">
                            <span className="k">Installed</span>
                            <Pill kind={status.installed ? 'green' : 'amber'}>
                                {status.installed ? 'Yes' : 'No'}
                            </Pill>
                        </div>
                        <div className="sk-info-row">
                            <span className="k">Status</span>
                            <Pill kind={status.enabled ? 'green' : 'gray'}>
                                {status.enabled ? 'Enabled' : 'Disabled'}
                            </Pill>
                        </div>
                    </div>

                    <div className="auto-updates-actions">
                        {!status.installed ? (
                            <Button variant="default" onClick={handleInstall} disabled={actionLoading}>
                                {actionLoading ? 'Installing...' : 'Install Auto-Updates'}
                            </Button>
                        ) : status.enabled ? (
                            <Button variant="secondary" onClick={handleDisable} disabled={actionLoading}>
                                {actionLoading ? 'Disabling...' : 'Disable Auto-Updates'}
                            </Button>
                        ) : (
                            <Button variant="default" onClick={handleEnable} disabled={actionLoading}>
                                {actionLoading ? 'Enabling...' : 'Enable Auto-Updates'}
                            </Button>
                        )}
                    </div>

                    <div className="sec-note">
                        <p>
                            <strong>What are automatic security updates?</strong><br/>
                            When enabled, your server will automatically download and install security updates,
                            helping protect against known vulnerabilities without manual intervention.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default AutoUpdatesTab;
