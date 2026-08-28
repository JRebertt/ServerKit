// WordPress standalone endpoints (from api.js, NOT the separate wordpress.js service)

// Route registered by the external standalone-WP extension; Sidebar only
// calls this when a plugin nav item requires wpInstalled, and a 404 reads
// as "not installed". The rest of the old standalone lifecycle wrappers
// (install/uninstall/start/stop/restart/requirements) had no callers and
// no backend routes anywhere — removed with the route-contract test.
export async function getWordPressStatus() {
    return this.request('/wordpress/standalone/status');
}
