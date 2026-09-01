import {
    useCallback,
    useEffect,
    useMemo,
    useState,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { localizeWalkthroughs } from '../data/walkthroughs';
import api from '../services/api';
import { useContributions } from '../plugins/contributions';
import {
    EMPTY_WALKTHROUGH_STATE,
    completeWalkthroughStepState,
    dismissWalkthroughState,
    getWalkthroughProgress,
    normalizeWalkthroughState,
    routeMatches,
    startWalkthroughState,
} from '../services/walkthroughState';
import {
    buildWalkthroughRegistry,
    normalizeWalkthroughDefinition,
    WALKTHROUGH_LIBRARY_EVENT,
    WALKTHROUGH_SIGNAL_EVENT,
} from '../services/walkthroughRegistry';
import { useAuth } from './AuthContext';
import usePolling from '../hooks/usePolling';
import { WalkthroughContext } from './walkthroughContextValue';


function storageKey(userId) {
    return `serverkit.walkthroughs.v1.${userId || 'anonymous'}`;
}

function readCachedState(userId, walkthroughIds) {
    try {
        return normalizeWalkthroughState(
            JSON.parse(localStorage.getItem(storageKey(userId)) || 'null'),
            walkthroughIds,
        );
    } catch {
        return { ...EMPTY_WALKTHROUGH_STATE };
    }
}

export function WalkthroughProvider({ children }) {
    const { t } = useTranslation();
    const { user, hasPermission } = useAuth();
    const location = useLocation();
    const navigate = useNavigate();
    const contributions = useContributions();
    const [customDefinitions, setCustomDefinitions] = useState([]);
    const [previewDefinition, setPreviewDefinition] = useState(null);
    const [pendingPreviewId, setPendingPreviewId] = useState(null);
    const [customLoaded, setCustomLoaded] = useState(false);
    const [state, setState] = useState({ ...EMPTY_WALKTHROUGH_STATE });
    const [hydrated, setHydrated] = useState(false);
    const [open, setOpen] = useState(false);

    const localizedCore = useMemo(() => localizeWalkthroughs(t), [t]);
    const registry = useMemo(() => buildWalkthroughRegistry({
        core: localizedCore,
        contributed: contributions.walkthroughs,
        custom: previewDefinition
            ? [previewDefinition, ...customDefinitions]
            : customDefinitions,
        t,
    }), [contributions.walkthroughs, customDefinitions, localizedCore, previewDefinition, t]);
    const walkthroughIds = useMemo(
        () => registry.walkthroughs.map((item) => item.id),
        [registry.walkthroughs],
    );
    const walkthroughIdsKey = walkthroughIds.join('|');
    const registryReady = Boolean(contributions.__ready && customLoaded);
    const availableWalkthroughs = useMemo(() => registry.walkthroughs.filter((item) => {
        const required = item.permissions || (item.permission ? [item.permission] : []);
        return required.every((permission) => (
            hasPermission(permission.feature, permission.level)
        ));
    }), [hasPermission, registry.walkthroughs]);

    const activeWalkthrough = registry.byId[state.active_id] || null;
    const activeProgress = activeWalkthrough
        ? getWalkthroughProgress(state, activeWalkthrough)
        : null;
    const currentStep = activeProgress?.currentStep || null;

    useEffect(() => {
        if (!pendingPreviewId || !registry.byId[pendingPreviewId]) return;
        setState((previous) => startWalkthroughState(previous, pendingPreviewId));
        setOpen(true);
        setPendingPreviewId(null);
    }, [pendingPreviewId, registry.byId]);

    const refreshDefinitions = useCallback(() => {
        if (!user?.id) {
            setCustomDefinitions([]);
            setCustomLoaded(true);
            return Promise.resolve([]);
        }
        return api.getWalkthroughDefinitions()
            .then((response) => {
                const definitions = Array.isArray(response?.definitions)
                    ? response.definitions
                    : [];
                setCustomDefinitions(definitions);
                return definitions;
            })
            .catch(() => {
                setCustomDefinitions([]);
                return [];
            })
            .finally(() => setCustomLoaded(true));
    }, [user?.id]);

    useEffect(() => {
        setCustomLoaded(false);
        refreshDefinitions();
        window.addEventListener(WALKTHROUGH_LIBRARY_EVENT, refreshDefinitions);
        return () => window.removeEventListener(WALKTHROUGH_LIBRARY_EVENT, refreshDefinitions);
    }, [refreshDefinitions]);

    useEffect(() => {
        if (!user?.id || !registryReady) return undefined;
        let cancelled = false;
        const currentIds = walkthroughIdsKey ? walkthroughIdsKey.split('|') : [];
        setState(readCachedState(user.id, currentIds));
        setHydrated(false);
        api.getWalkthroughState()
            .then((response) => {
                if (!cancelled) {
                    setState(normalizeWalkthroughState(response.state, currentIds));
                }
            })
            .catch(() => { /* local cache remains the offline fallback */ })
            .finally(() => { if (!cancelled) setHydrated(true); });
        return () => { cancelled = true; };
    }, [registryReady, user?.id, walkthroughIdsKey]);

    useEffect(() => {
        if (!hydrated || !user?.id) return undefined;
        try { localStorage.setItem(storageKey(user.id), JSON.stringify(state)); } catch { /* ignore */ }
        const timer = setTimeout(() => {
            api.updateWalkthroughState(state).catch(() => { /* local progress is retained */ });
        }, 250);
        return () => clearTimeout(timer);
    }, [hydrated, state, user?.id]);

    const start = useCallback((walkthroughId) => {
        if (!registry.byId[walkthroughId]) return;
        setState((previous) => startWalkthroughState(previous, walkthroughId));
        setOpen(true);
    }, [registry.byId]);

    const completeStep = useCallback((walkthroughId, stepId) => {
        const walkthrough = registry.byId[walkthroughId];
        if (!walkthrough) return;
        setState((previous) => completeWalkthroughStepState(
            previous,
            walkthroughId,
            stepId,
            walkthrough.steps.map((step) => step.id),
        ));
    }, [registry.byId]);

    const dismiss = useCallback((walkthroughId) => {
        setState((previous) => dismissWalkthroughState(previous, walkthroughId));
    }, []);

    const preview = useCallback((definition) => {
        const normalized = normalizeWalkthroughDefinition(definition, { source: 'custom', t });
        if (!normalized) return false;
        setPreviewDefinition(definition);
        setPendingPreviewId(normalized.id);
        return true;
    }, [t]);

    useEffect(() => {
        if (!activeWalkthrough || !currentStep?.route) return;
        if (routeMatches(location.pathname, currentStep.route)) {
            completeStep(activeWalkthrough.id, currentStep.id);
        }
    }, [activeWalkthrough, completeStep, currentStep, location.pathname]);

    useEffect(() => {
        const handleSignal = (event) => {
            if (!activeWalkthrough) return;
            if (event.detail?.type === 'two-factor-enabled'
                    && activeWalkthrough.id === 'enable-two-factor') {
                activeWalkthrough.steps.forEach((step) => (
                    completeStep(activeWalkthrough.id, step.id)
                ));
                return;
            }
            // Only the step the operator is actually on may advance. These
            // signals are ordinary product events, so a later step's signal
            // can fire while an earlier step is still current -- matching
            // against the whole list would complete that step out of order
            // and silently skip everything between. Mirrors the route effect
            // above, which is already scoped to currentStep.
            if (currentStep?.signal && currentStep.signal === event.detail?.type) {
                completeStep(activeWalkthrough.id, currentStep.id);
            }
        };
        window.addEventListener(WALKTHROUGH_SIGNAL_EVENT, handleSignal);
        return () => window.removeEventListener(WALKTHROUGH_SIGNAL_EVENT, handleSignal);
    }, [activeWalkthrough, completeStep, currentStep]);

    const checkCurrent = useCallback(async () => {
        if (!activeWalkthrough) return false;
        if (currentStep?.check === 'two-factor-enabled') {
            const status = await api.get2FAStatus();
            if (status?.enabled) {
                activeWalkthrough.steps.forEach((step) => (
                    completeStep(activeWalkthrough.id, step.id)
                ));
                return true;
            }
        }
        return false;
    }, [activeWalkthrough, completeStep, currentStep?.check]);

    usePolling(
        () => checkCurrent(),
        5000,
        { enabled: currentStep?.check === 'two-factor-enabled' },
    );

    useEffect(() => {
        if (!open || !currentStep?.target) return undefined;
        let attempts = 0;
        let target;
        const findTarget = () => {
            target = document.querySelector(currentStep.target);
            if (target) {
                target.classList.add('is-walkthrough-target');
                if (currentStep.completeWhenTargetVisible && activeWalkthrough) {
                    completeStep(activeWalkthrough.id, currentStep.id);
                }
                return;
            }
            if (attempts++ < 20) timer = setTimeout(findTarget, 100);
        };
        let timer = setTimeout(findTarget, 50);
        return () => {
            clearTimeout(timer);
            target?.classList.remove('is-walkthrough-target');
        };
    }, [activeWalkthrough, completeStep, currentStep, location.pathname, open]);

    const goToCurrent = useCallback(() => {
        if (currentStep?.path) navigate(currentStep.path);
        setOpen(true);
    }, [currentStep, navigate]);

    const value = useMemo(() => ({
        state,
        open,
        setOpen,
        walkthroughs: availableWalkthroughs,
        activeWalkthrough,
        activeProgress,
        currentStep,
        start,
        dismiss,
        completeStep,
        checkCurrent,
        goToCurrent,
        refreshDefinitions,
        preview,
    }), [
        activeProgress,
        activeWalkthrough,
        availableWalkthroughs,
        checkCurrent,
        completeStep,
        currentStep,
        dismiss,
        goToCurrent,
        open,
        preview,
        refreshDefinitions,
        start,
        state,
    ]);

    return <WalkthroughContext.Provider value={value}>{children}</WalkthroughContext.Provider>;
}
