import { useState, useEffect } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { DangerZone } from '../DangerZone';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Pill } from '../ds';
import Modal from '@/components/Modal';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import TagsPanel from '../shared/TagsPanel';
import {
    TOKEN_EXPIRY_OPTIONS,
    KeyIcon,
    ServerIcon,
    NetworkIcon,
    TrashIcon,
    TagIcon,
    TerminalIcon,
    CopyIcon,
    WindowsIcon,
} from './serverDetailShared';

const AgentRegistrationSection = ({ server, onRegenerateToken }) => {
    const expires = server.registration_expires;
    const isExpired = expires && new Date(expires) < new Date();
    const isOnline = server.status === 'online';

    return (
        <div className="form-section form-section--accent">
            <div className="form-section__header">
                <span className="form-section__icon"><KeyIcon /></span>
                <div>
                    <h3>Connection String</h3>
                    <p className="section-description">
                        Generate a fresh connection string to pair (or re-pair) this server.
                        Useful after reinstalling the agent — old credentials are gone, but a
                        new string brings the agent right back to this row.
                        {isOnline && ' This server is currently online; regenerating only affects re-pairing.'}
                        {isExpired && ' The previous token has expired.'}
                    </p>
                </div>
            </div>
            <Button onClick={onRegenerateToken}>
                <KeyIcon /> Generate Connection String
            </Button>
        </div>
    );
};

