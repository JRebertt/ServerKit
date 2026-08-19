import { useState } from 'react';
import { Zap, Eraser } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useConfirm } from '@/hooks/useConfirm';

// Micro-cache panel (task #21) — opt-in nginx page cache per site. The
// backend rewrites the site's vhost with short-TTL cache directives plus
// hard bypasses for anything personalized (logged-in cookies, carts,
// admin/login paths, non-GET requests, query strings).
const MicroCachePanel = ({ app, onChanged }) => {
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
                    ? 'Micro-cache enabled — the site config was updated.'
                    : 'Micro-cache disabled — the site config was updated.');
            }
            onChanged?.();
        } catch (err) {
            setEnabled(!next);
            toast.error(err.message || 'Failed to update micro-cache');
        } finally {
            setSaving(false);
        }
    }

    async function handlePurge() {
        if (!await confirm({
            title: 'Clear micro-cache',
            message: 'Clear cached pages for every site using the shared cache? Entries normally expire within 10 seconds.',
            confirmText: 'Clear cache',
        })) return;
        setPurging(true);
        try {
            const data = await api.purgeMicroCache(app.id);
            toast.success(data.message || 'Micro-cache cleared');
        } catch (err) {
            toast.error(err.message || 'Failed to clear the micro-cache');
        } finally {
            setPurging(false);
        }
    }

    return (
        <div className="app-panel">
            <div className="app-panel-header">
                <Zap />
                <span>Micro-cache</span>
            </div>
            <div className="app-panel-body">
                <p className="app-panel-hint">
                    Caches full pages in nginx for 10 seconds, so traffic spikes hit the
                    cache instead of your app — a big, cheap win for WordPress and PHP
                    sites. It is safe to enable: requests from logged-in users, carts and
                    checkouts, admin and login pages, non-GET requests, and URLs with
                    query strings always bypass the cache and reach the app directly.
                </p>

                <div className="settings-row">
                    <div className="settings-label">
                        <span>Enable micro-cache</span>
                        <span className="settings-hint">
                            Rewrites this site&apos;s nginx config with the cache rules.
                            Turning it off removes them again.
                        </span>
                    </div>
                    <div className="settings-control">
                        <Switch
                            checked={enabled}
                            onCheckedChange={handleToggle}
                            disabled={saving}
                            aria-label="Enable micro-cache"
                        />
                        {saving && <span className="settings-saving">Saving...</span>}
                    </div>
                </div>

                {enabled && (
                    <div className="settings-row">
                        <div className="settings-label">
                            <span>Clear cache</span>
                            <span className="settings-hint">
                                Entries expire on their own within 10 seconds; use this when
                                a change must be visible immediately. The cache is shared, so
                                this clears it for every site that uses it.
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
                    To verify it works, check the <code>X-SK-Cache</code> response header
                    on the site: <code>HIT</code> means the page came from the cache,
                    <code> MISS</code>/<code>EXPIRED</code> that it was fetched fresh, and
                    <code> BYPASS</code> that a bypass rule applied.
                </p>
            </div>
        </div>
    );
};

export default MicroCachePanel;
