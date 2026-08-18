import { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../services/api';
import useSettingFocus from '../../hooks/useSettingFocus';
import TwoFactorPolicyCard from './TwoFactorPolicyCard';
import SSOProviderIcon from '../SSOProviderIcon';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { copyToClipboard } from '@/utils/clipboard';

const LinkedAccounts = ({ register }) => {
    const { ssoProviders } = useAuth();
    const [identities, setIdentities] = useState([]);
    const [loading, setLoading] = useState(true);
    const [unlinking, setUnlinking] = useState(null);
    const [linkingProvider, setLinkingProvider] = useState(null);
    const [error, setError] = useState('');

    useEffect(() => {
        loadIdentities();
    }, []);

    async function loadIdentities() {
        try {
            const data = await api.getSSOIdentities();
            setIdentities(data.identities || []);
        } catch (err) {
            // SSO may not be configured; silently handle
        } finally {
            setLoading(false);
        }
    }

    async function handleUnlink(provider) {
        setUnlinking(provider);
        setError('');
        try {
            await api.unlinkSSOProvider(provider);
            await loadIdentities();
        } catch (err) {
            setError(err.message);
        } finally {
            setUnlinking(null);
        }
    }

    async function handleLink(provider) {
        setLinkingProvider(provider);
        setError('');
        try {
            const redirectUri = `${window.location.origin}/login/callback/${provider}`;
            const { auth_url } = await api.startSSOAuth(provider, redirectUri);
            window.location.href = auth_url;
        } catch (err) {
            setError(err.message);
            setLinkingProvider(null);
        }
    }

    if (loading || (!ssoProviders?.length && !identities.length)) {
        return null;
    }

    const linkedProviderIds = identities.map(i => i.provider);
    const availableToLink = (ssoProviders || []).filter(p => !linkedProviderIds.includes(p.id));

    return (
        <div {...register('security-linked-accounts', 'settings-card')}>
            <h3>Linked Accounts</h3>
            <p className="text-secondary">Connect external identity providers to your account</p>

            {error && <div className="alert alert-danger">{error}</div>}

            {identities.length > 0 && (
                <div className="linked-accounts-list">
                    {identities.map(identity => (
                        <div key={identity.id} className="linked-account">
                            <div className="linked-account__info">
                                <SSOProviderIcon provider={identity.provider} />
                                <div>
                                    <span className="linked-account__provider">{identity.provider}</span>
                                    <span className="linked-account__email">{identity.provider_email}</span>
                                </div>
                            </div>
                            <Button
                                variant="destructive"
                                size="sm"
                                onClick={() => handleUnlink(identity.provider)}
                                disabled={unlinking === identity.provider}
                            >
                                {unlinking === identity.provider ? 'Unlinking...' : 'Unlink'}
                            </Button>
                        </div>
                    ))}
                </div>
            )}

            {availableToLink.length > 0 && (
                <div className="linked-accounts-available">
                    {availableToLink.map(p => (
                        <Button
                            key={p.id}
                            variant="outline"
                            size="sm"
                            onClick={() => handleLink(p.id)}
                            disabled={linkingProvider === p.id}
                        >
                            <SSOProviderIcon provider={p.id} />
                            {linkingProvider === p.id ? 'Redirecting...' : `Link ${p.name}`}
                        </Button>
                    ))}
                </div>
            )}
        </div>
    );
};

const SecuritySettingsTab = () => {
    const { updateUser, user, isAdmin } = useAuth();
    const register = useSettingFocus();
    const [formData, setFormData] = useState({
        currentPassword: '',
        newPassword: '',
        confirmPassword: ''
    });
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState(null);

    // 2FA state
    const [twoFAStatus, setTwoFAStatus] = useState(null);
    const [twoFALoading, setTwoFALoading] = useState(true);
    const [showSetupModal, setShowSetupModal] = useState(false);
    const [showDisableModal, setShowDisableModal] = useState(false);
    const [showBackupCodesModal, setShowBackupCodesModal] = useState(false);
    const [setupData, setSetupData] = useState(null);
    const [verificationCode, setVerificationCode] = useState('');
    const [backupCodes, setBackupCodes] = useState([]);
    const [twoFAError, setTwoFAError] = useState('');

    useEffect(() => {
        load2FAStatus();
    }, []);

    async function load2FAStatus() {
        try {
            const status = await api.get2FAStatus();
            setTwoFAStatus(status);
        } catch (err) {
            console.error('Failed to load 2FA status:', err);
        } finally {
            setTwoFALoading(false);
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        setMessage(null);

        if (formData.newPassword !== formData.confirmPassword) {
            setMessage({ type: 'error', text: 'Passwords do not match' });
            return;
        }

        if (formData.newPassword.length < 8) {
            setMessage({ type: 'error', text: 'Password must be at least 8 characters' });
            return;
        }

        setLoading(true);

        try {
            await updateUser({ password: formData.newPassword });
            setMessage({ type: 'success', text: 'Password changed successfully' });
            setFormData({ currentPassword: '', newPassword: '', confirmPassword: '' });
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setLoading(false);
        }
    }

    async function handleInitiate2FA() {
        setTwoFAError('');
        setTwoFALoading(true);
        try {
            const data = await api.initiate2FASetup();
            setSetupData(data);
            setShowSetupModal(true);
        } catch (err) {
            setTwoFAError(err.message);
        } finally {
            setTwoFALoading(false);
        }
    }

    async function handleConfirm2FA() {
        if (!verificationCode || verificationCode.length !== 6) {
            setTwoFAError('Please enter a 6-digit code');
            return;
        }

        setTwoFALoading(true);
        setTwoFAError('');
        try {
            const result = await api.confirm2FASetup(verificationCode);
            setBackupCodes(result.backup_codes);
            setShowSetupModal(false);
            setShowBackupCodesModal(true);
            setVerificationCode('');
            load2FAStatus();
        } catch (err) {
            setTwoFAError(err.message || 'Invalid verification code');
        } finally {
            setTwoFALoading(false);
        }
    }

    async function handleDisable2FA() {
        if (!verificationCode) {
            setTwoFAError('Please enter a verification code');
            return;
        }

        setTwoFALoading(true);
        setTwoFAError('');
        try {
            await api.disable2FA(verificationCode);
            setShowDisableModal(false);
            setVerificationCode('');
            load2FAStatus();
        } catch (err) {
            setTwoFAError(err.message || 'Invalid verification code');
        } finally {
            setTwoFALoading(false);
        }
    }

    async function handleRegenerateBackupCodes() {
        if (!verificationCode || verificationCode.length !== 6) {
            setTwoFAError('Please enter a 6-digit code');
            return;
        }

        setTwoFALoading(true);
        setTwoFAError('');
        try {
            const result = await api.regenerateBackupCodes(verificationCode);
            setBackupCodes(result.backup_codes);
            setShowBackupCodesModal(true);
            setVerificationCode('');
            load2FAStatus();
        } catch (err) {
            setTwoFAError(err.message || 'Invalid verification code');
        } finally {
            setTwoFALoading(false);
        }
    }

    function downloadBackupCodes() {
        const content = `ServerKit Backup Codes
Generated: ${new Date().toLocaleString()}

These codes can be used to access your account if you lose your authenticator device.
Each code can only be used once.

${backupCodes.join('\n')}

Keep these codes in a safe place.`;

        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'serverkit-backup-codes.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function copyBackupCodes() {
        copyToClipboard(backupCodes.join('\n'));
    }

    return (
        <div className="settings-section">
            <div className="section-header">
                <h2>Security Settings</h2>
                <p>Manage your password and security preferences</p>
            </div>

            {message && (
                <div className={`alert alert-${message.type === 'success' ? 'success' : 'danger'}`}>
                    {message.text}
                </div>
            )}

            {/* Two-Factor Authentication Section */}
            <div {...register('security-2fa', 'settings-card two-fa-card')}>
                <div className="two-fa-header">
                    <div className="two-fa-icon">
                        <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" fill="none" strokeWidth="2">
                            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                            <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                        </svg>
                    </div>
                    <div>
                        <h3>Two-Factor Authentication (2FA)</h3>
                        <p>Add an extra layer of security to your account</p>
                    </div>
                </div>

                {twoFALoading && !twoFAStatus ? (
                    <div className="loading-sm">Loading...</div>
                ) : twoFAStatus?.enabled ? (
                    <div className="two-fa-enabled">
                        <div className="two-fa-status">
                            <Badge variant="success">Enabled</Badge>
                            <span className="two-fa-info">
                                Enabled on {new Date(twoFAStatus.confirmed_at).toLocaleDateString()}
                            </span>
                        </div>
                        <div className="two-fa-backup-info">
                            <span>Backup codes remaining: <strong>{twoFAStatus.backup_codes_remaining}</strong></span>
                            {twoFAStatus.backup_codes_remaining <= 3 && (
                                <span className="warning-text">Consider regenerating your backup codes</span>
                            )}
                        </div>
                        <div className="two-fa-actions">
                            <Button
                                variant="outline"
                                onClick={() => {
                                    setVerificationCode('');
                                    setTwoFAError('');
                                    setShowBackupCodesModal(true);
                                }}
                            >
                                Regenerate Backup Codes
                            </Button>
                            <Button
                                variant="destructive"
                                onClick={() => {
                                    setVerificationCode('');
                                    setTwoFAError('');
                                    setShowDisableModal(true);
                                }}
                            >
                                Disable 2FA
                            </Button>
                        </div>
                    </div>
                ) : (
                    <div className="two-fa-disabled">
                        <p className="two-fa-description">
                            Two-factor authentication adds an additional layer of security to your account
                            by requiring a code from your authenticator app in addition to your password.
                        </p>
                        <Button
                            variant="default"
                            onClick={handleInitiate2FA}
                            disabled={twoFALoading}
                        >
                            Enable Two-Factor Authentication
                        </Button>
                    </div>
                )}
            </div>

            <form onSubmit={handleSubmit} {...register('security-password', 'settings-form')}>
                <h3>Change Password</h3>

                <div className="form-group">
                    <Label>Current Password</Label>
                    <Input
                        type="password"
                        value={formData.currentPassword}
                        onChange={(e) => setFormData({ ...formData, currentPassword: e.target.value })}
                        placeholder="Enter current password"
                    />
                </div>

                <div className="form-group">
                    <Label>New Password</Label>
                    <Input
                        type="password"
                        value={formData.newPassword}
                        onChange={(e) => setFormData({ ...formData, newPassword: e.target.value })}
                        placeholder="Enter new password"
                        required
                    />
                    <span className="form-help">Minimum 8 characters</span>
                </div>

                <div className="form-group">
                    <Label>Confirm New Password</Label>
                    <Input
                        type="password"
                        value={formData.confirmPassword}
                        onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                        placeholder="Confirm new password"
                        required
                    />
                </div>

                <div className="form-actions">
                    <Button type="submit" variant="default" disabled={loading}>
                        {loading ? 'Changing...' : 'Change Password'}
                    </Button>
                </div>
            </form>

            <div {...register('security-sessions', 'settings-card')}>
                <h3>Sessions</h3>
                <p>Manage your active sessions</p>
                <div className="session-item current">
                    <div className="session-info">
                        <svg viewBox="0 0 24 24" width="20" height="20">
                            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                            <line x1="8" y1="21" x2="16" y2="21"/>
                            <line x1="12" y1="17" x2="12" y2="21"/>
                        </svg>
                        <div>
                            <span className="session-device">Current Session</span>
                            <span className="session-details">This device - Active now</span>
                        </div>
                    </div>
                    <Badge variant="success">Current</Badge>
                </div>
            </div>

            {/* Require-2FA policy (admin only) — a policy, never a default. */}
            {isAdmin && <TwoFactorPolicyCard {...register('security-2fa-policy', 'settings-card')} />}

            {/* Linked Accounts */}
            <LinkedAccounts register={register} />

            {/* 2FA Setup Modal */}
            {showSetupModal && setupData && (
                <Modal open={true} onClose={() => setShowSetupModal(false)} title="Set Up Two-Factor Authentication" size="md">
                            <div className="setup-steps">
                                <div className="setup-step">
                                    <span className="step-number">1</span>
                                    <div className="step-content">
                                        <h4>Scan the QR Code</h4>
                                        <p>Use your authenticator app (Google Authenticator, Authy, 1Password, etc.) to scan this QR code.</p>
                                        {setupData.qr_code ? (
                                            <div className="qr-code-container">
                                                <img src={setupData.qr_code} alt="2FA QR Code" className="qr-code" />
                                            </div>
                                        ) : (
                                            <div className="qr-fallback">
                                                <p>QR code unavailable. Enter this secret manually:</p>
                                                <code className="secret-key">{setupData.secret}</code>
                                            </div>
                                        )}
                                        <details className="manual-entry">
                                            <summary>Can&apos;t scan? Enter manually</summary>
                                            <p>Account: {user?.email ?? ''}</p>
                                            <p>Secret: <code>{setupData.secret}</code></p>
                                        </details>
                                    </div>
                                </div>

                                <div className="setup-step">
                                    <span className="step-number">2</span>
                                    <div className="step-content">
                                        <h4>Enter Verification Code</h4>
                                        <p>Enter the 6-digit code from your authenticator app to verify setup.</p>
                                        <Input
                                            type="text"
                                            value={verificationCode}
                                            onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                                            placeholder="000000"
                                            className="verification-input"
                                            autoFocus
                                        />
                                        {twoFAError && <p className="error-text">{twoFAError}</p>}
                                    </div>
                                </div>
                            </div>
                        <div className="modal-footer">
                            <Button variant="outline" onClick={() => setShowSetupModal(false)}>
                                Cancel
                            </Button>
                            <Button
                                variant="default"
                                onClick={handleConfirm2FA}
                                disabled={twoFALoading || verificationCode.length !== 6}
                            >
                                {twoFALoading ? 'Verifying...' : 'Enable 2FA'}
                            </Button>
                        </div>
                </Modal>
            )}

            {/* Disable 2FA Modal */}
            {showDisableModal && (
                <Modal open={true} onClose={() => setShowDisableModal(false)} title="Disable Two-Factor Authentication">
                            <div className="warning-box">
                                <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" fill="none" strokeWidth="2">
                                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                                    <line x1="12" y1="9" x2="12" y2="13"/>
                                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                                </svg>
                                <p>Disabling 2FA will make your account less secure. You will only need your password to log in.</p>
                            </div>
                            <div className="form-group">
                                <Label>Enter a verification code or backup code to disable 2FA:</Label>
                                <Input
                                    type="text"
                                    value={verificationCode}
                                    onChange={(e) => setVerificationCode(e.target.value)}
                                    placeholder="Code from authenticator or backup code"
                                    autoFocus
                                />
                                {twoFAError && <p className="error-text">{twoFAError}</p>}
                            </div>
                        <div className="modal-footer">
                            <Button variant="outline" onClick={() => setShowDisableModal(false)}>
                                Cancel
                            </Button>
                            <Button
                                variant="destructive"
                                onClick={handleDisable2FA}
                                disabled={twoFALoading || !verificationCode}
                            >
                                {twoFALoading ? 'Disabling...' : 'Disable 2FA'}
                            </Button>
                        </div>
                </Modal>
            )}

            {/* Backup Codes Modal */}
            {showBackupCodesModal && (
                <Modal open={true} onClose={() => setShowBackupCodesModal(false)} title={backupCodes.length > 0 ? 'Your Backup Codes' : 'Regenerate Backup Codes'} size="md">
                            {backupCodes.length > 0 ? (
                                <>
                                    <div className="warning-box">
                                        <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" fill="none" strokeWidth="2">
                                            <circle cx="12" cy="12" r="10"/>
                                            <line x1="12" y1="8" x2="12" y2="12"/>
                                            <line x1="12" y1="16" x2="12.01" y2="16"/>
                                        </svg>
                                        <p>Save these backup codes in a secure location. They will not be shown again. Each code can only be used once.</p>
                                    </div>
                                    <div className="backup-codes-grid">
                                        {backupCodes.map((code, index) => (
                                            <code key={index} className="backup-code">{code}</code>
                                        ))}
                                    </div>
                                    <div className="backup-codes-actions">
                                        <Button variant="outline" onClick={downloadBackupCodes}>
                                            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                                            </svg>
                                            Download
                                        </Button>
                                        <Button variant="outline" onClick={copyBackupCodes}>
                                            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                                            </svg>
                                            Copy
                                        </Button>
                                    </div>
                                </>
                            ) : (
                                <>
                                    <p>Enter a code from your authenticator app to generate new backup codes. This will invalidate all existing backup codes.</p>
                                    <div className="form-group">
                                        <Label>Verification Code</Label>
                                        <Input
                                            type="text"
                                            value={verificationCode}
                                            onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                                            placeholder="000000"
                                            autoFocus
                                        />
                                        {twoFAError && <p className="error-text">{twoFAError}</p>}
                                    </div>
                                </>
                            )}
                        <div className="modal-footer">
                            <Button variant="outline" onClick={() => {
                                setShowBackupCodesModal(false);
                                setBackupCodes([]);
                                setVerificationCode('');
                            }}>
                                {backupCodes.length > 0 ? 'Done' : 'Cancel'}
                            </Button>
                            {backupCodes.length === 0 && (
                                <Button
                                    variant="default"
                                    onClick={handleRegenerateBackupCodes}
                                    disabled={twoFALoading || verificationCode.length !== 6}
                                >
                                    {twoFALoading ? 'Generating...' : 'Generate New Codes'}
                                </Button>
                            )}
                        </div>
                </Modal>
            )}
        </div>
    );
};

export default SecuritySettingsTab;
