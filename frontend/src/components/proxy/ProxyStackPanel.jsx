import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Pill, SegControl } from '../ds';
import EmptyState from '../EmptyState';
import { AlertTriangle, CheckCircle2, Network } from 'lucide-react';

// Human label for an ingress plane, used in the mismatch banner copy.
const PLANE_LABEL = {
    nginx: 'host Nginx',
    proxy_stack: 'the proxy stack',
};

// Managed reverse-proxy stack panel for a server.
//
// Host nginx is the default (and the better choice for PHP/WordPress). This
// panel lets an operator opt into a Dockerized proxy — Traefik or Caddy —
// deployed as a Compose stack, preview the generated compose, edit a custom
// config snippet, and (best-effort) regenerate / restart the stack.

const PROXY_OPTIONS = [
    { value: 'nginx', label: 'Nginx', sub: 'Host default' },
    { value: 'traefik', label: 'Traefik', sub: 'Docker stack' },
    { value: 'caddy', label: 'Caddy', sub: 'Docker stack' },
];

const STATUS_KIND = {
    running: 'green',
    stopped: 'gray',
    error: 'red',
    unknown: 'amber',
};

const ProxyStackPanel = ({ serverId }) => {
    const toast = useToast();
    const [stack, setStack] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Local working state — the selected type may differ from the saved one
    // until the user clicks "Switch".
    const [selectedType, setSelectedType] = useState('nginx');
    const [snippet, setSnippet] = useState('');
    const [preview, setPreview] = useState(null);
    const [busy, setBusy] = useState(false);

    // Ingress-plane audit: which apps expect a plane that disagrees with the
    // server's active proxy. Refreshed on mount and after any proxy mutation.
    const [audit, setAudit] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getServerProxy(serverId);
            setStack(data);
            setSelectedType(data.proxy_type || 'nginx');
            setSnippet(data.custom_snippet || '');
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load proxy configuration');
        } finally {
            setLoading(false);
        }
    }, [serverId]);

    useEffect(() => {
        load();
    }, [load]);

    // Best-effort ingress-plane audit. Never blocks the panel; on failure the
    // banner simply stays hidden.
    const loadAudit = useCallback(async () => {
        try {
            const data = await api.getServerIngressAudit(serverId);
            setAudit(data);
        } catch (err) {
            console.error('Failed to load ingress audit:', err);
            setAudit(null);
        }
    }, [serverId]);

    useEffect(() => {
        loadAudit();
    }, [loadAudit]);

    // Refresh the compose preview whenever the selected type changes.
    const loadPreview = useCallback(async (proxyType) => {
        try {
            const data = await api.getServerProxyComposePreview(serverId, { proxyType });
            setPreview(data);
        } catch (err) {
            console.error('Failed to load compose preview:', err);
            setPreview(null);
        }
    }, [serverId]);

    useEffect(() => {
        loadPreview(selectedType);
    }, [selectedType, loadPreview]);

    const isDirtyType = stack && selectedType !== stack.proxy_type;
    const isDirtySnippet = stack && snippet !== (stack.custom_snippet || '');

    async function handleSwitch() {
        setBusy(true);
        try {
            await api.switchServerProxy(serverId, selectedType);
            toast.success(`Switched to ${selectedType}`);
            await load();
            await loadAudit();
        } catch (err) {
            toast.error(err.message || 'Failed to switch proxy');
        } finally {
            setBusy(false);
        }
    }

    async function handleSaveSnippet() {
        setBusy(true);
        try {
            await api.configureServerProxy(serverId, { custom_snippet: snippet });
            toast.success('Custom snippet saved');
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to save snippet');
        } finally {
            setBusy(false);
        }
    }

    async function handleRegenerate() {
        setBusy(true);
        try {
            const res = await api.regenerateServerProxy(serverId);
            if (res.success) {
                toast.success(res.reloaded ? 'Config regenerated and reloaded' : 'Config regenerated');
            } else {
                toast.error(res.error || 'Regenerate failed');
            }
            await load();
            await loadAudit();
        } catch (err) {
            toast.error(err.message || 'Failed to regenerate config');
        } finally {
            setBusy(false);
        }
    }

    async function handleDeploy() {
        setBusy(true);
        try {
            const res = await api.configureServerProxy(serverId, {
                proxy_type: selectedType,
                deploy: true,
            });
            const deploy = res.deploy;
            if (deploy && deploy.success === false) {
                toast.error(deploy.error || 'Deploy failed (best-effort)');
            } else {
                toast.success('Stack deployed');
            }
            await load();
            await loadAudit();
        } catch (err) {
            toast.error(err.message || 'Failed to deploy stack');
        } finally {
            setBusy(false);
        }
    }

    if (loading) {
        return <EmptyState loading loadingVariant="form" title="Loading proxy configuration" />;
    }

    if (error) {
        return (
            <div className="proxy-panel">
                <div className="proxy-panel__error">{error}</div>
                <Button variant="outline" onClick={load}>Retry</Button>
            </div>
        );
    }

    const isNginx = selectedType === 'nginx';
    const savedIsNginx = stack?.proxy_type === 'nginx';

    return (
        <div className="proxy-panel">
            <header className="proxy-panel__header">
                <div className="proxy-panel__title">
                    <Network size={18} />
                    <h3>Reverse Proxy</h3>
                </div>
                <div className="proxy-panel__status">
                    <span className="proxy-panel__status-label">Status</span>
                    <Pill kind={STATUS_KIND[stack?.status] || 'gray'}>
                        {savedIsNginx ? 'host nginx' : (stack?.status || 'unknown')}
                    </Pill>
                </div>
            </header>

            <p className="proxy-panel__hint">
                Host Nginx is the default and is recommended for PHP/WordPress. You can
                opt into a Dockerized Traefik or Caddy proxy deployed as a Compose stack.
            </p>

            {audit && audit.mismatch_count > 0 && (
                <div className="proxy-panel__ingress-warning" role="alert">
                    <div className="proxy-panel__ingress-warning-head">
                        <AlertTriangle size={16} />
                        <strong>
                            {audit.mismatch_count} app{audit.mismatch_count === 1 ? '' : 's'} on the wrong ingress plane
                        </strong>
                    </div>
                    <p className="proxy-panel__ingress-warning-text">
                        This server&apos;s active proxy is <strong>{audit.proxy_type}</strong>, which
                        expects <strong>{PLANE_LABEL[audit.expected_plane] || audit.expected_plane}</strong>.
                        The apps below expect the other plane:
                    </p>
                    <ul className="proxy-panel__ingress-list">
                        {(audit.apps || []).filter(a => a.mismatch).map(a => (
                            <li key={a.id} className="proxy-panel__ingress-item">
                                <Link to={`/apps/${a.id}`} className="proxy-panel__ingress-link">
                                    {a.name}
                                </Link>
                                {a.reason && <span className="proxy-panel__ingress-reason">{a.reason}</span>}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {audit && audit.mismatch_count === 0 && audit.app_count > 0 && (
                <div className="proxy-panel__ingress-ok">
                    <CheckCircle2 size={14} />
                    All {audit.app_count} app{audit.app_count === 1 ? '' : 's'} aligned with this server&apos;s ingress plane.
                </div>
            )}

            <section className="proxy-panel__section">
                <label className="proxy-panel__label">Proxy type</label>
                <SegControl
                    options={PROXY_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    value={selectedType}
                    onChange={setSelectedType}
                />
                <div className="proxy-panel__actions">
                    <Button onClick={handleSwitch} disabled={!isDirtyType || busy}>
                        {isDirtyType ? `Switch to ${selectedType}` : 'No change'}
                    </Button>
                    {!isNginx && (
                        <Button variant="outline" onClick={handleDeploy} disabled={busy}>
                            Deploy / Restart
                        </Button>
                    )}
                    {!savedIsNginx && (
                        <Button variant="outline" onClick={handleRegenerate} disabled={busy}>
                            Regenerate config
                        </Button>
                    )}
                </div>
            </section>

            {!isNginx && (
                <section className="proxy-panel__section">
                    <label className="proxy-panel__label">Compose preview</label>
                    {preview?.compose ? (
                        <pre className="proxy-panel__code" aria-label="docker-compose preview">
                            {preview.compose}
                        </pre>
                    ) : (
                        <div className="proxy-panel__empty">No compose generated for this type.</div>
                    )}
                </section>
            )}

            {!isNginx && (
                <section className="proxy-panel__section">
                    <label className="proxy-panel__label">Custom config snippet</label>
                    <Textarea
                        rows={6}
                        value={snippet}
                        onChange={(e) => setSnippet(e.target.value)}
                        placeholder="Appended to the generated proxy config (Caddyfile / Traefik dynamic)."
                        className="font-mono"
                    />
                    <div className="proxy-panel__actions">
                        <Button
                            variant="outline"
                            onClick={handleSaveSnippet}
                            disabled={!isDirtySnippet || busy}
                        >
                            Save snippet
                        </Button>
                    </div>
                </section>
            )}

            {isNginx && (
                <EmptyState
                    icon={Network}
                    title="Host Nginx is active"
                    description="The host's Nginx is handling reverse proxying. Switch to Traefik or Caddy above to run a managed Docker proxy stack instead."
                />
            )}
        </div>
    );
};

export default ProxyStackPanel;
