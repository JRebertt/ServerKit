import { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Pill } from '../ds';
import EmptyState from '../EmptyState';
import { Cloud } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
    OfflineIcon,
    TrashIcon,
} from './serverDetailShared';

// CloudflaredTab — manage Cloudflare named tunnels via the agent.
//
// Auth model: the user runs `cloudflared tunnel login` once on the
// server. That writes ~/.cloudflared/cert.pem (or
// /etc/cloudflared/cert.pem when run as root). The panel never sees
// a Cloudflare API token — every action shells out to cloudflared
// using that cert. /status surfaces both "binary present" and
// "cert present" so we can show "log in first" before users hit
// CRUD actions and get confusing errors back.
const CloudflaredTab = ({ serverId, serverStatus }) => {
    const toast = useToast();
    const { confirm: confirmCf } = useConfirm();
    const [status, setStatus] = useState(null);
    const [tunnels, setTunnels] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [showCreateModal, setShowCreateModal] = useState(false);
    const [createName, setCreateName] = useState('');
    const [creating, setCreating] = useState(false);

    const [showRouteModal, setShowRouteModal] = useState(false);
    const [routeTunnel, setRouteTunnel] = useState(null);
    const [routeHostname, setRouteHostname] = useState('');
    const [routing, setRouting] = useState(false);

    // Login flow: { channel, authUrl, status: 'starting'|'awaiting'|'done'|'error', error, certPath }
    const [login, setLogin] = useState(null);

    const loadStatus = useCallback(async () => {
        try {
            const s = await api.getRemoteCloudflaredStatus(serverId);
            setStatus(s);
        } catch (err) {
            console.error('Failed to load cloudflared status:', err);
        }
    }, [serverId]);

    const loadTunnels = useCallback(async () => {
        try {
            const data = await api.getRemoteCloudflaredTunnels(serverId);
            setTunnels(data?.tunnels || []);
            setError(null);
        } catch (err) {
            // Auth errors here are common when the user hasn't logged
            // in yet — the status banner already explains; don't show
            // a redundant scary alert.
            setError(err.message || 'Failed to load tunnels');
        }
    }, [serverId]);

    useEffect(() => {
        if (serverStatus !== 'online') {
            setLoading(false);
            return;
        }
        let cancelled = false;
        (async () => {
            setLoading(true);
            await loadStatus();
            await loadTunnels();
            if (!cancelled) setLoading(false);
        })();
        return () => { cancelled = true; };
    }, [serverStatus, loadStatus, loadTunnels]);

    async function handleCreate(e) {
        e.preventDefault();
        const name = createName.trim();
        if (!name) {
            toast.error('Name is required');
            return;
        }
        setCreating(true);
        try {
            await api.createRemoteCloudflaredTunnel(serverId, name);
            toast.success(`Tunnel "${name}" created`);
            setShowCreateModal(false);
            setCreateName('');
            loadTunnels();
        } catch (err) {
            toast.error(err.message || 'Failed to create tunnel');
        } finally {
            setCreating(false);
        }
    }

    async function handleRoute(e) {
        e.preventDefault();
        const hostname = routeHostname.trim();
        if (!hostname || !routeTunnel) return;
        setRouting(true);
        try {
            await api.routeRemoteCloudflaredTunnel(serverId, routeTunnel.id || routeTunnel.name, hostname);
            toast.success(`${hostname} → ${routeTunnel.name}`);
            setShowRouteModal(false);
            setRouteHostname('');
            setRouteTunnel(null);
        } catch (err) {
            toast.error(err.message || 'Failed to add route');
        } finally {
            setRouting(false);
        }
    }

    async function handleDelete(tunnel) {
        const ok = await confirmCf({
            title: 'Delete Tunnel',
            message: `Delete tunnel "${tunnel.name}"? Active connections will be force-closed.`,
            variant: 'danger',
        });
        if (!ok) return;
        try {
            await api.deleteRemoteCloudflaredTunnel(serverId, tunnel.id || tunnel.name);
            toast.success('Tunnel deleted');
            loadTunnels();
        } catch (err) {
            toast.error(err.message || 'Failed to delete tunnel');
        }
    }

    // Triggers `cloudflared tunnel login` on the agent and subscribes
    // to the streaming auth flow. The first event carries the auth URL
    // we surface as a clickable button; the final event flips us back
    // to ready state once cert.pem appears.
    async function handleStartLogin() {
        try {
            const res = await api.startRemoteCloudflaredLogin(serverId);
            const channel = res?.channel || `job:${res?.job_id}`;
            setLogin({ channel, status: 'starting', authUrl: null, error: null, certPath: null });

            // Reuse the live socket service to subscribe to the
            // server_stream room. We don't open the JobProgressModal
            // because the login flow needs a different shape (a single
            // big "Open URL" CTA, not a log tail).
            const { default: socketService } = await import('../../services/socket');
            if (!socketService.socket) socketService.connect();
            const sock = socketService.socket;
            if (!sock) {
                setLogin(null);
                toast.error('Socket not available');
                return;
            }
            const room = `server_${serverId}_${channel}`;
            const onStream = (msg) => {
                if (msg?.channel !== channel) return;
                const ev = msg.data || {};
                const url = ev?.extra?.auth_url;
                if (url) {
                    setLogin((cur) => cur ? { ...cur, status: 'awaiting', authUrl: url } : cur);
                }
                if (ev.phase === 'done') {
                    if (ev.error) {
                        setLogin((cur) => cur ? { ...cur, status: 'error', error: ev.error } : cur);
                        toast.error(`Login failed: ${ev.error}`);
                    } else {
                        setLogin((cur) => cur ? { ...cur, status: 'done', certPath: ev?.extra?.cert_path } : cur);
                        toast.success('Cloudflare login complete');
                        // Refresh capabilities + status so the tab unlocks
                        // without a manual reload.
                        api.refreshRemoteCapabilities(serverId).catch(() => {});
                        loadStatus();
                        loadTunnels();
                    }
                    sock.off('server_stream', onStream);
                    sock.emit('leave_room', { room });
                }
            };
            sock.emit('join_room', { room });
            sock.on('server_stream', onStream);
        } catch (err) {
            toast.error(err.message || 'Failed to start login');
            setLogin(null);
        }
    }

    function handleCancelLogin() {
        setLogin(null);
    }

    if (serverStatus !== 'online') {
        return (
            <div className="offline-notice">
                <OfflineIcon />
                <h4>Server Offline</h4>
                <p>Tunnel management requires the server to be online.</p>
            </div>
        );
    }

    if (loading) {
        return <EmptyState loading loadingVariant="table" title="Loading tunnels" />;
    }

    // Status banner — three distinct states the UI cares about:
    //   1. binary missing      → "install cloudflared"
    //   2. binary, no cert     → "log in once"
    //   3. binary + cert       → ready to manage tunnels
    const notInstalled = status?.available === false;
    const notAuthed = status?.available && status?.authenticated === false;

    return (
        <div className="cloudflared-tab">
            <div className="cron-tab__header">
                <div className="cron-tab__status">
                    {notInstalled ? (
                        <Pill kind="amber">cloudflared not installed</Pill>
                    ) : notAuthed ? (
                        <Pill kind="amber">not authenticated — run cloudflared tunnel login</Pill>
                    ) : (
                        <Pill kind="green">cloudflared ready{status?.version ? ` (${status.version})` : ''}</Pill>
                    )}
                    <span className="cron-tab__count">{tunnels.length} tunnel{tunnels.length === 1 ? '' : 's'}</span>
                </div>
                <div className="cron-tab__actions">
                    <Button variant="outline" onClick={loadTunnels} disabled={notInstalled}>Refresh</Button>
                    <Button onClick={() => setShowCreateModal(true)} disabled={notInstalled || notAuthed}>
                        Create Tunnel
                    </Button>
                </div>
            </div>

            {(notInstalled || notAuthed) && (
                <div className="cloudflared-tab__hint">
                    {notInstalled ? (
                        <>
                            Install cloudflared on the server, then return here. See the{' '}
                            <a href="https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/" target="_blank" rel="noreferrer">
                                Cloudflare docs
                            </a>.
                        </>
                    ) : login ? (
                        <CloudflaredLoginCard login={login} onCancel={handleCancelLogin} />
                    ) : (
                        <div className="cloudflared-login-prompt">
                            <p>
                                Cloudflare needs you to authorise this agent once. Click{' '}
                                <strong>Login</strong> below — we&apos;ll start the OAuth flow on the
                                server and surface the URL for you to open in your browser. Once you
                                authorise, the agent picks up the cert.pem automatically and the
                                rest of this tab unlocks.
                            </p>
                            <Button onClick={handleStartLogin}>Login to Cloudflare</Button>
                        </div>
                    )}
                </div>
            )}

            {error && !notAuthed && !notInstalled && (
                <div className="alert alert-danger">{error}</div>
            )}

            {!notInstalled && !notAuthed && (
                tunnels.length === 0 ? (
                    <EmptyState
                        icon={Cloud}
                        title="No tunnels"
                        description="No tunnels on this server. Use Create Tunnel to make one."
                    />
                ) : (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>ID</th>
                                <th>Connections</th>
                                <th className="actions-cell">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {tunnels.map(t => (
                                <tr key={t.id || t.name}>
                                    <td><span className="cron-tab__name">{t.name}</span></td>
                                    <td className="mono">{(t.id || '').substring(0, 8)}…</td>
                                    <td>{t.connections?.length || 0}</td>
                                    <td className="actions-cell">
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            onClick={() => { setRouteTunnel(t); setShowRouteModal(true); }}
                                        >
                                            Route subdomain
                                        </Button>
                                        <button type="button"
                                            className="btn-icon danger"
                                            onClick={() => handleDelete(t)}
                                            title="Delete"
                                        >
                                            <TrashIcon />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )
            )}

            <Dialog
                open={showCreateModal}
                onOpenChange={(open) => { if (!open && !creating) setShowCreateModal(false); }}
            >
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Create Tunnel</DialogTitle>
                        <DialogDescription>
                            Provisions a new Cloudflare Tunnel on this server.
                        </DialogDescription>
                    </DialogHeader>
                    <form onSubmit={handleCreate} className="space-y-4">
                        <div className="space-y-1.5">
                            <Label htmlFor="cf-name">Tunnel Name</Label>
                            <Input
                                id="cf-name"
                                value={createName}
                                onChange={(e) => setCreateName(e.target.value)}
                                placeholder="my-app"
                                required
                                autoFocus
                            />
                            <p className="text-xs text-muted-foreground">Letters, numbers, dashes, underscores. Up to 32 chars.</p>
                        </div>
                        <DialogFooter>
                            <Button type="button" variant="outline" onClick={() => setShowCreateModal(false)} disabled={creating}>Cancel</Button>
                            <Button type="submit" disabled={creating}>{creating ? 'Creating…' : 'Create'}</Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>

            <Dialog
                open={showRouteModal && !!routeTunnel}
                onOpenChange={(open) => { if (!open && !routing) setShowRouteModal(false); }}
            >
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Route Subdomain{routeTunnel ? ` → ${routeTunnel.name}` : ''}</DialogTitle>
                        <DialogDescription>
                            A CNAME for this hostname will be created in Cloudflare DNS, pointing at the tunnel.
                        </DialogDescription>
                    </DialogHeader>
                    <form onSubmit={handleRoute} className="space-y-4">
                        <div className="space-y-1.5">
                            <Label htmlFor="cf-host">Hostname</Label>
                            <Input
                                id="cf-host"
                                value={routeHostname}
                                onChange={(e) => setRouteHostname(e.target.value)}
                                placeholder="app.example.com"
                                required
                                autoFocus
                            />
                        </div>
                        <DialogFooter>
                            <Button type="button" variant="outline" onClick={() => setShowRouteModal(false)} disabled={routing}>Cancel</Button>
                            <Button type="submit" disabled={routing}>{routing ? 'Adding…' : 'Add Route'}</Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>
        </div>
    );
};

// CloudflaredLoginCard renders the in-flight OAuth login state. The
// agent has spawned `cloudflared tunnel login` on the server and is
// streaming progress on a job channel; we render either a spinner
// (while we wait for the URL), the Open-in-Browser CTA (once the URL
// arrives), or a final success/error message.
const CloudflaredLoginCard = ({ login, onCancel }) => {
    if (!login) return null;
    if (login.status === 'starting') {
        return (
            <div className="cloudflared-login-card">
                <p>Asking the agent to start the Cloudflare login flow…</p>
                <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
            </div>
        );
    }
    if (login.status === 'awaiting' && login.authUrl) {
        return (
            <div className="cloudflared-login-card">
                <p>
                    <strong>Step 1 / 2:</strong> open the following URL in your browser, sign in
                    to Cloudflare, and pick the zone you want to associate with this agent.
                </p>
                <div className="cloudflared-login-card__actions">
                    <a
                        href={login.authUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-primary"
                    >
                        Open Cloudflare login
                    </a>
                    <button
                        type="button"
                        className="btn btn-outline"
                        onClick={() => navigator.clipboard?.writeText(login.authUrl)}
                    >
                        Copy URL
                    </button>
                </div>
                <p className="cloudflared-login-card__hint">
                    <strong>Step 2 / 2:</strong> waiting for the agent to receive cert.pem from
                    Cloudflare. This page will refresh automatically once authorisation completes.
                </p>
                <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
            </div>
        );
    }
    if (login.status === 'done') {
        return (
            <div className="cloudflared-login-card cloudflared-login-card--success">
                Authenticated. Refreshing…
            </div>
        );
    }
    if (login.status === 'error') {
        return (
            <div className="cloudflared-login-card cloudflared-login-card--error">
                <strong>Login failed:</strong> {login.error || 'unknown error'}
                <Button variant="outline" size="sm" onClick={onCancel}>Dismiss</Button>
            </div>
        );
    }
    return null;
};

export default CloudflaredTab;
