// Recycle Bin — soft-deleted records across every model that opted into
// SoftDeleteMixin. Type-agnostic: `kind` comes from the server's registry, so
// new restorable types appear here without a client change.

// { items: [{ kind, noun, id, label, description, deleted_at, deleted_by_id }],
//   kinds: [...], retention_days }
export async function getRecycleBin({ kind, limit } = {}) {
    const params = new URLSearchParams();
    if (kind) params.set('kind', kind);
    if (limit) params.set('limit', String(limit));
    const qs = params.toString();
    return this.request(`/recycle-bin${qs ? `?${qs}` : ''}`);
}

// Put a record back. Resolves with { item, warning } — a warning means the row
// returned but re-applying its side effects (a vhost, say) failed.
export async function restoreRecord(kind, id) {
    return this.request(`/recycle-bin/${kind}/${id}/restore`, { method: 'POST' });
}

// Destroy permanently. Admin-only, and the only irreversible call here.
export async function purgeRecord(kind, id) {
    return this.request(`/recycle-bin/${kind}/${id}`, { method: 'DELETE' });
}

// Reap every tombstone older than the retention window.
export async function purgeExpiredRecords(retentionDays) {
    return this.request('/recycle-bin/purge-expired', {
        method: 'POST',
        body: JSON.stringify({ retention_days: retentionDays }),
    });
}
