import { useEffect, useState } from 'react';
import api from '../../services/api';
import useSettingFocus from '../../hooks/useSettingFocus';
import { useAuth } from '../../contexts/AuthContext';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { useTranslation } from 'react-i18next';

const AI_CONFIG_CHANGED_EVENT = 'serverkit:ai-config-changed';

const AISettingsTab = () => {
    const { t } = useTranslation();
    const register = useSettingFocus();
    const { isAdmin } = useAuth();
    const [settings, setSettings] = useState({
        enabled: false, provider: '', model: '', endpoint: '',
        pii_redaction: true, injection_detection: true, max_cost_usd: '0.5',
        api_key_set: false,
    });
    const [providers, setProviders] = useState([]);
    const [models, setModels] = useState([]);
    const [apiKey, setApiKey] = useState('');     // write-only; '' means "unchanged"
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [message, setMessage] = useState(null);

    useEffect(() => {
        if (!isAdmin) { setLoading(false); return; }
        Promise.all([api.aiGetSettings(), api.aiGetProviders()])
            .then(([s, p]) => {
                setSettings((prev) => ({ ...prev, ...s, max_cost_usd: String(s.max_cost_usd ?? '0.5') }));
                setProviders(p.providers || []);
                if (s.provider) loadModels(s.provider);
            })
            .catch((e) => setMessage({ type: 'error', text: e.message || 'Failed to load AI settings' }))
            .finally(() => setLoading(false));
    }, [isAdmin]);

    const loadModels = (provider) => {
        if (!provider) { setModels([]); return; }
        api.aiGetModels(provider).then((d) => setModels(d.models || [])).catch(() => setModels([]));
    };

    const onProviderChange = (provider) => {
        setSettings((s) => ({ ...s, provider, model: '' }));
        loadModels(provider);
    };

    const buildPayload = () => {
        const payload = {
            enabled: settings.enabled,
            provider: settings.provider,
            model: settings.model,
            endpoint: settings.endpoint,
            pii_redaction: settings.pii_redaction,
            injection_detection: settings.injection_detection,
            max_cost_usd: settings.max_cost_usd,
        };
        if (apiKey.trim()) payload.api_key = apiKey.trim();
        return payload;
    };

    const handleSave = async () => {
        setSaving(true);
        setMessage(null);
        try {
            await api.aiUpdateSettings(buildPayload());
            setApiKey('');
            const fresh = await api.aiGetSettings();
            setSettings((prev) => ({ ...prev, ...fresh, max_cost_usd: String(fresh.max_cost_usd ?? '0.5') }));
            window.dispatchEvent(new Event(AI_CONFIG_CHANGED_EVENT));
            setMessage({ type: 'success', text: 'AI settings saved' });
        } catch (e) {
            setMessage({ type: 'error', text: e.message || 'Failed to save AI settings' });
        } finally {
            setSaving(false);
        }
    };

    const handleTest = async () => {
        setTesting(true);
        setMessage(null);
        try {
            const body = { provider: settings.provider, model: settings.model, endpoint: settings.endpoint };
            if (apiKey.trim()) body.api_key = apiKey.trim();
            const res = await api.aiTestSettings(body);
            setMessage(res.ok
                ? { type: 'success', text: 'Connection OK' }
                : { type: 'error', text: `Connection failed: ${res.error || 'unknown error'}` });
        } catch (e) {
            setMessage({ type: 'error', text: e.message || 'Test failed' });
        } finally {
            setTesting(false);
        }
    };

    if (!isAdmin) {
        return <div className="settings-section"><p>{t('app.aISettingsTab.adminAccessRequired', 'Admin access required.')}</p></div>;
    }
    if (loading) {
        return <div className="settings-section"><p>{t('app.aISettingsTab.loading', 'Loading…')}</p></div>;
    }

    const activeProvider = providers.find((p) => p.id === settings.provider);
    const needsKey = activeProvider ? activeProvider.needs_key : true;

    return (
        <div className="settings-section">
            <h2>{t('app.aISettingsTab.aiAssistant', 'AI Assistant')}</h2>
            <p className="section-description">
                {t('app.aISettingsTab.configureTheInPanelAssistantPowered', 'Configure the in-panel assistant — powered by Prompture. The API key is stored encrypted and never returned by the API.')}
            </p>

            {message && <div className={`message ${message.type}`}>{message.text}</div>}

            <div {...register('ai-provider', 'settings-card')}>
                <div className="form-group">
                    <div className="settings-row">
                        <div className="settings-label"><Label>{t('app.aISettingsTab.enableAiAssistant', 'Enable AI assistant')}</Label></div>
                        <Switch
                            checked={settings.enabled}
                            onCheckedChange={(v) => setSettings((s) => ({ ...s, enabled: v }))}
                        />
                    </div>
                </div>

                <div className="form-group">
                    <label htmlFor="ai-provider">{t('app.aISettingsTab.provider', 'Provider')}</label>
                    <select
                        id="ai-provider"
                        value={settings.provider}
                        onChange={(e) => onProviderChange(e.target.value)}
                    >
                        <option value="">{t('app.aISettingsTab.selectAProvider', 'Select a provider…')}</option>
                        {providers.map((p) => (
                            <option key={p.id} value={p.id}>{p.label}</option>
                        ))}
                    </select>
                </div>

                <div className="form-group">
                    <label htmlFor="ai-model">{t('app.aISettingsTab.model', 'Model')}</label>
                    <input
                        id="ai-model"
                        type="text"
                        list="ai-model-options"
                        placeholder={t('app.aISettingsTab.eGGpt4o', 'e.g. gpt-4o')}
                        value={settings.model}
                        onChange={(e) => setSettings((s) => ({ ...s, model: e.target.value }))}
                    />
                    <datalist id="ai-model-options">
                        {models.map((m) => <option key={m} value={m} />)}
                    </datalist>
                </div>

                {needsKey && (
                    <div className="form-group">
                        <label htmlFor="ai-key">{t('app.aISettingsTab.apiKey', 'API key')}</label>
                        <input
                            id="ai-key"
                            type="password"
                            autoComplete="off"
                            placeholder={settings.api_key_set ? t('app.aISettingsTab.configuredLeaveBlankToKeep', 'Configured ✓ (leave blank to keep)') : t('app.aISettingsTab.pasteYourApiKey', 'Paste your API key')}
                            value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                        />
                    </div>
                )}

                {activeProvider && activeProvider.supports_endpoint && (
                    <div className="form-group">
                        <label htmlFor="ai-endpoint">{t('app.aISettingsTab.endpointOptional', 'Endpoint (optional)')}</label>
                        <input
                            id="ai-endpoint"
                            type="text"
                            placeholder="http://localhost:11434"
                            value={settings.endpoint}
                            onChange={(e) => setSettings((s) => ({ ...s, endpoint: e.target.value }))}
                        />
                    </div>
                )}

                <div className="form-group">
                    <label htmlFor="ai-max-cost">{t('app.aISettingsTab.perConversationCostCeilingUsd', 'Per-conversation cost ceiling (USD)')}</label>
                    <input
                        id="ai-max-cost"
                        type="number"
                        step="0.1"
                        min="0"
                        value={settings.max_cost_usd}
                        onChange={(e) => setSettings((s) => ({ ...s, max_cost_usd: e.target.value }))}
                    />
                </div>

                <div className="form-group">
                    <div className="settings-row">
                        <div className="settings-label"><Label>{t('app.aISettingsTab.redactPiiFromMessagesToolOutput', 'Redact PII from messages & tool output')}</Label></div>
                        <Switch
                            checked={settings.pii_redaction}
                            onCheckedChange={(v) => setSettings((s) => ({ ...s, pii_redaction: v }))}
                        />
                    </div>
                </div>
                <div className="form-group">
                    <div className="settings-row">
                        <div className="settings-label"><Label>{t('app.aISettingsTab.blockPromptInjectionAttempts', 'Block prompt-injection attempts')}</Label></div>
                        <Switch
                            checked={settings.injection_detection}
                            onCheckedChange={(v) => setSettings((s) => ({ ...s, injection_detection: v }))}
                        />
                    </div>
                </div>

                <div className="settings-actions" style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                    <Button variant="outline" onClick={handleTest} disabled={testing || !settings.provider || !settings.model}>
                        {testing ? 'Testing…' : 'Test connection'}
                    </Button>
                    <Button variant="primary" onClick={handleSave} disabled={saving}>
                        {saving ? 'Saving…' : 'Save'}
                    </Button>
                </div>
            </div>
        </div>
    );
};

export default AISettingsTab;
