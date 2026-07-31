import { createContext, useContext, useState, useEffect } from 'react';
import api from '../services/api';
import { useAuth } from './AuthContext';

const ResourceTierContext = createContext(null);

export function ResourceTierProvider({ children }) {
    const { isAuthenticated, isAdmin } = useAuth();
    const [tierInfo, setTierInfo] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (isAuthenticated && isAdmin) {
            fetchTierInfo();
        } else {
            setLoading(false);
        }
    }, [isAuthenticated, isAdmin]);

    async function fetchTierInfo(forceRefresh = false) {
        try {
            setLoading(true);
            setError(null);
            // /system/capacity is a superset of /system/resource-tier: same
            // specs and tier, plus live headroom and the install profile.
            const endpoint = forceRefresh
                ? '/system/capacity?refresh=true'
                : '/system/capacity';
            const data = await api.request(endpoint);
            setTierInfo(data);
        } catch (err) {
            console.error('Failed to fetch server capacity:', err);
            setError(err.message || 'Failed to fetch server capacity');
        } finally {
            setLoading(false);
        }
    }

    async function refresh() {
        return fetchTierInfo(true);
    }

    const value = {
        tier: tierInfo?.tier || null,
        specs: tierInfo?.specs || null,
        features: tierInfo?.features || {},
        cached: tierInfo?.cached || false,
        loading,
        error,
        refresh,

        // Live capacity — the number that actually moves as apps get deployed.
        headroom: tierInfo?.headroom || null,

        // What this install provisioned, and what it can do right now.
        profile: tierInfo?.profile || null,
        profiles: tierInfo?.profiles || {},
        capabilities: tierInfo?.capabilities || {},
        recommendedProfile: tierInfo?.recommended_profile || null,
        profileDrift: tierInfo?.drift || [],
        canHostApps: tierInfo?.capabilities?.can_host_apps ?? true,

        // Creation is never blocked on resources — this reports whether the
        // server comfortably meets the recommendation so the UI can warn at
        // the point of action instead of hiding the action.
        isWordPressAdvised: tierInfo?.features?.wordpress_create_advised ?? true,
        isLiteTier: tierInfo?.tier === 'lite',
        isStandardTier: tierInfo?.tier === 'standard',
        isPerformanceTier: tierInfo?.tier === 'performance',
    };

    return (
        <ResourceTierContext.Provider value={value}>
            {children}
        </ResourceTierContext.Provider>
    );
}

export function useResourceTier() {
    const context = useContext(ResourceTierContext);
    if (!context) {
        throw new Error('useResourceTier must be used within a ResourceTierProvider');
    }
    return context;
}
