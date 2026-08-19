// Error tracking API methods. Mixed into ApiService (see ./index.js) so each
// function runs with `this` bound to the client and calls `this.request(...)`.

// --- Admin error log (JWT) ---

export async function getErrorLogs(params = {}) {
    const query = new URLSearchParams();
    if (params.source) query.append('source', params.source);
    if (params.resolved !== undefined && params.resolved !== null && params.resolved !== '') {
        query.append('resolved', params.resolved);
    }
    if (params.search) query.append('search', params.search);
    if (params.page) query.append('page', params.page);
    if (params.per_page) query.append('per_page', params.per_page);
    const suffix = query.toString() ? `?${query}` : '';
    return this.request(`/error-logs${suffix}`);
}

export async function getErrorLogStats() {
    return this.request('/error-logs/stats');
}

export async function getErrorLog(id) {
    return this.request(`/error-logs/${id}`);
}

export async function resolveErrorLog(id, resolved) {
    return this.request(`/error-logs/${id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ resolved }),
    });
}

export async function deleteErrorLog(id) {
    return this.request(`/error-logs/${id}`, { method: 'DELETE' });
}

// --- Client-side error ingestion (public-ish) ---
//
// Deliberately NOT this.request(): the report has to go out even when the
// caller's token is expired or missing (an expired session is exactly when a
// boundary error is likely), and a failed error report must never throw —
// it is called from ErrorBoundary.componentDidCatch, where throwing would
// re-trip the boundary it is reporting from.
//
// The Authorization header is still attached by hand when a token exists, so
// the backend can attribute the report (ErrorLog.user_id, rendered as "User #N"
// in pages/Errors.jsx). Without it every frontend row is anonymous.
//
// A stale token costs nothing here, but NOT for the reason it looks like:
// verify_jwt_in_request(optional=True) tolerates a MISSING token only — an
// expired one raises ExpiredSignatureError. The route survives because it wraps
// that call in try/except and falls back to an anonymous report, so do not
// tighten that except without revisiting this.
export async function reportClientError(payload) {
    try {
        const token = this.getToken();
        await fetch(`${this.baseUrl}/error-logs/client`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token && { Authorization: `Bearer ${token}` }),
            },
            body: JSON.stringify(payload),
        });
    } catch {
        // Swallow: reporting is best-effort.
    }
}
