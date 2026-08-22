import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { ShieldAlert, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Per-user "secure your account" nudge (plan 22 #12). Shows when the requesting
// user has no second factor, deep-linking to Settings → Security where the full
// guided enrolment lives (passkey-first, then TOTP with its QR). Dismissible;
// the dismissal is persisted to the account's `setup_snoozes` (plan 29 #8) so it
// follows the user across browsers, with localStorage kept only as a fast cache
// so the nudge doesn't flash before the account fetch resolves.

const DISMISS_KEY = 'account_security_nudge_dismissed';
const ITEM_KEY = 'setup.account_security';
const SNOOZE_DAYS = 30;

const AccountSecurityNudge = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [item, setItem] = useState(null);
    const [dismissed, setDismissed] = useState(() => {
        try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch { return false; }
    });

    useEffect(() => {
        if (dismissed) return;
        let cancelled = false;
        api.getAccountSecurity()
            .then((res) => {
                if (cancelled) return;
                const acct = (res.items || []).find((c) => c.key === ITEM_KEY);
                // The account row is the source of truth: a server-side snooze
                // (set from any browser) means "dismissed" here too.
                if (acct && acct.snoozed) {
                    try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* ignore */ }
                    setDismissed(true);
                    return;
                }
                if (acct && acct.status !== 'ok') setItem(acct);
            })
            .catch(() => { /* stay quiet */ });
        return () => { cancelled = true; };
    }, [dismissed]);

    if (dismissed || !item) return null;

    const dismiss = () => {
        // Cache locally for an instant hide, then persist to the account so the
        // dismissal survives across browsers/devices. Best-effort: a failed
        // persist still hides it for this session.
        try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* ignore */ }
        setDismissed(true);
        api.snoozeSetupItem(ITEM_KEY, SNOOZE_DAYS).catch(() => { /* keep the local hide */ });
    };

    return (
        <div className="account-security-nudge" role="status">
            <ShieldAlert size={18} className="account-security-nudge__icon" />
            <div className="account-security-nudge__body">
                <span className="account-security-nudge__title">{t('app.accountSecurityNudge.secureYourAccount', 'Secure your account')}</span>
                <span className="account-security-nudge__detail">{item.detail}</span>
            </div>
            <Button size="sm" onClick={() => navigate(item.fix?.to || '/settings/security')}>
                {t('app.accountSecurityNudge.addAPasskeyOr2fa', 'Add a passkey or 2FA')}
            </Button>
            <button type="button" className="account-security-nudge__close" onClick={dismiss} aria-label={t('common.actions.dismiss', 'Dismiss')}>
                <X size={16} />
            </button>
        </div>
    );
};

export default AccountSecurityNudge;
