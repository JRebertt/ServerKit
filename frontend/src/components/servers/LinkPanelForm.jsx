import { useEffect, useState } from 'react';
import { Unlink } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { ConfirmDialog } from '../ConfirmDialog';
import StatusBadge from '../StatusBadge';
import { InfoList, InfoItem } from '../InfoList';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { usePolling } from '@/hooks/usePolling';

const POLL_INTERVAL = 5000;

function formatTimestamp(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

// "Link panel" tab of the Add Server modal — the inverse of the other two
// tabs: instead of adding a remote server to THIS panel, link THIS panel to a
// master ServerKit so the master can manage this server (embedded agent mode,
// no Go agent install). Polls the link status while visible so the connection
// badge flips to Connected live.
const LinkPanelForm = ({ onClose }) => {
    const toast = useToast();
    const [status, setStatus] = useState(null); // null = still loading
    const [masterUrl, setMasterUrl] = useState('');
    const [token, setToken] = useState('');
    const [name, setName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [linkError, setLinkError] = useState('');
    const [unlinkOpen, setUnlinkOpen] = useState(false);

    async function loadStatus({ silent = false } = {}) {
        try {
            const data = await api.getLinkedPanel();
            setStatus(data);
        } catch (err) {
            if (!silent) setLinkError(err?.data?.error || err.message || 'Failed to load linked panel status');
        }
    }

    useEffect(() => { loadStatus(); }, []);
    usePolling(() => loadStatus({ silent: true }), POLL_INTERVAL, { immediate: false });

    async function handleLink(e) {
        e.preventDefault();
        setLinkError('');
        setSubmitting(true);
        try {
            const result = await api.linkPanel({
                master_url: masterUrl.trim(),
                registration_token: token.trim(),
                name: name.trim() || undefined,
            });
            toast.success('Panel linked to master');
            setStatus(result.status || { linked: true, master_url: masterUrl.trim() });
            setToken('');
        } catch (err) {
            setLinkError(err?.data?.error || err.message || 'Failed to link panel');
        } finally {
            setSubmitting(false);
        }
    }

    async function handleUnlink() {
        try {
            await api.unlinkPanel();
            toast.success('Panel unlinked');
            setUnlinkOpen(false);
            setStatus({ linked: false });
        } catch (err) {
            toast.error(err?.data?.error || err.message || 'Failed to unlink panel');
        }
    }

    if (status?.linked) {
        return (
            <div className="server-setup-form">
                <div className="server-setup-form__body">
                    <div className="link-panel-status">
                        <StatusBadge status={status.connected ? 'connected' : 'disconnected'} />
                        <InfoList>
                            <InfoItem label="Master" value={status.master_url} mono />
                            <InfoItem
                                label="Remote server"
                                value={status.remote_server_name
                                    ? `${status.remote_server_name}${status.remote_server_id ? ` (#${status.remote_server_id})` : ''}`
                                    : (status.remote_server_id ? `#${status.remote_server_id}` : '—')}
                            />
                            <InfoItem label="Linked since" value={formatTimestamp(status.created_at)} />
                            <InfoItem label="Last heartbeat" value={formatTimestamp(status.last_heartbeat_at)} />
                        </InfoList>
                        {status.last_error && (
                            <div className="error-message">
                                Connection error: {status.last_error}
                            </div>
                        )}
                    </div>
                </div>

                <div className="modal-actions">
                    <Button type="button" variant="outline" onClick={onClose}>
                        Close
                    </Button>
                    <Button type="button" variant="destructive" onClick={() => setUnlinkOpen(true)}>
                        <Unlink size={14} /> Unlink
                    </Button>
                </div>

                <ConfirmDialog
                    isOpen={unlinkOpen}
                    title="Unlink from master panel?"
                    message={`This server will stop being manageable by ${status?.master_url || 'the master panel'}. The link credentials are removed from this panel.`}
                    confirmText="Unlink"
                    variant="danger"
                    onConfirm={handleUnlink}
                    onCancel={() => setUnlinkOpen(false)}
                />
            </div>
        );
    }

    return (
        <form className="server-setup-form" onSubmit={handleLink}>
            <div className="server-setup-form__body">
                <p className="section-description">
                    Link this panel to a master ServerKit so it can manage this server — no
                    separate agent install needed. Generate a registration token on the
                    master: Servers → Add Server / regenerate token.
                </p>

                {linkError && <div className="error-message">{linkError}</div>}

                <div className="form-group">
                    <label>Master URL *</label>
                    <Input
                        type="url"
                        value={masterUrl}
                        onChange={(e) => setMasterUrl(e.target.value)}
                        placeholder="https://panel.example.com"
                        required
                    />
                </div>

                <div className="form-group">
                    <label>Registration token *</label>
                    <Input
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        placeholder="Token generated on the master"
                        required
                    />
                </div>

                <div className="form-group">
                    <label>Display name</label>
                    <Input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Optional"
                    />
                    <span className="form-hint">How this server appears on the master panel.</span>
                </div>
            </div>

            <div className="modal-actions">
                <Button type="button" variant="outline" onClick={onClose}>
                    Cancel
                </Button>
                <Button type="submit" disabled={submitting || status === null}>
                    {submitting ? 'Linking…' : 'Link panel'}
                </Button>
            </div>
        </form>
    );
};

export default LinkPanelForm;
