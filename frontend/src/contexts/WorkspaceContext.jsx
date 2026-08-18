import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from 'react';
import { workspaceStore } from '../services/workspaceStore';

const WorkspaceContext = createContext(null);

export function WorkspaceProvider({ children }) {
    const snapshot = useSyncExternalStore(
        workspaceStore.subscribe,
        workspaceStore.getSnapshot,
        workspaceStore.getServerSnapshot,
    );

    const setActiveWorkspace = useCallback((workspace) => {
        workspaceStore.setActiveWorkspace(workspace);
    }, []);

    const clearActiveWorkspace = useCallback(() => {
        workspaceStore.clearActiveWorkspace();
    }, []);

    const refreshActiveWorkspace = useCallback((workspace) => {
        workspaceStore.refreshActiveWorkspace(workspace);
    }, []);

    const value = useMemo(() => ({
        ...snapshot,
        isAllWorkspaces: snapshot.activeWorkspaceId === 'all',
        setActiveWorkspace,
        clearActiveWorkspace,
        refreshActiveWorkspace,
    }), [snapshot, setActiveWorkspace, clearActiveWorkspace, refreshActiveWorkspace]);

    return (
        <WorkspaceContext.Provider value={value}>
            {children}
        </WorkspaceContext.Provider>
    );
}

export function useWorkspace() {
    const context = useContext(WorkspaceContext);
    if (!context) {
        throw new Error('useWorkspace must be used within a WorkspaceProvider');
    }
    return context;
}

