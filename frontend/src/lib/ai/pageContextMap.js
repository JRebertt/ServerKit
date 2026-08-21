// Maps the current route to a human-readable context label + entity ids the
// assistant can use ("this server", "this app"), plus per-page suggested
// prompts for the empty state. Ordered: first matching pattern wins.

const ROUTES = [
    { re: /^\/docker(\/|$)/, labelKey: 'app.pageContextMap.docker', label: 'Docker', entity: 'docker' },
    { re: /^\/services\/([^/]+)$/, labelKey: 'app.pageContextMap.service', label: 'Service', entity: 'service', idKey: 'service_id' },
    { re: /^\/services(\/|$)/, labelKey: 'app.pageContextMap.services', label: 'Services', entity: 'services' },
    { re: /^\/apps\/([^/]+)/, labelKey: 'app.pageContextMap.application', label: 'Application', entity: 'app', idKey: 'app_id' },
    { re: /^\/apps(\/|$)/, labelKey: 'app.pageContextMap.applications', label: 'Applications', entity: 'apps' },
    { re: /^\/databases(\/|$)/, labelKey: 'app.pageContextMap.databases', label: 'Databases', entity: 'databases' },
    { re: /^\/wordpress\/([^/]+)/, labelKey: 'app.pageContextMap.wordpressSite', label: 'WordPress site', entity: 'wp_site', idKey: 'site_id' },
    { re: /^\/wordpress(\/|$)/, labelKey: 'app.pageContextMap.wordpress', label: 'WordPress', entity: 'wordpress' },
    { re: /^\/servers\/([^/]+)/, labelKey: 'app.pageContextMap.server', label: 'Server', entity: 'server', idKey: 'server_id' },
    { re: /^\/servers(\/|$)/, labelKey: 'app.pageContextMap.servers', label: 'Servers', entity: 'servers' },
    { re: /^\/fleet/, labelKey: 'app.pageContextMap.fleet', label: 'Fleet', entity: 'fleet' },
    { re: /^\/monitoring(\/|$)/, labelKey: 'app.pageContextMap.monitoring', label: 'Monitoring', entity: 'monitoring' },
    { re: /^\/security(\/|$)/, labelKey: 'app.pageContextMap.security', label: 'Security', entity: 'security' },
    { re: /^\/backups(\/|$)/, labelKey: 'app.pageContextMap.backups', label: 'Backups', entity: 'backups' },
    { re: /^\/dns(\/|$)/, label: 'DNS', entity: 'dns' },
    { re: /^\/domains(\/|$)/, labelKey: 'app.pageContextMap.domains', label: 'Domains', entity: 'domains' },
    { re: /^\/files(\/|$)/, labelKey: 'app.pageContextMap.fileManager', label: 'File Manager', entity: 'files' },
    { re: /^\/extensions/, labelKey: 'app.pageContextMap.extensions', label: 'Extensions', entity: 'marketplace' },
    { re: /^\/$/, labelKey: 'app.pageContextMap.dashboard', label: 'Dashboard', entity: 'dashboard' },
];

const SUGGESTED = {
    docker: ['List my running containers', "Why might a container keep restarting?"],
    apps: ['List my applications and their status', 'Which apps are unhealthy?'],
    app: ['Summarize the status of this application'],
    databases: ['List my databases', 'How big is each database?'],
    monitoring: ["What's my current CPU, memory, and disk usage?"],
    servers: ['List the servers in my fleet'],
    server: ["Summarize this server's health"],
    dashboard: ['What can you do?', "Give me a quick health summary of this panel"],
};

const GLOBAL_SUGGESTED = ['What can you do?', "What's my system's CPU and memory usage?"];

export function getCoreContext(pathname, params = {}) {
    for (const entry of ROUTES) {
        const m = pathname.match(entry.re);
        if (!m) continue;
        const ids = {};
        if (entry.idKey && m[1]) ids[entry.idKey] = m[1];
        // Merge any router params (covers deeper routes).
        for (const [k, v] of Object.entries(params || {})) {
            if (v != null) ids[k] = v;
        }
        return { route: pathname, label: entry.label, entity: entry.entity, ids };
    }
    return { route: pathname, labelKey: 'app.pageContextMap.dashboard2', label: 'Dashboard', entity: 'dashboard', ids: {} };
}

export function getSuggestedPrompts(entity) {
    return SUGGESTED[entity] || GLOBAL_SUGGESTED;
}
