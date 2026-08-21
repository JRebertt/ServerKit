import { useCallback, useMemo, useState } from 'react';

import { useAuth } from '../contexts/AuthContext';
import { useServerQuery } from './useServerQuery';
import api from '../services/api';
import { getFavorites } from '../utils/recents';
import {
    getRecentResourceKeys,
    groupResourceOptions,
    normalizeResourceRef,
    recordRecentResource,
} from '../utils/resourceRefs';

const stableList = (values) => [...new Set(values || [])].map(String).sort();

export function useResourceOptions({
    types,
    scope = {},
    capabilities = [],
    query = '',
    cursor = null,
    limit = 20,
    enabled = true,
} = {}) {
    const { user } = useAuth();
    const [recentRevision, setRecentRevision] = useState(0);
    const normalizedTypes = stableList(types);
    const normalizedCapabilities = stableList(capabilities);
    const normalizedScope = {
        workspaceId: scope.workspaceId ?? scope.workspace_id ?? null,
        projectId: scope.projectId ?? scope.project_id ?? null,
        environmentId: scope.environmentId ?? scope.environment_id ?? null,
    };
    const normalizedQuery = String(query || '').trim();

    const request = useServerQuery(
        [
            'resource-options',
            normalizedTypes.join(','),
            normalizedScope.workspaceId,
            normalizedScope.projectId,
            normalizedScope.environmentId,
            normalizedCapabilities.join(','),
            normalizedQuery,
            cursor,
            limit,
        ],
        ({ signal }) => api.searchResources({
            types: normalizedTypes,
            scope: normalizedScope,
            capabilities: normalizedCapabilities,
            query: normalizedQuery,
            cursor,
            limit,
        }, { signal }),
        {
            enabled: enabled && normalizedTypes.length > 0,
            staleTime: 15_000,
        },
    );

    const options = useMemo(
        () => (request.data?.results || []).map(normalizeResourceRef).filter(Boolean),
        [request.data],
    );
    const recentKeys = useMemo(
        () => getRecentResourceKeys(user?.id, normalizedTypes),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [user?.id, normalizedTypes.join(','), recentRevision],
    );
    const groups = useMemo(
        () => groupResourceOptions(options, {
            favoriteEntries: getFavorites(),
            recentKeys,
        }),
        [options, recentKeys],
    );
    const recordSelection = useCallback((resource) => {
        recordRecentResource(resource, user?.id);
        setRecentRevision((revision) => revision + 1);
        return resource;
    }, [user?.id]);

    return {
        ...request,
        options,
        groups,
        nextCursor: request.data?.nextCursor ?? null,
        recordSelection,
    };
}
