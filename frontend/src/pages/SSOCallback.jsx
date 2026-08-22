import { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api from '../services/api';
import { consumeRedirect } from '../utils/redirectAfterLogin';
import { Loader } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTranslation } from 'react-i18next';

const SSOCallback = () => {
    const { t } = useTranslation();
    const { provider } = useParams();
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const { setUser } = useAuth();
    const [error, setError] = useState('');

    useEffect(() => {
        const code = searchParams.get('code');
        const state = searchParams.get('state');
        const redirectUri = `${window.location.origin}/login/callback/${provider}`;

        if (!code || !state) {
            setError('Missing authorization code or state parameter.');
            return;
        }

        completeAuth(code, state, redirectUri);
    }, []);

    async function completeAuth(code, state, redirectUri) {
        try {
            const response = await api.completeSSOAuth(provider, code, state, redirectUri);

            if (response.requires_2fa) {
                // Redirect to login page with 2FA state
                navigate('/login', {
                    state: {
                        requires2FA: true,
                        tempToken: response.temp_token,
                    }
                });
                return;
            }

            setUser(response.user);
            // sessionStorage survived the round trip to the identity provider;
            // react-router state would not have.
            navigate(consumeRedirect());
        } catch (err) {
            setError(err.message || 'SSO authentication failed');
        }
    }

    if (error) {
        return (
            <div className="auth-container">
                <div className="auth-card">
                    <div className="auth-header">
                        <h1>{t('app.sSOCallback.authenticationFailed', 'Authentication Failed')}</h1>
                        <p className="error-message">{error}</p>
                    </div>
                    <Button asChild className="btn-full">
                        <Link to="/login">{t('app.sSOCallback.backToLogin', 'Back to Login')}</Link>
                    </Button>
                </div>
            </div>
        );
    }

    return (
        <div className="auth-container">
            <div className="auth-card">
                <div className="auth-header">
                    <div className="sso-loading">
                        <Loader size={32} className="spinning" />
                    </div>
                    <h1>{t('app.sSOCallback.signingYouIn', 'Signing you in…')}</h1>
                    <p>{t('app.sSOCallback.completingAuthenticationWith', 'Completing authentication with')} {provider}</p>
                </div>
            </div>
        </div>
    );
};

export default SSOCallback;
