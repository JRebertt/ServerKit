// Generic restore points and the merged per-server activity timeline.

export async function getServerTimeline(serverId, {
    types = [],
    before = null,
    limit = 50,
} = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (types.length) params.set('types', types.join(','));
    if (before) params.set('before', before);
    return this.request(`/servers/${serverId}/timeline?${params.toString()}`);
}

export async function createRestorePoint({ scopeType, scopeId, label = null }) {
    const body = {
        scope_type: scopeType,
        scope_id: String(scopeId),
    };
    if (label) body.label = label;
    return this.request('/restore-points', { method: 'POST', body });
}

export async function getRestorePoint(pointId) {
    return this.request(`/restore-points/${pointId}`);
}

export async function getRestorePointDiff(pointId, against = 'previous') {
    const query = against ? `?against=${encodeURIComponent(against)}` : '';
    return this.request(`/restore-points/${pointId}/diff${query}`);
}

export async function previewRestorePoint(pointId) {
    return this.request(`/restore-points/${pointId}/preview`, { method: 'POST' });
}

export async function restoreRestorePoint(pointId) {
    return this.request(`/restore-points/${pointId}/restore`, { method: 'POST' });
}
