import {
    createContext, useCallback, useContext, useEffect, useMemo, useState,
} from 'react';

import { useOperations } from './OperationsContext';
import { useServerkitAI } from './AIContext';
import { useWalkthroughs } from './walkthroughContextValue';

// One console, four tabs (Operations · Alerts · Recipes · Assistant), exactly
// one visible at a time — the prototype's bottom-edge console. Open state for
// three of the tabs already lives in feature contexts that pages drive
// directly (e.g. "Ask AI" buttons call useServerkitAI().open()), so this
// provider doesn't own their state: it derives the active tab and flips the
// underlying contexts in concert. Priority on conflicting opens: assistant >
// recipes > operations — closing the winner reveals the panel underneath.
const ShellDockContext = createContext(null);

export function ShellDockProvider({ children }) {
    const { collapsed, setCollapsed } = useOperations();
    const { isOpen: assistantOpen, open: openAssistant, close: closeAssistant } = useServerkitAI();
    const { open: recipesOpen, setOpen: setRecipesOpen } = useWalkthroughs();
    const [alertsOpen, setAlertsOpen] = useState(false);
    const [expanded, setExpanded] = useState(false);

    const activeTab = assistantOpen
        ? 'assistant'
        : recipesOpen
            ? 'recipes'
            : !collapsed
                ? 'ops'
                : alertsOpen
                    ? 'alerts'
                    : null;

    const openTab = useCallback((tab) => {
        setCollapsed(tab !== 'ops');
        setRecipesOpen(tab === 'recipes');
        setAlertsOpen(tab === 'alerts');
        if (tab === 'assistant') openAssistant();
        else closeAssistant();
    }, [closeAssistant, openAssistant, setCollapsed, setRecipesOpen]);

    const close = useCallback(() => openTab(null), [openTab]);

    const toggleTab = useCallback((tab) => {
        openTab(activeTab === tab ? null : tab);
    }, [activeTab, openTab]);

    // Escape closes the console. The assistant and any open dialog handle
    // their own Escape first (focus trap / Radix preventDefault), so only act
    // on unclaimed presses outside text inputs.
    useEffect(() => {
        if (!activeTab || activeTab === 'assistant') return undefined;
        const onKeyDown = (event) => {
            if (event.key !== 'Escape' || event.defaultPrevented) return;
            const target = document.activeElement;
            const tag = target?.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target?.isContentEditable) return;
            close();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [activeTab, close]);

    const value = useMemo(() => ({
        activeTab,
        openTab,
        toggleTab,
        close,
        expanded,
        setExpanded,
    }), [activeTab, close, expanded, openTab, toggleTab]);

    return <ShellDockContext.Provider value={value}>{children}</ShellDockContext.Provider>;
}

export function useShellDock() {
    const context = useContext(ShellDockContext);
    if (!context) throw new Error('useShellDock must be used within ShellDockProvider');
    return context;
}
