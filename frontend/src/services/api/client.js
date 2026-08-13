// Base HTTP client - constructor, token management, core request methods
const AUTH_EXPIRED_EVENT = 'serverkit:auth-expired';

const normalizeApiBaseUrl = (url) => {
    if (!url) return '/api/v1';
    const trimmed = url.replace(/\/+$/, '');
    return trimmed.endsWith('/api/v1') ? trimmed : `${trimmed}/api/v1`;
};

// In dev, keep browser requests same-origin so Vite can proxy /api to the
// configured backend target. Calling VITE_API_URL directly bypasses that
// proxy and exposes CORS/preflight redirects in the browser.
const API_BASE_URL = import.meta.env.DEV
    ? '/api/v1'
    : normalizeApiBaseUrl(import.meta.env.VITE_API_URL);

// Requests that are safe to share with a concurrent identical caller: a plain
// GET with no body, no custom headers (X-DB-Password and friends change what
// comes back) and no abort signal (one caller aborting must not cancel
// someone else's request).
// A joining caller gets its own copy, so the two callers keep the independent
// objects they had when each ran its own fetch — one of them mutating the
// result (sorting an array in place, say) must not corrupt the other's.
const cloneResult = (data) => {
    if (data === null || typeof data !== 'object') return data;
    try {
        return structuredClone(data);
    } catch {
        return data;   // exotic payload — sharing beats throwing
    }
};

const isCoalescable = (options) => (
    (!options.method || options.method === 'GET')
    && !options.body
    && !options.headers
    && !options.signal
);

class ApiClient {
    constructor() {
        this.baseUrl = API_BASE_URL;
        // In-flight GET coalescing. Two callers asking for the same URL at the
        // same moment share one network request instead of racing.
        //
        // This is NOT a cache — the entry is dropped the moment the request
        // settles, so nobody ever reads a stale body. It only collapses the
        // overlap, which is where the duplicates actually came from: React's
        // StrictMode double-invokes every effect in dev, two independent
        // components own the same endpoint (/system/notices,
        // /plugins/contributions), and a poller whose previous tick has not
        // returned fires again on schedule. A DevTools capture of one page load
        // showed the same endpoint requested up to five times concurrently.
        //
        // It matters more than it looks: in dev the API shares the browser's
        // six-connection HTTP/1.1 budget with Vite's module graph, so a
        // redundant request does not merely waste the backend's time, it holds
        // a connection the page needs to finish rendering.
        this._inflight = new Map();
    }

    getToken() {
        return localStorage.getItem('access_token');
    }

    setTokens(accessToken, refreshToken) {
        localStorage.setItem('access_token', accessToken);
        localStorage.setItem('refresh_token', refreshToken);
    }

    clearTokens() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('active_workspace_id');  // drop workspace context on logout
        localStorage.removeItem('active_workspace');
        localStorage.removeItem('workspace_accent');
    }

    request(endpoint, options = {}) {
        if (!isCoalescable(options)) return this._request(endpoint, options);

        // Scope the key by workspace: the same path returns different rows
        // under a different X-Workspace-Id.
        const key = `${localStorage.getItem('active_workspace_id') || ''}|${endpoint}`;
        const existing = this._inflight.get(key);
        if (existing) return existing.then(cloneResult);

        const pending = this._request(endpoint, options)
            .finally(() => { this._inflight.delete(key); });
        this._inflight.set(key, pending);
        return pending;
    }

    async _request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const token = this.getToken();

        // FormData uploads need browser-built Content-Type (with boundary)
        // and must NOT be JSON-stringified. Detect and bypass both.
        const isFormData = options.body instanceof FormData;

        // Active workspace context (#33). Sent ambiently so the backend can scope
        // resources; endpoints that don't honor it ignore it. A stale value is safe
        // — the backend resolves it leniently (falls back to no scope).
        const activeWorkspace = localStorage.getItem('active_workspace_id');

        // Spread `...options` FIRST, then set merged headers LAST — otherwise a
        // call passing custom `headers` (e.g. X-DB-Password) would clobber the
        // whole merged set, dropping Content-Type/Authorization and triggering
        // 415 (no application/json) on JSON POSTs.
        const config = {
            ...options,
            headers: {
                ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                ...(token && { Authorization: `Bearer ${token}` }),
                ...(activeWorkspace && activeWorkspace !== 'all' && { 'X-Workspace-Id': activeWorkspace }),
                ...options.headers,
            },
        };

        if (
            !isFormData &&
            options.body &&
            typeof options.body === 'object' &&
            !(options.body instanceof Blob)
        ) {
            config.body = JSON.stringify(options.body);
        }

        const response = await fetch(url, config);

        if (response.status === 401) {
            // flask-jwt-extended returns 401 with `{"msg": "..."}` when
            // the token is the problem; domain endpoints (e.g. wrong
            // pair-code passphrase) return `{"error": "..."}`. Only the
            // former should trigger a token refresh — refreshing on a
            // domain 401 wastes a backend round-trip and burns through
            // rate limits twice as fast.
            const probe = await response.clone().json().catch(() => ({}));
            const isJwtIssue = probe && probe.msg && !probe.error;

            if (isJwtIssue) {
                const refreshed = await this.refreshToken();
                if (refreshed) {
                    config.headers.Authorization = `Bearer ${this.getToken()}`;
                    const retryResponse = await fetch(url, config);
                    return this.handleResponse(retryResponse);
                }
                this.clearTokens();
                window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
                const err = new Error('Session expired');
                err.status = 401;
                throw err;
            }
            // Domain 401 — fall through so handleResponse throws the
            // server's error message verbatim, with status attached.
        }

        return this.handleResponse(response);
    }

    async handleResponse(response) {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            // No server-provided message means the route itself misbehaved
            // (404 unknown endpoint, 405 SPA catch-all, 502 proxy...) — name
            // the endpoint and status so the toast is diagnosable.
            let fallback = `Request failed (${response.status})`;
            try {
                fallback += `: ${new URL(response.url).pathname}`;
            } catch { /* keep the status-only message */ }
            const err = new Error(data.error || data.msg || fallback);
            err.status = response.status;
            err.data = data;
            throw err;
        }
        return data;
    }

    async refreshToken() {
        const refreshToken = localStorage.getItem('refresh_token');
        if (!refreshToken) return false;

        try {
            const response = await fetch(`${this.baseUrl}/auth/refresh`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${refreshToken}`,
                },
            });

            if (response.ok) {
                const data = await response.json();
                localStorage.setItem('access_token', data.access_token);
                return true;
            }
            return false;
        } catch {
            return false;
        }
    }
}

export default ApiClient;
