import { useState, useEffect } from 'react';
import api from '../../services/api';
import EmptyState from '../EmptyState';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const PackagesTab = ({ appId }) => {
    const toast = useToast();
    const [packages, setPackages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [installing, setInstalling] = useState(false);
    const [newPackage, setNewPackage] = useState('');

    useEffect(() => {
        loadPackages();
    }, [appId]);

    async function loadPackages() {
        try {
            const data = await api.getPythonPackages(appId);
            setPackages(data.packages || []);
        } catch (err) {
            console.error('Failed to load packages:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleInstall(e) {
        e.preventDefault();
        if (!newPackage.trim()) return;

        setInstalling(true);
        try {
            await api.installPythonPackages(appId, [newPackage.trim()]);
            setNewPackage('');
            loadPackages();
        } catch (err) {
            console.error('Failed to install package:', err);
        } finally {
            setInstalling(false);
        }
    }

    async function handleFreeze() {
        try {
            await api.freezePythonRequirements(appId);
            toast.success('requirements.txt updated');
        } catch (err) {
            toast.error('Failed to freeze requirements');
            console.error('Failed to freeze requirements:', err);
        }
    }

    if (loading) {
        return <EmptyState loading loadingVariant="table" title="Loading packages..." />;
    }

    return (
        <div>
            <div className="section-header">
                <h3>Installed Packages</h3>
                <Button variant="outline" size="sm" onClick={handleFreeze}>
                    Freeze to requirements.txt
                </Button>
            </div>

            <form className="install-form" onSubmit={handleInstall}>
                <Input
                    type="text"
                    value={newPackage}
                    onChange={(e) => setNewPackage(e.target.value)}
                    placeholder="Package name (e.g., requests, flask==2.0.0)"
                />
                <Button type="submit" disabled={installing}>
                    {installing ? 'Installing...' : 'Install'}
                </Button>
            </form>

            <div className="packages-list">
                {packages.map(pkg => (
                    <div key={pkg.name} className="package-item">
                        <span className="package-name">{pkg.name}</span>
                        <span className="package-version">{pkg.version}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default PackagesTab;
