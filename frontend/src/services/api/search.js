// Unified entity omnisearch (plan 41, Phase 4).
export async function search(q) {
    const response = await this.request(`/search?q=${encodeURIComponent(q)}`);
    return normalizeSearchResponse(response);
}

const appendCsv = (params, key, values) => {
    const normalized = [...new Set((values || []).map(String).map((value) => value.trim()).filter(Boolean))];
    if (normalized.length) params.set(key, normalized.join(','));
};

const appendScope = (params, scope = {}) => {
    const fields = [
        ['workspace_id', scope.workspaceId ?? scope.workspace_id],
        ['project_id', scope.projectId ?? scope.project_id],
        ['environment_id', scope.environmentId ?? scope.environment_id],
    ];
    fields.forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '' && value !== 'all') {
            params.set(key, String(value));
        }
    });
};

export function buildResourceSearchQuery({
    query = '',
    types = [],
    scope = {},
    capabilities = [],
    cursor = null,
    limit = 20,
} = {}) {
    const params = new URLSearchParams();
    const normalizedQuery = String(query || '').trim();
    if (normalizedQuery) params.set('q', normalizedQuery);
    appendCsv(params, 'types', types);
    appendScope(params, scope);
    appendCsv(params, 'capabilities', capabilities);
    if (cursor) params.set('cursor', String(cursor));
    if (limit != null) params.set('limit', String(limit));
    return params.toString();
}

const normalizeSearchResponse = (response) => ({
    ...response,
    // The backend keeps `results` during the public API migration. Prefer
    // the canonical envelope here so the browser exercises the new path.
    results: response?.data ?? response?.results ?? [],
});

export async function searchResources(params, options = {}) {
    const query = buildResourceSearchQuery(params);
    const response = await this.request(`/search?${query}`, options);
    return {
        ...normalizeSearchResponse(response),
        nextCursor: response?.meta?.next_cursor ?? null,
    };
}
