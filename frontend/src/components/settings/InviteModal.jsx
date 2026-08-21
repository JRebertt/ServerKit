import { useState, useEffect } from 'react';
import api from '../../services/api';
import PermissionEditor from './PermissionEditor';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';
import { copyToClipboard } from '@/utils/clipboard';
import { useTranslation } from 'react-i18next';

const InviteModal = ({ onClose, onCreated }) => {
    const { t } = useTranslation();
    const [email, setEmail] = useState('');
    const [role, setRole] = useState('developer');
    const [expiryDays, setExpiryDays] = useState(7);
    const [showPermissions, setShowPermissions] = useState(false);
    const [permissions, setPermissions] = useState({});
    const [templates, setTemplates] = useState({});
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [result, setResult] = useState(null);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        api.getPermissionTemplates().then(data => {
            setTemplates(data.templates || {});
            if (data.templates?.developer) {
                setPermissions(data.templates.developer);
            }
        }).catch(() => {});
    }, []);

    function handleRoleChange(newRole) {
        setRole(newRole);
        if (templates[newRole]) {
            setPermissions(templates[newRole]);
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            const data = {
                role,
                expires_in_days: expiryDays === 0 ? null : expiryDays,
            };
            if (email.trim()) data.email = email.trim();
            if (showPermissions && role !== 'admin') {
                data.permissions = permissions;
            }

            const response = await api.createInvitation(data);
            setResult(response);
            if (onCreated) onCreated();
        } catch (err) {
            setError(err.message || 'Failed to create invitation');
        } finally {
            setLoading(false);
        }
    }

    async function copyLink() {
        if (result?.invite_url && await copyToClipboard(result.invite_url)) {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    }

    // Show result screen after creation
    if (result) {
        return (
            <Modal open={true} onClose={onClose} title={t('app.inviteModal.invitationCreated', 'Invitation Created')} size="md">
                        <p>{t('app.inviteModal.shareThisInvitationLink', 'Share this invitation link:')}</p>
                        <div className="invite-link-display">
                            <code>{result.invite_url}</code>
                            <Button variant="ghost" size="sm" onClick={copyLink}>
                                {copied ? 'Copied!' : 'Copy'}
                            </Button>
                        </div>
                        {result.email_sent && (
                            <p className="text-success" style={{ marginTop: 12 }}>
                                {t('app.inviteModal.invitationEmailSentTo', 'Invitation email sent to')} {result.invitation.email}
                            </p>
                        )}
                        {result.email_error && (
                            <p className="text-warning" style={{ marginTop: 12 }}>
                                {t('app.inviteModal.emailCouldNotBeSent', 'Email could not be sent:')} {result.email_error}
                            </p>
                        )}
                    <div className="modal-footer">
                        <Button variant="default" onClick={onClose}>{t('app.inviteModal.done', 'Done')}</Button>
                    </div>
            </Modal>
        );
    }

    return (
        <Modal open={true} onClose={onClose} title={t('app.inviteModal.inviteUser', 'Invite User')} size="md">
                <form onSubmit={handleSubmit}>
                    <div className="modal-body">
                        {error && <div className="error-message">{error}</div>}

                        <div className="form-group">
                            <Label htmlFor="invite-email">{t('app.inviteModal.emailOptional', 'Email (optional)')}</Label>
                            <Input
                                type="email"
                                id="invite-email"
                                value={email}
                                onChange={e => setEmail(e.target.value)}
                                placeholder={t('app.inviteModal.userExampleComLeaveBlankFor', 'user@example.com (leave blank for link-only)')}
                            />
                            <span className="form-help">
                                {t('app.inviteModal.ifProvidedAnInvitationEmailWill', 'If provided, an invitation email will be sent. Otherwise, share the link manually.')}
                            </span>
                        </div>

                        <div className="form-row">
                            <div className="form-group">
                                <Label htmlFor="invite-role">{t('app.inviteModal.role', 'Role')}</Label>
                                <Select value={role} onValueChange={handleRoleChange}>
                                    <SelectTrigger id="invite-role">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="admin">{t('app.inviteModal.admin', 'Admin')}</SelectItem>
                                        <SelectItem value="developer">{t('app.inviteModal.developer', 'Developer')}</SelectItem>
                                        <SelectItem value="viewer">{t('app.inviteModal.viewer', 'Viewer')}</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>

                            <div className="form-group">
                                <Label htmlFor="invite-expiry">{t('app.inviteModal.expires', 'Expires')}</Label>
                                <Select
                                    value={String(expiryDays)}
                                    onValueChange={(val) => setExpiryDays(Number(val))}
                                >
                                    <SelectTrigger id="invite-expiry">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="1">{t('app.inviteModal.1Day', '1 day')}</SelectItem>
                                        <SelectItem value="3">{t('app.inviteModal.3Days', '3 days')}</SelectItem>
                                        <SelectItem value="7">{t('app.inviteModal.7Days', '7 days')}</SelectItem>
                                        <SelectItem value="30">{t('app.inviteModal.30Days', '30 days')}</SelectItem>
                                        <SelectItem value="0">{t('app.inviteModal.never', 'Never')}</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>

                        {role !== 'admin' && (
                            <div className="customize-permissions-section">
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => {
                                        if (!showPermissions && templates[role]) {
                                            setPermissions(templates[role]);
                                        }
                                        setShowPermissions(!showPermissions);
                                    }}
                                >
                                    {showPermissions ? 'Hide' : 'Customize'} {t('app.inviteModal.permissions', 'Permissions')}
                                    <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2" style={{ marginLeft: 4 }}>
                                        {showPermissions
                                            ? <polyline points="18 15 12 9 6 15"/>
                                            : <polyline points="6 9 12 15 18 9"/>
                                        }
                                    </svg>
                                </Button>
                                {showPermissions && (
                                    <PermissionEditor
                                        permissions={permissions}
                                        onChange={setPermissions}
                                    />
                                )}
                            </div>
                        )}
                    </div>

                    <div className="modal-footer">
                        <Button type="button" variant="ghost" onClick={onClose}>{t('app.inviteModal.cancel', 'Cancel')}</Button>
                        <Button type="submit" variant="default" disabled={loading}>
                            {loading ? 'Creating...' : 'Create Invitation'}
                        </Button>
                    </div>
                </form>
        </Modal>
    );
};

export default InviteModal;
