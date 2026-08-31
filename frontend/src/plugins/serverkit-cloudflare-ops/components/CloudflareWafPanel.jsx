import { useState, useEffect, useCallback } from 'react';
import { ShieldAlert } from 'lucide-react';
import api from '../services/cloudflare';
import {
    Button, Input, Textarea, Switch, Badge,
    Select, SelectTrigger, SelectContent, SelectItem, SelectValue,
    EmptyState, useToast,
} from 'serverkit-sdk';
import { useTranslation } from 'react-i18next';

const ACTION_OPTIONS = [
    { value: 'block', labelKey: 'app.cloudflareWafPanel.block', label: 'Block' },
    { value: 'managed_challenge', labelKey: 'app.cloudflareWafPanel.managedChallenge', label: 'Managed Challenge' },
    { value: 'js_challenge', labelKey: 'app.cloudflareWafPanel.jsChallenge', label: 'JS Challenge' },
    { value: 'log', labelKey: 'app.cloudflareWafPanel.log', label: 'Log' },
];

const EXPRESSION_PLACEHOLDER = '(http.request.uri.path contains "/admin")';

export default function CloudflareWafPanel({ zoneId, isAdmin }) {
    const { t } = useTranslation();
    const toast = useToast();

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [rulesetId, setRulesetId] = useState(null);
    const [rules, setRules] = useState([]);
    const [presets, setPresets] = useState([]);

    // Preset form state
    const [selectedPreset, setSelectedPreset] = useState('');
    const [presetParams, setPresetParams] = useState({});

    // Custom rule form state
    const [customDescription, setCustomDescription] = useState('');
    const [customExpression, setCustomExpression] = useState('');
    const [customAction, setCustomAction] = useState('block');

    // Tracks any in-flight write so buttons can disable
    const [applying, setApplying] = useState(false);

    const loadRules = useCallback(async () => {
        try {
            const data = await api.getCloudflareWafRules(zoneId);
            setRulesetId(data.ruleset_id ?? null);
            setRules(data.rules || []);
            setPresets(data.presets || []);
            setError(null);
        } catch (err) {
            setError(err.message);
        }
    }, [zoneId]);

    useEffect(() => {
        let active = true;
        setLoading(true);
        (async () => {
            try {
                const data = await api.getCloudflareWafRules(zoneId);
                if (!active) return;
                setRulesetId(data.ruleset_id ?? null);
                setRules(data.rules || []);
                setPresets(data.presets || []);
                setError(null);
            } catch (err) {
                if (active) setError(err.message);
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => {
            active = false;
        };
    }, [zoneId]);

    const activePreset = presets.find((p) => p.key === selectedPreset) || null;
    const presetParamDefs = activePreset?.params || [];

    const handleSelectPreset = (key) => {
        setSelectedPreset(key);
        setPresetParams({});
    };

    const handleParamChange = (key, value) => {
        setPresetParams((prev) => ({ ...prev, [key]: value }));
    };

    const handleApplyPreset = async () => {
        if (!activePreset) return;
        setApplying(true);
        try {
            await api.applyCloudflareWafPreset(zoneId, activePreset.key, presetParams);
            await loadRules();
            setPresetParams({});
            toast.success(t('app.cloudflareWafPanel.addedQuickRule', 'Added quick rule: {{label}}', { label: activePreset.label }));
        } catch (err) {
            toast.error(err.message);
        } finally {
            setApplying(false);
        }
    };

    const handleAddCustomRule = async () => {
        setApplying(true);
        try {
            await api.addCloudflareWafRule(zoneId, {
                description: customDescription,
                expression: customExpression,
                action: customAction,
                enabled: true,
            });
            await loadRules();
            setCustomDescription('');
            setCustomExpression('');
            setCustomAction('block');
            toast.success(t('app.cloudflareWafPanel.customRuleAdded', 'Custom rule added'));
        } catch (err) {
            toast.error(err.message);
        } finally {
            setApplying(false);
        }
    };

    const handleToggleRule = async (rule) => {
        setApplying(true);
        try {
            await api.updateCloudflareWafRule(zoneId, rulesetId, rule.id, {
                enabled: !rule.enabled,
            });
            await loadRules();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setApplying(false);
        }
    };

    const handleDeleteRule = async (rule) => {
        setApplying(true);
        try {
            await api.deleteCloudflareWafRule(zoneId, rulesetId, rule.id);
            await loadRules();
            toast.success(t('app.cloudflareWafPanel.ruleDeleted', 'Rule deleted'));
        } catch (err) {
            toast.error(err.message);
        } finally {
            setApplying(false);
        }
    };

    if (loading) {
        return <div className="cf-waf__loading">{t('app.cloudflareWafPanel.loadingFirewallRules', 'Loading firewall rules…')}</div>;
    }

    if (error) {
        return (
            <EmptyState
                icon={ShieldAlert}
                title={t('app.cloudflareWafPanel.firewallRulesUnavailable', 'Firewall rules unavailable')}
                description={error}
            />
        );
    }

    const writeDisabled = !isAdmin || applying;

    return (
        <div className="cf-waf">
            {/* Presets / quick rules */}
            <section className="cf-waf__section">
                <h3 className="cf-waf__heading">{t('app.cloudflareWafPanel.quickRules', 'Quick rules')}</h3>
                <p className="cf-waf__hint">
                    {t('app.cloudflareWafPanel.applyACuratedCloudflareRuleWithout', 'Apply a curated Cloudflare rule without writing an expression by hand.')}
                </p>

                <div className="cf-waf__field">
                    <Select
                        value={selectedPreset}
                        onValueChange={handleSelectPreset}
                        disabled={writeDisabled}
                    >
                        <SelectTrigger className="cf-waf__select">
                            <SelectValue placeholder={t('app.cloudflareWafPanel.chooseAQuickRule', 'Choose a quick rule…')} />
                        </SelectTrigger>
                        <SelectContent>
                            {presets.map((preset) => (
                                <SelectItem key={preset.key} value={preset.key}>
                                    {preset.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                {activePreset && (
                    <p className="cf-waf__preset-desc">{activePreset.description}</p>
                )}

                {presetParamDefs.length > 0 && (
                    <div className="cf-waf__params">
                        {presetParamDefs.map((param) => (
                            <div className="cf-waf__field" key={param.key}>
                                <label className="cf-waf__label">{param.label}</label>
                                <Input
                                    value={presetParams[param.key] || ''}
                                    placeholder={param.placeholder}
                                    onChange={(e) => handleParamChange(param.key, e.target.value)}
                                    disabled={writeDisabled}
                                />
                            </div>
                        ))}
                    </div>
                )}

                <div className="cf-waf__actions">
                    <Button
                        size="sm"
                        onClick={handleApplyPreset}
                        disabled={writeDisabled || !activePreset}
                    >
                        {t('app.cloudflareWafPanel.addRule', 'Add rule')}
                    </Button>
                </div>
            </section>

            {/* Custom rule */}
            <section className="cf-waf__section">
                <h3 className="cf-waf__heading">{t('app.cloudflareWafPanel.customRule', 'Custom rule')}</h3>
                <p className="cf-waf__hint">
                    {t('app.cloudflareWafPanel.writeYourOwnCloudflareFirewallExpression', 'Write your own Cloudflare firewall expression for full control.')}
                </p>

                <div className="cf-waf__field">
                    <label className="cf-waf__label">{t('common.labels.description', 'Description')}</label>
                    <Input
                        value={customDescription}
                        placeholder={t('app.cloudflareWafPanel.blockAdminFromOutsideTheOffice', 'Block admin from outside the office')}
                        onChange={(e) => setCustomDescription(e.target.value)}
                        disabled={writeDisabled}
                    />
                </div>

                <div className="cf-waf__field">
                    <label className="cf-waf__label">{t('app.cloudflareWafPanel.expression', 'Expression')}</label>
                    <Textarea
                        rows={3}
                        value={customExpression}
                        placeholder={EXPRESSION_PLACEHOLDER}
                        onChange={(e) => setCustomExpression(e.target.value)}
                        disabled={writeDisabled}
                    />
                </div>

                <div className="cf-waf__field">
                    <label className="cf-waf__label">{t('common.labels.action', 'Action')}</label>
                    <Select
                        value={customAction}
                        onValueChange={setCustomAction}
                        disabled={writeDisabled}
                    >
                        <SelectTrigger className="cf-waf__select">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {ACTION_OPTIONS.map((opt) => (
                                <SelectItem key={opt.value} value={opt.value}>
                                    {opt.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                <div className="cf-waf__actions">
                    <Button
                        size="sm"
                        onClick={handleAddCustomRule}
                        disabled={writeDisabled || !customExpression.trim()}
                    >
                        {t('app.cloudflareWafPanel.addCustomRule', 'Add custom rule')}
                    </Button>
                </div>
            </section>

            {/* Active rules list */}
            <section className="cf-waf__section">
                <h3 className="cf-waf__heading">{t('app.cloudflareWafPanel.activeRules', 'Active rules (')}{rules.length})</h3>

                {rules.length === 0 ? (
                    <EmptyState
                        icon={ShieldAlert}
                        title={t('app.cloudflareWafPanel.noCustomFirewallRules', 'No custom firewall rules')}
                        description={t('app.cloudflareWafPanel.addAQuickRuleOrA', 'Add a quick rule or a custom rule above.')}
                    />
                ) : (
                    <ul className="cf-waf__list">
                        {rules.map((rule) => (
                            <li className="cf-waf__rule" key={rule.id}>
                                <div className="cf-waf__rule-main">
                                    <div className="cf-waf__rule-head">
                                        <Badge
                                            variant={rule.action === 'block' ? 'destructive' : 'secondary'}
                                        >
                                            {rule.action}
                                        </Badge>
                                        <span className="cf-waf__rule-desc">
                                            {rule.description || 'Untitled rule'}
                                        </span>
                                    </div>
                                    <code className="cf-waf__rule-expr">{rule.expression}</code>
                                </div>

                                <div className="cf-waf__rule-actions">
                                    <Switch
                                        checked={rule.enabled}
                                        onCheckedChange={() => handleToggleRule(rule)}
                                        disabled={writeDisabled}
                                    />
                                    <Button
                                        variant="destructive"
                                        size="sm"
                                        onClick={() => handleDeleteRule(rule)}
                                        disabled={writeDisabled}
                                    >
                                        {t('common.actions.delete', 'Delete')}
                                    </Button>
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
        </div>
    );
}
