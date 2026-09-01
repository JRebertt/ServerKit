import {
    useCallback,
    useEffect,
    useMemo,
    useState,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
    WALKTHROUGHS,
    WALKTHROUGH_BY_ID,
    localizeWalkthroughs,
} from '../data/walkthroughs';
import api from '../services/api';
import {
    EMPTY_WALKTHROUGH_STATE,
    completeWalkthroughStepState,
    dismissWalkthroughState,
    getWalkthroughProgress,
    normalizeWalkthroughState,
    routeMatches,
    startWalkthroughState,
} from '../services/walkthroughState';
import { useAuth } from './AuthContext';
import usePolling from '../hooks/usePolling';
import { WalkthroughContext } from './walkthroughContextValue';


const WALKTHROUGH_IDS = WALKTHROUGHS.map((item) => item.id);

function storageKey(userId) {
    return `serverkit.walkthroughs.v1.${userId || 'anonymous'}`;
}

function readCachedState(userId) {
    try {
        return normalizeWalkthroughState(
            JSON.parse(localStorage.getItem(storageKey(userId)) || 'null'),
            WALKTHROUGH_IDS,
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
    const [state, setState] = useState(() => readCachedState(user?.id));
    const [hydrated, setHydrated] = useState(false);
    const [open, setOpen] = useState(false);

    const localizedWalkthroughs = useMemo(() => localizeWalkthroughs(t), [t]);
    const availableWalkthroughs = useMemo(() => localizedWalkthroughs.filter((item) => {
        const required = item.permissions || (item.permission ? [item.permission] : []);
        return required.every((permission) => (
            hasPermission(permission.feature, permission.level)
        ));
    }), [hasPermission, localizedWalkthroughs]);

    const activeWalkthrough = localizedWalkthroughs.find(
        (walkthrough) => walkthrough.id === state.active_id,
    ) || null;
    const activeProgress = activeWalkthrough
        ? getWalkthroughProgress(state, activeWalkthrough)
        : null;
    const currentStep = activeProgress?.currentStep || null;

    useEffect(() => {
        if (!user?.id) return undefined;
        let cancelled = false;
        setState(readCachedState(user.id));
        setHydrated(false);
        api.getWalkthroughState()
            .then((response) => {
                if (!cancelled) {
                    setState(normalizeWalkthroughState(response.state, WALKTHROUGH_IDS));
                }
            })
            .catch(() => { /* local cache remains the offline fallback */ })
            .finally(() => { if (!cancelled) setHydrated(true); });
        return () => { cancelled = true; };
    }, [user?.id]);

    useEffect(() => {
        if (!hydrated || !user?.id) return undefined;
        try { localStorage.setItem(storageKey(user.id), JSON.stringify(state)); } catch { /* ignore */ }
        const timer = setTimeout(() => {
            api.updateWalkthroughState(state).catch(() => { /* local progress is retained */ });
        }, 250);
        return () => clearTimeout(timer);
    }, [hydrated, state, user?.id]);

    const start = useCallback((walkthroughId) => {
        if (!WALKTHROUGH_BY_ID[walkthroughId]) return;
        setState((previous) => startWalkthroughState(previous, walkthroughId));
        setOpen(true);
    }, []);

    const completeStep = useCallback((walkthroughId, stepId) => {
        const walkthrough = WALKTHROUGH_BY_ID[walkthroughId];
        if (!walkthrough) return;
        setState((previous) => completeWalkthroughStepState(
            previous,
            walkthroughId,
            stepId,
            walkthrough.steps.map((step) => step.id),
        ));
    }, []);

    const dismiss = useCallback((walkthroughId) => {
        setState((previous) => dismissWalkthroughState(previous, walkthroughId));
    }, []);

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
            const signaledStep = activeWalkthrough.steps.find(
                (step) => step.signal === event.detail?.type,
            );
            if (signaledStep) completeStep(activeWalkthrough.id, signaledStep.id);
        };
        window.addEventListener('serverkit:walkthrough-signal', handleSignal);
        return () => window.removeEventListener('serverkit:walkthrough-signal', handleSignal);
    }, [activeWalkthrough, completeStep, currentStep]);

    const checkCurrent = useCallback(async () => {
        if (!activeWalkthrough) return false;
        if (activeWalkthrough.id === 'enable-two-factor') {
            const status = await api.get2FAStatus();
            if (status?.enabled) {
                activeWalkthrough.steps.forEach((step) => (
                    completeStep(activeWalkthrough.id, step.id)
                ));
                return true;
            }
        }
        return false;
    }, [activeWalkthrough, completeStep]);

    usePolling(
        () => checkCurrent(),
        5000,
        { enabled: activeWalkthrough?.id === 'enable-two-factor' },
    );

    useEffect(() => {
        if (!open || !currentStep?.target) return undefined;
        let attempts = 0;
        let target;
        const findTarget = () => {
            target = document.querySelector(currentStep.target);
            if (target) {
                target.classList.add('is-walkthrough-target');
                return;
            }
            if (attempts++ < 20) timer = setTimeout(findTarget, 100);
        };
        let timer = setTimeout(findTarget, 50);
        return () => {
            clearTimeout(timer);
            target?.classList.remove('is-walkthrough-target');
        };
    }, [currentStep?.target, location.pathname, open]);

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
        start,
        state,
    ]);

    return <WalkthroughContext.Provider value={value}>{children}</WalkthroughContext.Provider>;
}
