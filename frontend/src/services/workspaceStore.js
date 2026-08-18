export const ACTIVE_WORKSPACE_ID_KEY = 'active_workspace_id';
export const ACTIVE_WORKSPACE_KEY = 'active_workspace';
export const WORKSPACE_ACCENT_KEY = 'workspace_accent';

const TRACKED_KEYS = new Set([
    ACTIVE_WORKSPACE_ID_KEY,
    ACTIVE_WORKSPACE_KEY,
    WORKSPACE_ACCENT_KEY,
]);

const ALL_WORKSPACES_SNAPSHOT = Object.freeze({
    activeWorkspaceId: 'all',
    activeWorkspace: null,
    workspaceAccent: null,
});

const safeGet = (storage, key) => {
    try {
        return storage?.getItem(key) ?? null;
    } catch {
        return null;
    }
};

const safeSet = (storage, key, value) => {
    try {
        storage?.setItem(key, value);
    } catch {
        // Workspace persistence is a convenience. In-memory state still updates
        // when storage is unavailable (private mode, quota, or sandboxed frames).
    }
};

const safeRemove = (storage, key) => {
    try {
        storage?.removeItem(key);
    } catch {
        // See safeSet: keep the live store usable even without persistence.
    }
};

const normalizeWorkspaceId = (value) => {
    if (value == null) return 'all';
    const id = String(value).trim();
    return !id || id === 'all' ? 'all' : id;
};

const parseWorkspace = (raw) => {
    if (!raw) return null;
    try {
        const workspace = JSON.parse(raw);
        return workspace && typeof workspace === 'object' ? workspace : null;
    } catch {
        return null;
    }
};

const readSnapshot = (storage) => {
    const activeWorkspaceId = normalizeWorkspaceId(
        safeGet(storage, ACTIVE_WORKSPACE_ID_KEY),
    );
    if (activeWorkspaceId === 'all') return ALL_WORKSPACES_SNAPSHOT;

    const storedWorkspace = parseWorkspace(safeGet(storage, ACTIVE_WORKSPACE_KEY));
    const activeWorkspace = storedWorkspace
        && String(storedWorkspace.id) === activeWorkspaceId
        ? storedWorkspace
        : null;

    return {
        activeWorkspaceId,
        activeWorkspace,
        workspaceAccent: safeGet(storage, WORKSPACE_ACCENT_KEY),
    };
};

const snapshotSignature = (snapshot) => JSON.stringify(snapshot);

/**
 * Framework-neutral active-workspace store.
 *
 * React subscribes through WorkspaceProvider, while ApiClient reads the same
 * snapshot directly. The factory is exported so persistence and cross-tab
 * behavior can be tested without a browser runtime.
 */
export function createWorkspaceStore({ storage, eventTarget } = {}) {
    const resolvedStorage = storage
        ?? (typeof window !== 'undefined' ? window.localStorage : null);
    const resolvedEventTarget = eventTarget
        ?? (typeof window !== 'undefined' ? window : null);
    const listeners = new Set();
    let snapshot = readSnapshot(resolvedStorage);
    let signature = snapshotSignature(snapshot);

    const publishSnapshot = (nextSnapshot) => {
        const nextSignature = snapshotSignature(nextSnapshot);
        if (nextSignature === signature) return false;
        snapshot = nextSnapshot;
        signature = nextSignature;
        listeners.forEach((listener) => listener());
        return true;
    };

    const syncFromStorage = () => publishSnapshot(readSnapshot(resolvedStorage));

    const handleStorage = (event) => {
        if (event?.key != null && !TRACKED_KEYS.has(event.key)) return;
        syncFromStorage();
    };

    // ApiClient also consumes this store without mounting React, so cross-tab
    // updates must be observed for the lifetime of the store rather than only
    // while a component happens to be subscribed.
    resolvedEventTarget?.addEventListener?.('storage', handleStorage);

    const subscribe = (listener) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
    };

    // useSyncExternalStore requires a cached, side-effect-free snapshot getter.
    // Same-tab mutations and cross-tab storage events update this value.
    const getSnapshot = () => snapshot;

    const clearActiveWorkspace = () => {
        safeRemove(resolvedStorage, ACTIVE_WORKSPACE_ID_KEY);
        safeRemove(resolvedStorage, ACTIVE_WORKSPACE_KEY);
        safeRemove(resolvedStorage, WORKSPACE_ACCENT_KEY);
        publishSnapshot(ALL_WORKSPACES_SNAPSHOT);
    };

    const persistWorkspace = (workspace) => {
        if (!workspace || workspace.id == null) {
            clearActiveWorkspace();
            return;
        }

        const activeWorkspaceId = normalizeWorkspaceId(workspace.id);
        if (activeWorkspaceId === 'all') {
            clearActiveWorkspace();
            return;
        }

        const workspaceAccent = workspace.primary_color || null;
        safeSet(resolvedStorage, ACTIVE_WORKSPACE_ID_KEY, activeWorkspaceId);
        safeSet(resolvedStorage, ACTIVE_WORKSPACE_KEY, JSON.stringify(workspace));
        if (workspaceAccent) {
            safeSet(resolvedStorage, WORKSPACE_ACCENT_KEY, workspaceAccent);
        } else {
            safeRemove(resolvedStorage, WORKSPACE_ACCENT_KEY);
        }
        publishSnapshot({ activeWorkspaceId, activeWorkspace: workspace, workspaceAccent });
    };

    const refreshActiveWorkspace = (workspace) => {
        if (!workspace || String(workspace.id) !== getSnapshot().activeWorkspaceId) return;
        persistWorkspace(workspace);
    };

    return {
        subscribe,
        getSnapshot,
        getServerSnapshot: () => ALL_WORKSPACES_SNAPSHOT,
        setActiveWorkspace: persistWorkspace,
        refreshActiveWorkspace,
        clearActiveWorkspace,
        destroy: () => {
            resolvedEventTarget?.removeEventListener?.('storage', handleStorage);
            listeners.clear();
        },
    };
}

export const workspaceStore = createWorkspaceStore();
