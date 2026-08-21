const STORAGE_PREFIX = 'serverkit:resource-recents';
const MAX_PER_TYPE = 5;

const normalizeScopeValue = (value) => {
    if (value === undefined || value === null || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
};

export function normalizeResourceRef(row) {
    if (!row || row.type == null || row.id == null || !row.label || !row.path) return null;
    const scope = row.scope || {};
    return {
        type: String(row.type),
        id: String(row.id),
        label: String(row.label),
        sublabel: String(row.sublabel || ''),
        path: String(row.path),
        scope: {
            workspaceId: normalizeScopeValue(scope.workspace_id ?? scope.workspaceId),
            projectId: normalizeScopeValue(scope.project_id ?? scope.projectId),
            environmentId: normalizeScopeValue(scope.environment_id ?? scope.environmentId),
        },
        status: row.status == null ? null : String(row.status),
        capabilities: [...new Set((row.capabilities || []).map(String))].sort(),
    };
}

export const resourceKey = (resource) => `${resource.type}:${resource.id}`;

const storageKey = (userId) => `${STORAGE_PREFIX}:${userId}`;

const resolveStorage = (storage) => {
    if (storage) return storage;
    if (typeof localStorage !== 'undefined') return localStorage;
    return null;
};

const load = (userId, storage) => {
    if (userId == null) return [];
    try {
        const raw = resolveStorage(storage)?.getItem(storageKey(userId));
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
};

export function getRecentResourceKeys(userId, types = [], storage) {
    const allowedTypes = new Set(types || []);
    return load(userId, storage)
        .filter((entry) => !allowedTypes.size || allowedTypes.has(entry.type))
        .map((entry) => `${entry.type}:${entry.id}`);
}

export function recordRecentResource(resource, userId, storage) {
    const normalized = normalizeResourceRef(resource);
    const target = resolveStorage(storage);
    if (!normalized || userId == null || !target) return;

    const entry = {
        type: normalized.type,
        id: normalized.id,
        at: Date.now(),
    };
    const existing = load(userId, target)
        .filter((candidate) => resourceKey(candidate) !== resourceKey(entry));
    const next = [entry, ...existing].filter((candidate, index, all) => (
        all.slice(0, index + 1).filter((item) => item.type === candidate.type).length
        <= MAX_PER_TYPE
    ));
    try {
        target.setItem(storageKey(userId), JSON.stringify(next));
    } catch {
        // Selection history is a convenience; storage failures never block it.
    }
}

export function groupResourceOptions(options, { favoriteEntries = [], recentKeys = [] } = {}) {
    const favorites = new Set(favoriteEntries.map(resourceKey));
    const recents = new Set(recentKeys);
    const favoriteOptions = [];
    const recentOptions = [];
    const remainingOptions = [];

    options.forEach((option) => {
        const key = resourceKey(option);
        if (favorites.has(key)) favoriteOptions.push(option);
        else if (recents.has(key)) recentOptions.push(option);
        else remainingOptions.push(option);
    });

    return [
        favoriteOptions.length && { id: 'favorites', options: favoriteOptions },
        recentOptions.length && { id: 'recent', options: recentOptions },
        remainingOptions.length && { id: 'results', options: remainingOptions },
    ].filter(Boolean);
}