const ServerSettingsTab = ({ server, onUpdate, onRegenerateToken, onDelete }) => {
    const { confirm: confirmSettings } = useConfirm();
    const [formData, setFormData] = useState({
        name: server.name || '',
        description: server.description || '',
        hostname: server.hostname || '',
        ip_address: server.ip_address || '',
        group_id: server.group_id || ''
    });
    const [groups, setGroups] = useState([]);
    const [loading, setLoading] = useState(false);
    const [allowedIPs, setAllowedIPs] = useState([]);
    const [newIP, setNewIP] = useState('');
    const [connectionInfo, setConnectionInfo] = useState(null);
    const [rotatingKey, setRotatingKey] = useState(false);
    const toast = useToast();

    useEffect(() => {
        loadGroups();
        loadSecurityData();
    }, []);

    async function loadGroups() {
        try {
            const data = await api.getServerGroups();
            setGroups(Array.isArray(data) ? data : []);
        } catch (err) {
            console.error('Failed to load groups:', err);
        }
    }

    async function loadSecurityData() {
        try {
            const [ipsData, connData] = await Promise.all([
                api.getAllowedIPs(server.id),
                api.getConnectionInfo(server.id),
            ]);
            setAllowedIPs(ipsData.allowed_ips || []);
            setConnectionInfo(connData);
        } catch (err) {
            console.error('Failed to load security data:', err);
        }
    }

    async function handleAddIP() {
        if (!newIP.trim()) return;
        const updated = [...allowedIPs, newIP.trim()];
        try {
            await api.updateAllowedIPs(server.id, updated);
            setAllowedIPs(updated);
            setNewIP('');
            toast.success('IP allowlist updated');
        } catch (err) {
            toast.error(err.details?.[0] || err.message || 'Invalid IP pattern');
        }
    }

    async function handleRemoveIP(ip) {
        const updated = allowedIPs.filter(i => i !== ip);
        try {
            await api.updateAllowedIPs(server.id, updated);
            setAllowedIPs(updated);
            toast.success('IP removed from allowlist');
        } catch (err) {
            toast.error(err.message || 'Failed to update allowlist');
        }
    }

    async function handleRotateKey() {
        const confirmed = await confirmSettings({ title: 'Rotate Credentials', message: 'Rotate API credentials? The agent must be online to receive new credentials.', variant: 'warning' });
        if (!confirmed) return;
        setRotatingKey(true);
        try {
            const result = await api.rotateAPIKey(server.id);
            if (result.success) {
                toast.success('Credential rotation initiated. Agent will update shortly.');
            } else {
                toast.error(result.error || 'Failed to rotate credentials');
            }
        } catch (err) {
            toast.error(err.message || 'Failed to rotate credentials');
        } finally {
            setRotatingKey(false);
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        setLoading(true);

        try {
            await api.updateServer(server.id, formData);
            toast.success('Server updated successfully');
            onUpdate();
        } catch (err) {
            toast.error(err.message || 'Failed to update server');
        } finally {
            setLoading(false);
        }
    }

    function handleChange(e) {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    }

    return (
        <div className="settings-tab">
            <div className="settings-grid">
                <form onSubmit={handleSubmit} className="settings-form">
                    <div className="form-section form-section--accent">
                        <div className="form-section__header">
                            <span className="form-section__icon"><ServerIcon /></span>
                            <div>
                                <h3>Basic Information</h3>
                                <p className="section-description">Identity and grouping for this server.</p>
                            </div>
                        </div>
                        <div className="form-group">
                            <label>Server Name</label>
                            <Input
                                type="text"
                                name="name"
                                value={formData.name}
                                onChange={handleChange}
                                required
                            />
                        </div>

                        <div className="form-group">
                            <label>Description</label>
                            <Textarea
                                name="description"
                                value={formData.description}
                                onChange={handleChange}
                                rows={3}
                            />
                        </div>

                        <div className="form-row">
                            <div className="form-group">
                                <label>Hostname</label>
                                <Input
                                    type="text"
                                    name="hostname"
                                    value={formData.hostname}
                                    onChange={handleChange}
                                />
                            </div>
                            <div className="form-group">
                                <label>IP Address</label>
                                <Input
                                    type="text"
                                    name="ip_address"
                                    value={formData.ip_address}
                                    onChange={handleChange}
                                />
                            </div>
                        </div>

                        <div className="form-group">
                            <label>Group</label>
                            <select name="group_id" value={formData.group_id} onChange={handleChange}>
                                <option value="">No Group</option>
                                {groups.map(group => (
                                    <option key={group.id} value={group.id}>{group.name}</option>
                                ))}
                            </select>
                        </div>

                        <Button type="submit" disabled={loading}>
                            {loading ? 'Saving...' : 'Save Changes'}
                        </Button>
                    </div>
                </form>

                <AgentRegistrationSection
                    server={server}
                    onRegenerateToken={onRegenerateToken}
                />
            </div>

            <div className="security-grid">
                <div className="form-section form-section--accent">
                    <div className="form-section__header">
                        <span className="form-section__icon"><NetworkIcon /></span>
                        <div>
                            <h3>Connection & IP Allowlist</h3>
                            <p className="section-description">
                                Restrict which IPs can connect. Supports single IPs, CIDR notation, and wildcards.
                            </p>
                        </div>
                    </div>

                    {connectionInfo && (
                        <div className="security-info-bar">
                            <div className="security-info-item">
                                <span className="security-info-label">Connection IP</span>
                                <span className="security-info-value">
                                    <code>{connectionInfo.ip_address || 'Not connected'}</code>
                                </span>
                            </div>
                            {connectionInfo.connected_since && (
                                <div className="security-info-item">
                                    <span className="security-info-label">Connected Since</span>
                                    <span className="security-info-value">{new Date(connectionInfo.connected_since).toLocaleString()}</span>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="subsection">
                        <div className="ip-list">
                            {allowedIPs.length === 0 ? (
                                <div className="ip-empty">No IP restrictions (all IPs allowed)</div>
                            ) : (
                                allowedIPs.map((ip, idx) => (
                                    <div key={idx} className="ip-item">
                                        <code>{ip}</code>
                                        {connectionInfo?.ip_address === ip && (
                                            <Pill kind="green" dot={false}>Current</Pill>
                                        )}
                                        <button type="button"
                                            className="btn-icon danger"
                                            onClick={() => handleRemoveIP(ip)}
                                            title="Remove"
                                        >
                                            <TrashIcon />
                                        </button>
                                    </div>
                                ))
                            )}
                        </div>

                        <div className="ip-add-form">
                            <Input
                                type="text"
                                placeholder="IP address or CIDR (e.g., 192.168.1.0/24)"
                                value={newIP}
                                onChange={(e) => setNewIP(e.target.value)}
                                onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddIP())}
                            />
                            <Button variant="outline" onClick={handleAddIP}>
                                Add
                            </Button>
                        </div>

                        {connectionInfo?.ip_address && allowedIPs.length > 0 && !allowedIPs.some(ip => {
                            return ip === connectionInfo.ip_address || ip.includes('*') || ip.includes('/');
                        }) && (
                            <div className="security-warning">
                                Current connection IP ({connectionInfo.ip_address}) may be blocked by these rules.
                            </div>
                        )}
                    </div>
                </div>

                <div className="form-section form-section--accent">
                    <div className="form-section__header">
                        <span className="form-section__icon"><KeyIcon /></span>
                        <div>
                            <h3>API Key Rotation</h3>
                            <p className="section-description">
                                Rotate the API credentials used by the agent. The agent must be online to receive new credentials.
                            </p>
                        </div>
                    </div>
                    <div className="key-rotation-actions">
                        <Button
                            variant="outline"
                            onClick={handleRotateKey}
                            disabled={rotatingKey || server.status !== 'online'}
                        >
                            <KeyIcon /> {rotatingKey ? 'Rotating...' : 'Rotate API Key'}
                        </Button>
                        {server.api_key_last_rotated && (
                            <span className="key-rotation-hint">Last rotated: {new Date(server.api_key_last_rotated).toLocaleString()}</span>
                        )}
                    </div>

                    {server.status !== 'online' && (
                        <div className="security-notice">
                            Server must be online to rotate credentials.
                        </div>
                    )}
                </div>
            </div>

            <div className="form-section form-section--accent shared-resources-section">
                <div className="form-section__header">
                    <span className="form-section__icon"><TagIcon /></span>
                    <div>
                        <h3>Tags</h3>
                        <p className="section-description">
                            Free-form labels for grouping and filtering this server across the panel.
                        </p>
                    </div>
                </div>
                <TagsPanel resourceType="server" resourceId={server.id} />
            </div>

            <DangerZone
                title="Danger Zone"
                description="Removing this server will disconnect the agent and delete all associated data."
                action={
                    <Button variant="destructive" onClick={onDelete}>
                        <TrashIcon /> Remove Server
                    </Button>
                }
            />
        </div>
    );
};

export const TokenModal = ({ server, onClose, onGenerated }) => {
    const toast = useToast();
    const [expiresIn, setExpiresIn] = useState(7 * 24 * 60 * 60);
    const [generating, setGenerating] = useState(false);
    // Result of the most recent generation in *this* modal session. We
    // don't fall back to server.connection_string because the panel only
    // ever returns the connection string at create/regenerate time — once
    // the modal closes, the value is gone, so showing a stale one would
    // be misleading.
    const [result, setResult] = useState(null);

    async function handleGenerate() {
        setGenerating(true);
        try {
            const data = await api.generateRegistrationToken(server.id, { expires_in: expiresIn });
            setResult(data);
            onGenerated?.(data);
            toast.success('Connection string generated');
        } catch (err) {
            toast.error(err.message || 'Failed to generate connection string');
        } finally {
            setGenerating(false);
        }
    }

    function copyToClipboard(text) {
        navigator.clipboard.writeText(text);
        toast.success('Copied to clipboard');
    }

    // Download-then-run, not `curl … | sudo bash`: a piped curl failure is
    // invisible (the pipeline reports bash's exit status, so a 404 still exits
    // 0 with nothing installed). See issue #101.
    const linuxScript = result ? `curl -fsSL ${window.location.origin}/api/v1/servers/install.sh -o /tmp/serverkit-agent-install.sh && \\
  sudo bash /tmp/serverkit-agent-install.sh \\
  --server "${window.location.origin}" \\
  --token "${result.registration_token}"` : '';
    const windowsScript = result ? `irm ${window.location.origin}/api/v1/servers/install.ps1 | iex
Install-ServerKitAgent -Server "${window.location.origin}" -Token "${result.registration_token}"` : '';

    return (
        <Modal
            open
            onClose={onClose}
            title="Connection String"
            size="lg"
            footer={!result ? (
                <>
                    <Button variant="outline" onClick={onClose}>Cancel</Button>
                    <Button onClick={handleGenerate} disabled={generating}>
                        {generating ? 'Generating…' : 'Generate'}
                    </Button>
                </>
            ) : (
                <>
                    <Button variant="outline" onClick={() => setResult(null)}>
                        Generate another
                    </Button>
                    <Button onClick={onClose}>Done</Button>
                </>
            )}
        >
            {!result && (
                <p className="sk-modal__subtitle">
                    Generate a single pasteable string the agent can consume.
                    The token inside is single-use — burned the moment any
                    agent registers with it.
                </p>
            )}

            {!result ? (
                <>
                        <div className="space-y-2">
                            <Label htmlFor="token-expires">Token expires</Label>
                            <Select value={String(expiresIn)} onValueChange={(v) => setExpiresIn(Number(v))}>
                                <SelectTrigger id="token-expires">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {TOKEN_EXPIRY_OPTIONS.map(opt => (
                                        <SelectItem key={opt.value} value={String(opt.value)}>{opt.label}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </>
                ) : (
                    <>
                        <div className="token-status">
                            <span className="token-status-dot active" />
                            <span>
                                Active — expires {new Date(result.registration_expires).toLocaleString()}
                            </span>
                        </div>

                        <div className="connection-string-field">
                            <div className="connection-string-field__header">
                                <KeyIcon />
                                <span>Connection string</span>
                                <Button variant="outline" size="sm" onClick={() => copyToClipboard(result.connection_string)}>
                                    <CopyIcon /> Copy
                                </Button>
                            </div>
                            <pre className="connection-string-field__value">{result.connection_string}</pre>
                        </div>

                        <details className="install-fallback">
                            <summary>Need to install the agent first? Use the one-liner installer.</summary>
                            <div className="install-tabs" style={{ marginTop: '0.75rem' }}>
                                <div className="install-tab">
                                    <div className="install-tab-header">
                                        <TerminalIcon />
                                        <div className="install-tab-title">
                                            <span>Linux</span>
                                            <span className="install-tab-description">curl, tar, sudo, and systemd</span>
                                        </div>
                                        <Button variant="outline" size="sm" onClick={() => copyToClipboard(linuxScript)}>
                                            <CopyIcon /> Copy
                                        </Button>
                                    </div>
                                    <pre className="install-script">{linuxScript}</pre>
                                </div>
                                <div className="install-tab">
                                    <div className="install-tab-header">
                                        <WindowsIcon />
                                        <div className="install-tab-title">
                                            <span>Windows (PowerShell)</span>
                                            <span className="install-tab-description">Run as Administrator</span>
                                        </div>
                                        <Button variant="outline" size="sm" onClick={() => copyToClipboard(windowsScript)}>
                                            <CopyIcon /> Copy
                                        </Button>
                                    </div>
                                    <pre className="install-script">{windowsScript}</pre>
                                </div>
                            </div>
                        </details>
                    </>
                )}
        </Modal>
    );
};

export default ServerSettingsTab;
