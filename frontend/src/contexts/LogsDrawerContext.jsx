import { useOperations } from './OperationsContext';

// Compatibility shell for existing callers and extension SDK consumers.
// Log sessions now live in OperationsProvider; no second drawer is rendered.
export function LogsDrawerProvider({ children }) {
    return children;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useLogsDrawer() {
    const {
        logSession,
        collapsed,
        openLogSession,
        closeLogSession,
        setCollapsed,
    } = useOperations();

    return {
        drawerState: !logSession ? 'closed' : collapsed ? 'collapsed' : 'expanded',
        service: logSession,
        openDrawer: openLogSession,
        closeDrawer: closeLogSession,
        toggleDrawer: () => {
            if (logSession) setCollapsed((current) => !current);
        },
        collapseDrawer: () => setCollapsed(true),
        expandDrawer: () => setCollapsed(false),
    };
}
