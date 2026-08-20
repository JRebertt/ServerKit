import { useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useLocale } from '../contexts/LocaleContext';
import api from '../services/api';

// Bridges auth -> locale (plan 79 B1/B2). LocaleProvider sits above
// AuthProvider so the sign-in screen is translated before anyone is signed in,
// which means it cannot read auth state itself. This renders inside
// AuthProvider and does two things:
//
//   1. Pushes the panel default (pre-auth, from /auth/setup-status) and the
//      signed-in user's stored language into the provider.
//   2. Registers the writer that persists an explicit choice to the user row,
//      so the preference survives a different browser -- the gap in most
//      implementations of this, which only call changeLanguage().
//
// Renders nothing.
const LocaleSync = () => {
    const { user, isAuthenticated, setupStatus } = useAuth();
    const { applyServerPreferences, registerPersist } = useLocale();

    const panelDefault = setupStatus?.defaultLanguage;
    const checked = setupStatus?.checked;
    const userLanguage = user?.language ?? null;

    useEffect(() => {
        // Wait for the pre-auth probe to land, otherwise the panel default is
        // always undefined and the browser language wins a race it should lose.
        if (!checked) return;
        applyServerPreferences({ userLanguage, panelDefault });
    }, [checked, userLanguage, panelDefault, applyServerPreferences]);

    useEffect(() => {
        if (!isAuthenticated) return undefined;
        return registerPersist((code) => {
            api.updateCurrentUser({ language: code }).catch(() => {
                // The choice is already applied and cached locally; failing to
                // record it server-side must not undo it in front of the user.
            });
        });
    }, [isAuthenticated, registerPersist]);

    return null;
};

export default LocaleSync;
