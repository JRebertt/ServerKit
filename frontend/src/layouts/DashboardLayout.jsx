import { useState, useEffect, useCallback, useMemo } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import MobileTopBar from '../components/MobileTopBar';
import CommandPalette from '../components/CommandPalette';
import LogsDrawer from '../components/LogsDrawer';
import { LogsDrawerProvider } from '../contexts/LogsDrawerContext';
import { AIProvider } from '../contexts/AIContext';
import AIAssistant from '../components/ai/AIAssistant';
import { ConfirmProvider } from '../contexts/ConfirmContext';
import PluginLoader from '../plugins/PluginLoader';
import { ensureContributions, useContributions } from '../plugins/contributions';
import useMediaQuery from '../hooks/useMediaQuery';
import { useLockBodyScroll } from '../hooks/useLockBodyScroll';
import api from '../services/api';
import SystemNotices from '../components/SystemNotices';
import StagingBanner from '../components/StagingBanner';
import OperationsDock from '../components/OperationsDock';
import ErrorBoundary from '../components/ErrorBoundary';
import { useShortcut } from '../hooks/useShortcut';
import { useTranslation } from 'react-i18next';
import { OperationsProvider } from '../contexts/OperationsContext';

// The Automations extension (tramo) contributes /automations/edit/:slug with
// layout:'full', so it's picked up dynamically via fullPagePaths below.
const FULL_PAGE_ROUTES = ['/files', '/docker'];

const DashboardLayout = () => {
    const { t } = useTranslation();
    const location = useLocation();
    const [paletteOpen, setPaletteOpen] = useState(false);
    const [navOpen, setNavOpen] = useState(false);
    // Matches the sidebar's $breakpoint-md (768px). Below it the persistent
    // sidebar collapses into an off-canvas drawer driven by navOpen.
    const isMobile = useMediaQuery('(max-width: 768px)');
    const { routes: pluginRoutes } = useContributions();

    // Plugin routes contribute their path relative to the dashboard
    // parent (e.g. "git", "git/:tab"). Normalize to leading-slash and
    // strip any :params so we can do a startsWith check below.
    const fullPagePaths = useMemo(() => {
        const fromPlugins = (pluginRoutes || [])
            .filter((r) => r && r.layout === 'full' && r.path)
            .map((r) => {
                const stripped = r.path.split('/:')[0].replace(/^\/+/, '');
                return '/' + stripped;
            });
        return [...FULL_PAGE_ROUTES, ...fromPlugins];
    }, [pluginRoutes]);

    const isFullPageRoute = fullPagePaths.some((route) => (
        location.pathname === route || location.pathname.startsWith(`${route}/`)
    ));

    const handleKeyDown = useCallback((e) => {
        // Open aliases: Ctrl/Cmd+K (original), plus VS Code muscle memory —
        // F1 and Ctrl/Cmd+Shift+P. preventDefault on F1 keeps the browser
        // help panel from stealing it.
        const cmdK = (e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'k';
        const cmdShiftP = (e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'p';
        const f1 = e.key === 'F1';
        if (cmdK || cmdShiftP || f1) {
            e.preventDefault();
            setPaletteOpen(prev => !prev);
        }
    }, []);

    useShortcut({
        id: 'command-palette',
        label: t('palette.label', 'Command palette'),
        group: 'shell',
        keys: [
            { key: 'k', ctrlOrMeta: true },
            { key: 'p', ctrlOrMeta: true, shift: true },
            { key: 'F1' },
        ],
        allowInInput: true,
        handler: handleKeyDown,
    });

    // Close the mobile drawer on navigation (covers nav-link taps too).
    useEffect(() => {
        setNavOpen(false);
    }, [location.pathname]);

    // Never leave the drawer "open" when we cross back to the desktop layout.
    useEffect(() => {
        if (!isMobile) setNavOpen(false);
    }, [isMobile]);

    // Lock body scroll behind the drawer while it's open on mobile.
    useLockBodyScroll(isMobile && navOpen);

    // Load plugin contributions once we're authenticated. Subscribers
    // (Sidebar, CommandPalette, ExtensionRoutes, PageTitleUpdater) all
    // pick up the result via useContributions().
    useEffect(() => {
        ensureContributions();
    }, []);

    return (
        <OperationsProvider>
        <LogsDrawerProvider>
            <AIProvider>
            <ConfirmProvider>
            <div className="dashboard-layout">
                <StagingBanner />
                <MobileTopBar navOpen={navOpen} onToggle={() => setNavOpen(prev => !prev)} />
                <Sidebar
                    mobileOpen={navOpen}
                    isMobile={isMobile}
                    onMobileClose={() => setNavOpen(false)}
                />
                {isMobile && navOpen && (
                    <div
                        className="sidebar-backdrop"
                        onClick={() => setNavOpen(false)}
                        aria-hidden="true"
                    />
                )}
                <main className={`main-content${isFullPageRoute ? ' main-content--full-page' : ''}`}>
                    {!isFullPageRoute && <SystemNotices />}
                    <ErrorBoundary resetKey={location.pathname}>
                        <Outlet />
                    </ErrorBoundary>
                </main>
                <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
                <LogsDrawer />
                <OperationsDock />
                <AIAssistant />
                <PluginLoader api={api} />
            </div>
            </ConfirmProvider>
            </AIProvider>
        </LogsDrawerProvider>
        </OperationsProvider>
    );
};

export default DashboardLayout;
