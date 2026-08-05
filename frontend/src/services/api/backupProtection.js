// Backup "Protection" policy + runs API.
//
// Generic over the target so the shared ProtectionPanel can drive both
// WordPress sites and applications with one set of methods. The backend mounts
// the same endpoint shapes under /wordpress/sites/:id and /apps/:id.

function policyBase(targetType, targetId) {
    return targetType === 'wordpress_site'
        ? `/wordpress/sites/${targetId}/backup-policy`
        : `/apps/${targetId}/backup-policy`;
}

function runsBase(targetType, targetId) {
    return targetType === 'wordpress_site'
        ? `/wordpress/sites/${targetId}/backups`
        : `/apps/${targetId}/backups`;
}

export async function getBackupPolicy(targetType, targetId) {
    return this.request(policyBase(targetType, targetId));
}

export async function updateBackupPolicy(targetType, targetId, policy) {
    return this.request(policyBase(targetType, targetId), { method: 'PUT', body: policy });
}

export async function triggerBackup(targetType, targetId) {
    return this.request(runsBase(targetType, targetId), { method: 'POST' });
}

export async function getBackupRuns(targetType, targetId) {
    return this.request(runsBase(targetType, targetId));
}

export async function restoreBackupRun(targetType, targetId, runId, options) {
    return this.request(`${runsBase(targetType, targetId)}/${runId}/restore`, {
        method: 'POST',
        body: options || {},
    });
}

export async function verifyBackupRun(targetType, targetId, runId) {
    return this.request(`${runsBase(targetType, targetId)}/${runId}/verify`, { method: 'POST' });
}

// Trigger a restore drill (a proving test-restore into a throwaway location).
// Applications and WordPress sites use their own edit-gated, target-scoped
// endpoint (the same owner who can back up a target can drill it); any other
// target routes through the admin-only generic policy-by-target endpoint.
export async function runBackupDrill(targetType, targetId) {
    if (targetType === 'application' || targetType === 'wordpress_site') {
        return this.request(`${runsBase(targetType, targetId)}/drill`, { method: 'POST' });
    }
    return this.request(`/backups/policies/${targetType}/${targetId}/drill`, { method: 'POST' });
}

export async function deleteBackupRun(targetType, targetId, runId) {
    return this.request(`${runsBase(targetType, targetId)}/${runId}`, { method: 'DELETE' });
}

// ---- fleet-wide policy + run views (§8 unification) -----------------------
// The per-target methods above answer "how is THIS site protected?"; these two
// answer "how is everything protected?" and back the Backups overview — the
// protected-resource count, the activity heatmap, and the success rate all come
// from these two lists rather than from the filesystem archive listing.

// Target types available right now (core set + extension-registered kinds,
// e.g. wordpress_site only while the WordPress extension is installed). The
// Protection panel / restore drawer read this instead of hardcoding type
// knowledge, so an absent extension means an absent type (plan 52 D4).
export async function getBackupTargetTypes() {
    return this.request('/backups/target-types');
}

export async function listBackupPolicies(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request(`/backups/policies${qs ? `?${qs}` : ''}`);
}

export async function listBackupRuns(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request(`/backups/runs${qs ? `?${qs}` : ''}`);
}
