import { useState, useEffect } from 'react';
import api from '../../services/api';
import EmptyState from '../EmptyState';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';

const GunicornTab = ({ appId }) => {
    const toast = useToast();
    const [config, setConfig] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        loadConfig();
    }, [appId]);

    async function loadConfig() {
        try {
            const data = await api.getGunicornConfig(appId);
            setConfig(data.content || '');
        } catch (err) {
            console.error('Failed to load config:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleSave() {
        setSaving(true);
        try {
            await api.updateGunicornConfig(appId, config);
            toast.success('Configuration saved. Restart the app to apply changes.');
        } catch (err) {
            toast.error('Failed to save configuration');
            console.error('Failed to save config:', err);
        } finally {
            setSaving(false);
        }
    }

    if (loading) {
        return <EmptyState loading loadingVariant="form" title="Loading Gunicorn configuration..." />;
    }

    return (
        <div>
            <div className="section-header">
                <h3>Gunicorn Configuration</h3>
                <Button onClick={handleSave} disabled={saving}>
                    {saving ? 'Saving...' : 'Save'}
                </Button>
            </div>
            <textarea
                className="code-editor"
                value={config}
                onChange={(e) => setConfig(e.target.value)}
                spellCheck={false}
            />
        </div>
    );
};

export default GunicornTab;
