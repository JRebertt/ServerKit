import { useState, useEffect } from 'react';
import { ShieldCheck, Copy, Download, AlertTriangle, Check, Loader } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import api from '../../services/api';

// Enrolment is a three-beat flow. Offer is the default so someone who just
// wants a dashboard is one click from moving on — 2FA is offered here because
// this is the only moment we know the operator is at a keyboard with their
// phone, not because it is mandatory.
const STAGE_OFFER = 'offer';
const STAGE_ENROLL = 'enroll';
const STAGE_CODES = 'codes';
const STAGE_ALREADY = 'already';

const CODE_LENGTH = 6;

const SetupStepSecurity = ({ onComplete }) => {
    const [stage, setStage] = useState(STAGE_OFFER);
    const [setupData, setSetupData] = useState(null);
    const [code, setCode] = useState('');
    const [backupCodes, setBackupCodes] = useState([]);
    const [savedCodes, setSavedCodes] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    // Stepping back to Capacity and forward again re-mounts this step, but the
    // enrolment already landed server-side — re-offering it would just 400.
    useEffect(() => {
        let active = true;
        api.get2FAStatus()
            .then((status) => {
                if (active && status?.enabled) setStage(STAGE_ALREADY);
            })
            .catch(() => {
                // Status is a convenience; the offer path still works without it.
            });
        return () => {
            active = false;
        };
    }, []);

    async function handleEnable() {
        setBusy(true);
        setError('');
        try {
            const data = await api.initiate2FASetup();
            setSetupData(data);
            setStage(STAGE_ENROLL);
        } catch (err) {
            setError(err.message || 'Could not start two-factor setup.');
        } finally {
            setBusy(false);
        }
    }

    async function handleConfirm() {
        if (code.length !== CODE_LENGTH) {
            setError(`Enter the ${CODE_LENGTH}-digit code from your app.`);
            return;
        }
        setBusy(true);
        setError('');
        try {
            const result = await api.confirm2FASetup(code);
            setBackupCodes(result.backup_codes || []);
            setStage(STAGE_CODES);
        } catch (err) {
            setError(err.message || 'That code did not match. Try the next one.');
        } finally {
            setBusy(false);
        }
    }

    function copyCodes() {
        navigator.clipboard?.writeText(backupCodes.join('\n'));
        setSavedCodes(true);
    }

    function downloadCodes() {
        const body = [
            'ServerKit backup codes',
            '',
            'Each code works once, in place of your authenticator app.',
            'Store them somewhere you can reach without this server.',
            '',
            ...backupCodes,
        ].join('\n');

        const url = URL.createObjectURL(new Blob([body], { type: 'text/plain' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = 'serverkit-backup-codes.txt';
        link.click();
        URL.revokeObjectURL(url);
        setSavedCodes(true);
    }

    if (stage === STAGE_ALREADY) {
        return (
            <div className="wizard-step">
                <h2 className="wizard-step-title">Two-factor is on</h2>
                <p className="wizard-step-description">
                    This account already has two-factor authentication enabled. You
                    can regenerate backup codes or turn it off from Settings.
                </p>

                <div className="security-offer">
                    <div className="security-offer__icon">
                        <ShieldCheck size={28} />
                    </div>
                    <div className="security-offer__body">
                        <div className="security-offer__title">
                            Two-factor authentication active
                        </div>
                        <p className="security-offer__desc">
                            You&apos;ll be asked for a code from your authenticator
                            app the next time you sign in.
                        </p>
                    </div>
                </div>

                <div className="wizard-nav" style={{ borderTop: 'none', marginTop: 0, paddingTop: 0 }}>
                    <button
                        type="button"
                        className="btn-wizard-next"
                        onClick={() => onComplete(true)}
                    >
                        Continue
                    </button>
                </div>
            </div>
        );
    }

    if (stage === STAGE_OFFER) {
        return (
            <div className="wizard-step">
                <h2 className="wizard-step-title">Protect this account</h2>
                <p className="wizard-step-description">
                    This panel can restart services, open firewall ports and read your
                    databases. Two-factor authentication means a stolen password alone
                    is not enough to do any of that.
                </p>

                <div className="security-offer">
                    <div className="security-offer__icon">
                        <ShieldCheck size={28} />
                    </div>
                    <div className="security-offer__body">
                        <div className="security-offer__title">
                            Two-factor authentication
                        </div>
                        <p className="security-offer__desc">
                            Takes about thirty seconds with any authenticator app —
                            1Password, Aegis, Google Authenticator. You&apos;ll get
                            backup codes in case you lose the device.
                        </p>
                    </div>
                </div>

                {error && (
                    <div className="tier-warning">
                        <AlertTriangle size={20} className="tier-warning-icon" />
                        <div className="tier-warning-text">{error}</div>
                    </div>
                )}

                <div className="wizard-nav" style={{ borderTop: 'none', marginTop: 0, paddingTop: 0 }}>
                    <Button variant="ghost" onClick={() => onComplete(false)} disabled={busy}>
                        Skip for now
                    </Button>
                    <button
                        type="button"
                        className="btn-wizard-next"
                        onClick={handleEnable}
                        disabled={busy}
                    >
                        {busy ? 'Starting...' : 'Enable two-factor'}
                    </button>
                </div>
            </div>
        );
    }

    if (stage === STAGE_ENROLL) {
        return (
            <div className="wizard-step">
                <h2 className="wizard-step-title">Scan this code</h2>
                <p className="wizard-step-description">
                    Open your authenticator app, scan the QR code, then enter the
                    six-digit code it shows.
                </p>

                <div className="security-enroll">
                    {setupData?.qr_code ? (
                        <img
                            src={setupData.qr_code}
                            alt="Two-factor QR code"
                            className="security-enroll__qr"
                        />
                    ) : (
                        <div className="security-enroll__qr security-enroll__qr--empty">
                            <Loader size={20} className="spin" />
                        </div>
                    )}

                    <div className="security-enroll__manual">
                        <div className="security-enroll__manual-label">
                            Can&apos;t scan? Enter this key instead:
                        </div>
                        <code className="security-enroll__secret">{setupData?.secret}</code>
                    </div>
                </div>

                <div className="security-enroll__verify">
                    <Input
                        value={code}
                        onChange={(e) =>
                            setCode(e.target.value.replace(/\D/g, '').slice(0, CODE_LENGTH))
                        }
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') handleConfirm();
                        }}
                        placeholder="000000"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        className="security-enroll__input"
                        aria-label="Six-digit verification code"
                    />
                </div>

                {error && (
                    <div className="tier-warning">
                        <AlertTriangle size={20} className="tier-warning-icon" />
                        <div className="tier-warning-text">{error}</div>
                    </div>
                )}

                <div className="wizard-nav" style={{ borderTop: 'none', marginTop: 0, paddingTop: 0 }}>
                    <Button variant="ghost" onClick={() => onComplete(false)} disabled={busy}>
                        Skip for now
                    </Button>
                    <button
                        type="button"
                        className="btn-wizard-next"
                        onClick={handleConfirm}
                        disabled={busy || code.length !== CODE_LENGTH}
                    >
                        {busy ? 'Verifying...' : 'Verify and enable'}
                    </button>
                </div>
            </div>
        );
    }

    // STAGE_CODES — shown exactly once. The backend will not reissue these.
    return (
        <div className="wizard-step">
            <h2 className="wizard-step-title">Save your backup codes</h2>
            <p className="wizard-step-description">
                These are shown once and never again. Each works a single time if you
                lose your authenticator — keep them somewhere that does not depend on
                this server being reachable.
            </p>

            <div className="security-codes">
                {backupCodes.map((backupCode) => (
                    <code key={backupCode} className="security-codes__item">
                        {backupCode}
                    </code>
                ))}
            </div>

            <div className="security-codes__actions">
                <Button variant="outline" onClick={copyCodes}>
                    <Copy size={15} />
                    Copy
                </Button>
                <Button variant="outline" onClick={downloadCodes}>
                    <Download size={15} />
                    Download
                </Button>
                {savedCodes && (
                    <span className="security-codes__saved">
                        <Check size={15} />
                        Saved
                    </span>
                )}
            </div>

            <div className="wizard-nav" style={{ borderTop: 'none', marginTop: 0, paddingTop: 0 }}>
                <button
                    type="button"
                    className="btn-wizard-next"
                    onClick={() => onComplete(true)}
                >
                    {savedCodes ? 'Continue' : 'I have saved these'}
                </button>
            </div>
        </div>
    );
};

export default SetupStepSecurity;
