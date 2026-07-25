import { createContext, useContext, useState, useEffect } from 'react';
import api from '../services/api';
import { presetForUseCases } from '../components/sidebarItems';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [setupStatus, setSetupStatus] = useState({
        needsSetup: false,
        registrationEnabled: false,
        ssoProviders: [],
        passwordLoginEnabled: true,
        // Build-time default until the pre-auth fetch resolves (avoids a title flash
        // for forks that brand at build time via VITE_PANEL_TITLE).
        panelTitle: import.meta.env.VITE_PANEL_TITLE || 'ServerKit',
        publicTitle: 'Control Panel',
        loginLayout: 'centered',
        needsMigration: false,
        migrationInfo: null,
        checked: false
    });

    useEffect(() => {
        checkSetupStatus();
    }, []);

    useEffect(() => {
        const handleAuthExpired = () => setUser(null);
        window.addEventListener('serverkit:auth-expired', handleAuthExpired);
        return () => window.removeEventListener('serverkit:auth-expired', handleAuthExpired);
    }, []);

    async function checkSetupStatus(retries = 3) {
        try {
            const status = await api.getSetupStatus();
            setSetupStatus({
                needsSetup: status.needs_setup,
                registrationEnabled: status.registration_enabled,
                ssoProviders: status.sso_providers || [],
                passwordLoginEnabled: status.password_login_enabled !== false,
                panelTitle: status.panel_title || import.meta.env.VITE_PANEL_TITLE || 'ServerKit',
                publicTitle: status.public_title || 'Control Panel',
                loginLayout: status.login_layout || 'centered',
                needsMigration: status.needs_migration || false,
                migrationInfo: status.migration_info || null,
                checked: true
            });

            // Always check auth — user may be mid-onboarding wizard with valid session
            await checkAuth();
        } catch (error) {
            console.error('Setup status check failed:', error);
            // Backend may not be ready yet — retry before falling back
            if (retries > 0) {
                await new Promise(r => setTimeout(r, 2000));
                return checkSetupStatus(retries - 1);
            }
            // Exhausted retries — assume fresh install so user isn't locked out
            setSetupStatus(prev => ({
                ...prev,
                needsSetup: true,
                registrationEnabled: true,
                checked: true
            }));
            await checkAuth();
        }
    }

    async function checkAuth() {
        const token = localStorage.getItem('access_token');
        if (token) {
            try {
                const data = await api.getCurrentUser();
                setUser(data.user);
            } catch (error) {
                if (error.status !== 401) {
                    console.error('Auth check failed:', error);
                }
                api.clearTokens();
            }
        }
        setLoading(false);
    }

    async function refreshSetupStatus() {
        try {
            const status = await api.getSetupStatus();
            setSetupStatus({
                needsSetup: status.needs_setup,
                registrationEnabled: status.registration_enabled,
                ssoProviders: status.sso_providers || [],
                passwordLoginEnabled: status.password_login_enabled !== false,
                panelTitle: status.panel_title || import.meta.env.VITE_PANEL_TITLE || 'ServerKit',
                publicTitle: status.public_title || 'Control Panel',
                loginLayout: status.login_layout || 'centered',
                needsMigration: status.needs_migration || false,
                migrationInfo: status.migration_info || null,
                checked: true
            });
        } catch (error) {
            console.error('Failed to refresh setup status:', error);
        }
    }

    async function login(email, password) {
        const data = await api.login(email, password);
        setUser(data.user);
        return data;
    }

    async function register(email, username, password, inviteToken) {
        const data = await api.register(email, username, password, inviteToken);
        setUser(data.user);
        return data;
    }

    async function completeOnboarding(useCases, installedExtensions = [], sidebarPreset = null) {
        await api.completeOnboarding(useCases, installedExtensions);
        // Tailor the initial sidebar so a fresh install opens focused instead of
        // showing every item. The Summary step passes an explicit profile (which
        // it pre-selects from the use cases and the user may override); fall back
        // to deriving it here for any caller that doesn't. Best-effort: if it
        // fails, the sidebar just falls back to the "Recommended" default.
        try {
            const preset = sidebarPreset || presetForUseCases(useCases);
            const sidebar_config = { preset, hiddenItems: [] };
            const res = await api.updateCurrentUser({ sidebar_config });
            if (res?.user) setUser(res.user);
        } catch {
            /* ignore — sidebar preset is a non-critical nicety */
        }
        setSetupStatus(prev => ({
            ...prev,
            needsSetup: false,
            registrationEnabled: false,
            checked: true
        }));
    }

    function logout() {
        api.logout();
        setUser(null);
    }

    async function updateUser(data) {
        const response = await api.updateCurrentUser(data);
        setUser(response.user);
        return response;
    }

    async function refreshUser() {
        const data = await api.getCurrentUser();
        setUser(data.user);
        return data.user;
    }

    function hasPermission(feature, level = 'read') {
        if (!user) return false;
        if (user.role === 'admin') return true;
        const perms = user.permissions || {};
        const featurePerms = perms[feature] || {};
        return !!featurePerms[level];
    }

    const value = {
        user,
        setUser,
        loading,
        login,
        register,
        completeOnboarding,
        logout,
        updateUser,
        refreshUser,
        refreshSetupStatus,
        hasPermission,
        isAuthenticated: !!user,
        isAdmin: user?.role === 'admin',
        isDeveloper: user?.role === 'admin' || user?.role === 'developer',
        isViewer: !!user?.role,
        setupStatus,
        needsSetup: setupStatus.needsSetup,
        needsMigration: setupStatus.needsMigration,
        migrationInfo: setupStatus.migrationInfo,
        registrationEnabled: setupStatus.registrationEnabled,
        ssoProviders: setupStatus.ssoProviders,
        passwordLoginEnabled: setupStatus.passwordLoginEnabled,
        panelTitle: setupStatus.panelTitle,
        publicTitle: setupStatus.publicTitle,
        loginLayout: setupStatus.loginLayout,
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}
