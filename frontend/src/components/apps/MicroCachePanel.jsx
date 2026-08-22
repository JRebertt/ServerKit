import { useState } from 'react';
import { Zap, Eraser } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useConfirm } from '@/hooks/useConfirm';
import { useTranslation } from 'react-i18next';

// Micro-cache panel (task #21) — opt-in nginx page cache per site. The
// backend rewrites the site's vhost with short-TTL cache directives plus
// hard bypasses for anything personalized (logged-in cookies, carts,
// admin/login paths, non-GET requests, query strings).
const MicroCachePanel = ({ app, onChanged }) => {
    const { t } = useTranslation();
    const toast = useToast();
    const { confirm } = useConfirm();
    const [enabled, setEnabled] = useState(!!app.micro_cache_enabled);
    const [saving, setSaving] = useState(false);
    const [purging, setPurging] = useState(false);

    async function handleToggle(next) {
        setSaving(true);
        setEnabled(next); // optimistic; reverted on failure
        try {
            const data = await api.setMicroCache(app.id, next);
            if (data.warning) toast.warning(data.warning);
            if (data.note) {
                toast.info(data.note);
            } else {
                toast.success(next
                    ? t('app.microCachePanel.microCacheEnabledTheSiteConfig', 'Micro-cache enabled — the site config was updated.')
                    : t('app.microCachePanel.microCacheDisabledTheSiteConfig', 'Micro-cache disabled — the site config was updated.'));
            }
            onChanged?.();
        } catch (err) {
            setEnabled(!next);
            toast.error(err.message || t('app.microCachePanel.failedToUpdateMicroCache', 'Failed to update micro-cache'));
        } finally {
            setSaving(false);
        }
    }

    async function handlePurge() {
        if (!await confirm({
            title: t('app.microCachePanel.clearMicroCache', 'Clear micro-cache'),
            message: t('app.microCachePanel.clearCachedPagesForEverySite', 'Clear cached pages for every site using the shared cache? Entries normally expire within 10 seconds.'),
            confirmText: t('app.microCachePanel.clearCache', 'Clear cache'),
        })) return;
        setPurging(true);
        try {
            const data = await api.purgeMicroCache(app.id);
            toast.success(data.message || t('app.microCachePanel.microCacheCleared', 'Micro-cache cleared'));
        } catch (err) {
            toast.error(err.message || t('app.microCachePanel.failedToClearTheMicroCache', 'Failed to clear the micro-cache'));
        } finally {
            setPurging(false);
        }
    }

    return (
        <div className="app-panel">
            <div className="app-panel-header">
                <Zap />
                <span>{t('app.microCachePanel.microCache', 'Micro-cache')}</span>
            </div>
            <div className="app-panel-body">
                <p className="app-panel-hint">
                    {t('app.microCachePanel.cachesFullPagesInNginxFor', 'Caches full pages in nginx for 10 seconds, so traffic spikes hit the cache instead of your app — a big, cheap win for WordPress and PHP sites. It is safe to enable: requests from logged-in users, carts and checkouts, admin and login pages, non-GET requests, and URLs with query strings always bypass the cache and reach the app directly.')}
                </p>

                <div className="settings-row">
                    <div className="settings-label">
                        <span>{t('app.microCachePanel.enableMicroCache', 'Enable micro-cache')}</span>
                        <span className="settings-hint">
                            {t('app.microCachePanel.rewritesThisSiteSNginxConfig', 'Rewrites this site\'s nginx config with the cache rules. Turning it off removes them again.')}
                        </span>
                    </div>
                    <div className="settings-control">
                        <Switch
                            checked={enabled}
                            onCheckedChange={handleToggle}
                            disabled={saving}
                            aria-label={t('app.microCachePanel.enableMicroCache', 'Enable micro-cache')}
                        />
                        {saving && <span className="settings-saving">{t('common.editing.saving', 'Saving…')}</span>}
                    </div>
                </div>

                {enabled && (
                    <div className="settings-row">
                        <div className="settings-label">
                            <span>{t('app.microCachePanel.clearCache', 'Clear cache')}</span>
                            <span className="settings-hint">
                                {t('app.microCachePanel.entriesExpireOnTheirOwnWithin', 'Entries expire on their own within 10 seconds; use this when a change must be visible immediately. The cache is shared, so this clears it for every site that uses it.')}
                            </span>
                        </div>
                        <div className="settings-control">
                            <Button variant="outline" size="sm" onClick={handlePurge} disabled={purging}>
                                <Eraser size={14} />
                                {purging ? 'Clearing…' : 'Clear cache'}
                            </Button>
                        </div>
                    </div>
                )}

                <p className="app-panel-hint">
                    {t('app.microCachePanel.toVerifyItWorksCheckThe', 'To verify it works, check the')} <code>{t('app.microCachePanel.xSkCache', 'X-SK-Cache')}</code> {t('app.microCachePanel.responseHeaderOnTheSite', 'response header on the site:')} <code>HIT</code> {t('app.microCachePanel.meansThePageCameFromThe', 'means the page came from the cache,')}
                    <code> MISS</code>/<code>EXPIRED</code> {t('app.microCachePanel.thatItWasFetchedFreshAnd', 'that it was fetched fresh, and')}
                    <code> BYPASS</code> {t('app.microCachePanel.thatABypassRuleApplied', 'that a bypass rule applied.')}
                </p>
            </div>
        </div>
    );
};

export default MicroCachePanel;
