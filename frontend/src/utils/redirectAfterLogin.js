// Remembers where someone was headed when auth bounced them to /login, so
// they land there instead of on the dashboard.
//
// This exists because deep links into the panel are now a real entry point:
// serverkit.ai install links (/extensions?install=<slug>,
// /templates?install=<id>) arrive from README badges and are, by definition,
// clicked by people who may not have an open session. Dropping the query
// string on the way through login made every one of those links land on a
// bare dashboard with no explanation.
//
// sessionStorage rather than react-router's location.state: the SSO flow
// leaves the origin entirely for the identity provider and comes back through
// /login/callback/<provider>, and router state cannot survive that. One
// mechanism that covers every path beats two that each cover half.

const STORAGE_KEY = 'serverkit.redirectAfterLogin';

// How long a parked destination stays good. Long enough to cover a password
// manager, a TOTP prompt, or an SSO round trip that includes signing up at the
// provider; short enough that a destination abandoned earlier in the tab
// session does not resurface on an unrelated login and read as a glitch.
const MAX_AGE_MS = 30 * 60 * 1000;

// A path far longer than any real panel route is not a destination.
const MAX_PATH_LENGTH = 2048;

// Landing back on one of these after login is either a loop or nonsense.
const AUTH_PATH_PREFIXES = ['/login', '/register', '/setup', '/migrate', '/logout'];

/**
 * Validate a stored destination before we navigate to it.
 *
 * Returns the path, or null when it is unusable. Same-origin is enforced by
 * shape: a destination must be one absolute path and nothing else. `//evil.com`
 * and `/\evil.com` are the two that matter — browsers read both as
 * protocol-relative URLs, so either would turn login into an open redirect.
 */
export function sanitizeRedirect(path) {
    if (typeof path !== 'string' || !path) return null;
    if (path.length > MAX_PATH_LENGTH) return null;
    if (path[0] !== '/') return null;
    if (path[1] === '/' || path[1] === '\\') return null;
    // Control characters (newline, tab, NUL) can smuggle a value past the
    // shape checks above once something downstream re-parses it.
    // eslint-disable-next-line no-control-regex
    if (/[\u0000-\u001f\u007f]/.test(path)) return null;

    const pathname = path.split(/[?#]/)[0];

    // Dot segments, plain or percent-encoded, in any position. They collapse:
    // `/..//evil.com` normalizes to `//evil.com`, which is only same-origin
    // while it is resolved against a base — hand that same string to
    // `window.location.href` and it leaves the site. Nothing in this app needs
    // a dot segment, so refuse the gadget rather than reason about every
    // consumer of the value.
    if (pathname.split('/').some((segment) => segment === '.' || segment === '..')) return null;
    if (/%2e/i.test(pathname)) return null;

    // Prefix match with a "/" boundary, case-insensitive: catches /login/ and
    // /login/callback/<provider> (which would re-run the SSO callback with no
    // code and show an error), while leaving /logins and /login-help valid.
    const lowered = pathname.toLowerCase();
    if (AUTH_PATH_PREFIXES.some((p) => lowered === p || lowered.startsWith(`${p}/`))) {
        return null;
    }

    return path;
}

/** Store where the visitor was going. Call this before redirecting to /login. */
export function rememberRedirect(location) {
    if (!location) return;
    const path = sanitizeRedirect(
        `${location.pathname || ''}${location.search || ''}${location.hash || ''}`,
    );
    if (!path || path === '/') return; // the dashboard is already the default
    try {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ path, at: Date.now() }));
    } catch {
        // Storage unavailable — fall back to the dashboard, as before.
    }
}

/**
 * Read and clear the stored destination, falling back to the dashboard.
 * Re-validates on the way out: the value is same-origin sessionStorage, but a
 * post-login navigation is not the place to trust that assumption.
 */
export function consumeRedirect() {
    let raw = null;
    try {
        raw = window.sessionStorage.getItem(STORAGE_KEY);
        window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
        return '/';
    }
    if (!raw) return '/';

    let stored;
    try {
        stored = JSON.parse(raw);
    } catch {
        return '/';
    }
    if (!stored || typeof stored !== 'object') return '/';

    // A missing, non-numeric, or future timestamp is treated as expired rather
    // than trusted: rememberRedirect is the only writer, so anything else is
    // not a value this module put there.
    const at = Number(stored.at);
    if (!Number.isFinite(at) || at > Date.now() || Date.now() - at > MAX_AGE_MS) {
        return '/';
    }

    return sanitizeRedirect(stored.path) || '/';
}
