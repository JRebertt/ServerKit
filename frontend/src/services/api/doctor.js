// Doctor / drift API — health sweep + configuration drift surface
// (Monitoring → Doctor tab). Admin-only endpoints under /api/v1/doctor.

export async function getDoctorReport() {
    return this.request('/doctor');
}

export async function runDoctor() {
    return this.request('/doctor/run', { method: 'POST' });
}

export async function repairDoctorItems(items) {
    return this.request('/doctor/repair', {
        method: 'POST',
        body: JSON.stringify({ items }),
    });
}

// Fleet doctor (plan 26) — the per-server health sweep merged across every
// connected agent. getFleetDoctorReport returns { report: { ran_at, servers } };
// runFleetSweep enqueues the sweep job (fan-out runs off the request thread)
// and returns { job_id }.
export async function getFleetDoctorReport() {
    return this.request('/doctor/fleet');
}

export async function runFleetSweep() {
    return this.request('/doctor/fleet/run', { method: 'POST' });
}

// Allowlisted remote repairs (currently: restart a core service on an agent).
// Refusals — offline agent, missing capability, non-allowlisted target — come
// back as per-item { success: false, code } results, not as a failed request.
export async function repairFleetItems(items) {
    return this.request('/doctor/fleet/repair', {
        method: 'POST',
        body: JSON.stringify({ items }),
    });
}

// Setup Health — "how set-up is this panel" (server IP / base domain / DNS
// provider / cert / email / backups). Admin-only; cheap DB/settings probes.
export async function getSetupHealth() {
    return this.request('/setup-health');
}

// The requesting user's own setup-health items (e.g. the "secure your account"
// nudge). Any authenticated user, about themselves.
export async function getAccountSecurity() {
    return this.request('/setup-health/account');
}

// Snooze / un-snooze a setup item (mutes it; it still renders, just quietly).
export async function snoozeSetupItem(key, days = 30) {
    return this.request('/setup-health/snooze', {
        method: 'POST',
        body: JSON.stringify({ key, days }),
    });
}

export async function unsnoozeSetupItem(key) {
    return this.request('/setup-health/snooze', {
        method: 'DELETE',
        body: JSON.stringify({ key }),
    });
}

// Reconcile-on-connect (Phase 3): preview is a synchronous dry-run; apply
// enqueues the job and returns { job_id }.
export async function previewDnsBackfill() {
    return this.request('/setup-health/reconcile/dns/preview', { method: 'POST' });
}

export async function applyDnsBackfill() {
    return this.request('/setup-health/reconcile/dns/apply', { method: 'POST' });
}

export async function previewUrlFix() {
    return this.request('/setup-health/reconcile/url-fix/preview', { method: 'POST' });
}

export async function applyUrlFix() {
    return this.request('/setup-health/reconcile/url-fix/apply', { method: 'POST' });
}

export async function getDriftReport() {
    return this.request('/doctor/drift');
}

export async function runDriftCheck() {
    return this.request('/doctor/drift/check', { method: 'POST' });
}

export async function repairDrift(type, id) {
    return this.request(`/doctor/drift/${type}/${id}/repair`, {
        method: 'POST',
        body: JSON.stringify({ confirm: true }),
    });
}
