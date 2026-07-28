import { useState, useEffect } from 'react';
import api from '../services/api';
import { useAuth } from '../contexts/AuthContext';

// Shared, app-wide "developer mode" flag — the gate for developer-only surfaces
// (currently the Test Sandbox). True when either:
//
//   * this is a local `npm run dev` build (import.meta.env.DEV), or
//   * an admin has turned on Site Settings → Developer mode (dev_mode).
//
// Cached at module scope like useModules() so the sidebar item and the route
// guard read one value and can never disagree — a visible nav entry that
// redirects to the dashboard is worse than no entry at all.
//
// /admin/settings is admin-gated, so only admins are asked; everyone else stays
// on the `false` default rather than eating a 403 per session.

let cache = null;        // last-fetched dev_mode boolean
let inflight = null;     // de-dupes concurrent initial fetches
const listeners = new Set();

function notify() {
    for (const listener of listeners) listener(cache);
}

async function fetchDevMode(force = false) {
    if (cache !== null && !force) return cache;
    if (inflight && !force) return inflight;
    inflight = api.getSystemSettings()
        .then((data) => {
            cache = !!data?.dev_mode;
            notify();
            return cache;
        })
        .catch(() => {
            cache = cache ?? false;
            return cache;
        })
        .finally(() => { inflight = null; });
    return inflight;
}

// Let Settings broadcast a toggle without a reload.
export function refreshDevMode() {
    return fetchDevMode(true);
}

// Returns the resolved flag. `resolved` is false only while an admin's first
// dev_mode fetch is still in flight — route guards must wait for it, or a
// deep link into a dev-only page would bounce before the answer arrives.
export function useDevMode({ withStatus = false } = {}) {
    const { isAdmin } = useAuth();
    const [systemDevMode, setSystemDevMode] = useState(cache ?? false);
    const [loaded, setLoaded] = useState(cache !== null);

    useEffect(() => {
        if (!isAdmin) return undefined;
        const listener = (v) => { setSystemDevMode(!!v); setLoaded(true); };
        listeners.add(listener);
        fetchDevMode().then(() => setLoaded(true));
        return () => { listeners.delete(listener); };
    }, [isAdmin]);

    // A local dev build short-circuits: nothing to wait for.
    const devMode = import.meta.env.DEV || (isAdmin && systemDevMode);
    const resolved = import.meta.env.DEV || !isAdmin || loaded;

    return withStatus ? { devMode, resolved } : devMode;
}

export default useDevMode;
