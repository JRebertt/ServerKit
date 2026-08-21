import { useState, useEffect, useCallback } from 'react';
import { Network } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import EmptyState from '../EmptyState';
import { useToast } from '../../contexts/ToastContext';
import api from '../../services/api';
import { copyToClipboard } from '@/utils/clipboard';
import { useTranslation } from 'react-i18next';

function InstallBox({ command }) {
    const { t } = useTranslation();
    const toast = useToast();

    if (!command) {
        return <p className="cf-tunnels__hint">{t('app.tunnelsPanel.noInstallCommandAvailable', 'No install command available.')}</p>;
    }

    const handleCopy = async () => {
        if (await copyToClipboard(command)) toast.success(t('app.tunnelsPanel.copied', 'Copied'));
        else toast.error(t('app.tunnelsPanel.couldNotCopyTheInstallCommand', 'Could not copy the install command'));
    };

    return (
        <div className="cf-tunnels__install">
            <code className="cf-tunnels__cmd">{command}</code>
            <Button size="sm" variant="outline" onClick={handleCopy}>
                {t('app.tunnelsPanel.copy', 'Copy')}
            </Button>
        </div>
    );
}

function TunnelRow({ zoneId, tunnel, isAdmin, onChanged }) {
    const { t } = useTranslation();
    const toast = useToast();

    const [install, setInstall] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [hostnames, setHostnames] = useState([]);
    const [hostname, setHostname] = useState('');
    const [service, setService] = useState('');
    const [working, setWorking] = useState(false);

    const loadHostnames = useCallback(async () => {
        try {
            const res = await api.getCloudflareTunnelHostnames(zoneId, tunnel.id);
            setHostnames(res.hostnames || []);
        } catch (err) {
            toast.error(err.message);
        }
    }, [zoneId, tunnel.id, toast]);

    const handleToggleInstall = async () => {
        if (install) {
            setInstall(null);
            return;
        }
        setWorking(true);
        try {
            const res = await api.getCloudflareTunnelInstall(zoneId, tunnel.id);
            setInstall(res.install || null);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    const handleToggleHostnames = async () => {
        const next = !expanded;
        setExpanded(next);
        if (next && hostnames.length === 0) {
            await loadHostnames();
        }
    };

    const handleDelete = async () => {
        setWorking(true);
        try {
            await api.deleteCloudflareTunnel(zoneId, tunnel.id);
            toast.success(t('app.tunnelsPanel.deletedCloudflareTunnel', 'Deleted Cloudflare Tunnel "{{name}}"', { name: tunnel.name }));
            onChanged();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    const handleRemoveHostname = async (h) => {
        setWorking(true);
        try {
            await api.removeCloudflareTunnelHostname(zoneId, tunnel.id, h.hostname);
            toast.success(t('app.tunnelsPanel.hostnameRemoved', 'Hostname removed'));
            await loadHostnames();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    const handleAddHostname = async () => {
        setWorking(true);
        try {
            const res = await api.addCloudflareTunnelHostname(
                zoneId,
                tunnel.id,
                hostname,
                service,
            );
            toast.success(t('app.tunnelsPanel.hostnameRouted', 'Hostname routed'));
            if (res.dns && !res.dns.created) {
                toast.error(t('app.tunnelsPanel.routeSetButTheDnsRecord', 'Route set, but the DNS record failed: ') + res.dns.error);
            }
            setHostname('');
            setService('');
            await loadHostnames();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    const writeDisabled = !isAdmin || working;

    return (
        <li className="cf-tunnels__item">
            <div className="cf-tunnels__item-head">
                <span className="cf-tunnels__name">{tunnel.name}</span>
                <code className="cf-tunnels__meta">{tunnel.id.slice(0, 12)}…</code>
                {tunnel.status && (
                    <span className="cf-tunnels__meta">{tunnel.status}</span>
                )}
                {tunnel.connections != null && (
                    <span className="cf-tunnels__meta">{tunnel.connections}</span>
                )}
                {tunnel.managed && <Badge variant="secondary">{t('app.tunnelsPanel.serverkit', 'ServerKit')}</Badge>}
            </div>

            <div className="cf-tunnels__item-actions">
                <Button
                    size="sm"
                    variant="outline"
                    onClick={handleToggleInstall}
                    disabled={!isAdmin || working}
                >
                    {t('app.tunnelsPanel.installCommand', 'Install command')}
                </Button>
                <Button
                    size="sm"
                    variant="outline"
                    onClick={handleToggleHostnames}
                    disabled={working}
                >
                    {t('app.tunnelsPanel.hostnames', 'Hostnames')}
                </Button>
                <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleDelete}
                    disabled={writeDisabled}
                >
                    {t('app.tunnelsPanel.delete', 'Delete')}
                </Button>
            </div>

            {install && <InstallBox command={install} />}

            {expanded && (
                <div className="cf-tunnels__hostnames">
                    {hostnames.length === 0 ? (
                        <p className="cf-tunnels__hint">{t('app.tunnelsPanel.noPublicHostnamesRoutedYet', 'No public hostnames routed yet.')}</p>
                    ) : (
                        hostnames.map((h) => (
                            <div className="cf-tunnels__host" key={h.hostname}>
                                <span>
                                    <code>{h.hostname}</code> &rarr; <code>{h.service}</code>
                                </span>
                                <Button
                                    variant="destructive"
                                    size="sm"
                                    onClick={() => handleRemoveHostname(h)}
                                    disabled={writeDisabled}
                                >
                                    {t('app.tunnelsPanel.remove', 'Remove')}
                                </Button>
                            </div>
                        ))
                    )}

                    <div className="cf-tunnels__host-add">
                        <Input
                            value={hostname}
                            placeholder="app.example.com"
                            onChange={(e) => setHostname(e.target.value)}
                            disabled={writeDisabled}
                        />
                        <Input
                            value={service}
                            placeholder="http://localhost:8080"
                            onChange={(e) => setService(e.target.value)}
                            disabled={writeDisabled}
                        />
                        <Button
                            size="sm"
                            onClick={handleAddHostname}
                            disabled={writeDisabled || !hostname.trim() || !service.trim()}
                        >
                            {t('app.tunnelsPanel.add', 'Add')}
                        </Button>
                    </div>
                    <p className="cf-tunnels__hint">
                        {t('app.tunnelsPanel.theHostnameShouldBeInsideThis', 'The hostname should be inside this zone\'s domain; a proxied DNS record is created automatically.')}
                    </p>
                </div>
            )}
        </li>
    );
}

export default function TunnelsPanel({ zoneId, isAdmin }) {
    const { t } = useTranslation();
    const toast = useToast();

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [tunnels, setTunnels] = useState([]);

    // Create form state
    const [name, setName] = useState('');
    const [creating, setCreating] = useState(false);
    const [lastInstall, setLastInstall] = useState(null);

    const loadData = useCallback(async () => {
        try {
            const data = await api.getCloudflareTunnels(zoneId);
            setTunnels(data.tunnels || []);
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
                const data = await api.getCloudflareTunnels(zoneId);
                if (!active) return;
                setTunnels(data.tunnels || []);
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

    const handleCreate = async () => {
        setCreating(true);
        try {
            const res = await api.createCloudflareTunnel(zoneId, name);
            toast.success(t('app.tunnelsPanel.createdTunnel', 'Created tunnel "{{name}}"', { name: name }));
            setLastInstall({ name, install: res.install, token: res.token });
            setName('');
            await loadData();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setCreating(false);
        }
    };

    if (loading) {
        return <div className="cf-tunnels__loading">{t('app.tunnelsPanel.loadingCloudflareTunnels', 'Loading Cloudflare Tunnels…')}</div>;
    }

    if (error) {
        return (
            <EmptyState
                icon={Network}
                title={t('app.tunnelsPanel.cloudflareTunnelsUnavailable', 'Cloudflare Tunnels unavailable')}
                description={error}
            />
        );
    }

    const createDisabled = !isAdmin || creating || !name.trim();

    return (
        <div className="cf-tunnels">
            {/* Create a Cloudflare Tunnel */}
            <section className="cf-tunnels__section">
                <h3 className="cf-tunnels__heading">{t('app.tunnelsPanel.createACloudflareTunnel', 'Create a Cloudflare Tunnel')}</h3>
                <p className="cf-tunnels__hint">
                    {t('app.tunnelsPanel.aCloudflareTunnelExposesALocal', 'A Cloudflare Tunnel exposes a local or private service through Cloudflare\'s edge — no public IP or open ports required.')}
                </p>

                <div className="cf-tunnels__field">
                    <label className="cf-tunnels__label">{t('app.tunnelsPanel.name', 'Name')}</label>
                    <Input
                        value={name}
                        placeholder="home-jellyfin"
                        onChange={(e) => setName(e.target.value)}
                        disabled={!isAdmin || creating}
                    />
                </div>

                <div className="cf-tunnels__actions">
                    <Button onClick={handleCreate} disabled={createDisabled}>
                        {t('app.tunnelsPanel.create', 'Create')}
                    </Button>
                </div>

                {lastInstall && (
                    <div className="cf-tunnels__install">
                        <p className="cf-tunnels__hint">
                            {t('app.tunnelsPanel.runThisOnceOnTheMachine', 'Run this once on the machine hosting your local service. The connector token is shown only now.')}
                        </p>
                        <InstallBox command={lastInstall.install} />
                        <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setLastInstall(null)}
                        >
                            {t('app.tunnelsPanel.dismiss', 'Dismiss')}
                        </Button>
                    </div>
                )}
            </section>

            {/* Cloudflare Tunnels list */}
            <section className="cf-tunnels__section">
                <h3 className="cf-tunnels__heading">{t('app.tunnelsPanel.cloudflareTunnels', 'Cloudflare Tunnels (')}{tunnels.length})</h3>

                {tunnels.length === 0 ? (
                    <EmptyState
                        icon={Network}
                        title={t('app.tunnelsPanel.noCloudflareTunnels', 'No Cloudflare Tunnels')}
                        description={t('app.tunnelsPanel.createOneAboveToExposeA', 'Create one above to expose a local service without a public IP.')}
                    />
                ) : (
                    <ul className="cf-tunnels__list">
                        {tunnels.map((tunnel) => (
                            <TunnelRow
                                key={tunnel.id}
                                zoneId={zoneId}
                                tunnel={tunnel}
                                isAdmin={isAdmin}
                                onChanged={loadData}
                            />
                        ))}
                    </ul>
                )}
            </section>
        </div>
    );
}
