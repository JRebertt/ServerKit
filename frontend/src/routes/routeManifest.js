/**
 * Core route descriptor contract.
 *
 * @typedef {'root' | 'dashboard'} RoutePlacement
 * @typedef {'public' | 'private' | 'setup'} RouteGuard
 * @typedef {Object} CoreRoute
 * @property {string} id Stable identity used by tests and diagnostics.
 * @property {string} path Absolute React Router path (or `*` for the dashboard fallback).
 * @property {RoutePlacement} placement Router level where the route is mounted.
 * @property {string=} component Key in routeComponents.jsx.
 * @property {string=} redirect Absolute redirect destination.
 * @property {'apps' | 'git-extension'=} legacyRedirect Parameter-aware legacy redirect.
 * @property {RouteGuard=} guard Root-route authentication policy.
 * @property {string=} group Dashboard tab-group identity.
 * @property {string=} title Browser title before the panel brand.
 * @property {string=} titlePath Optional exact title-only path for a parameterized route.
 * @property {boolean=} index Whether this is the dashboard index route.
 * @property {boolean=} devOnly Whether the page is hidden outside developer mode.
 * @property {Record<string, Record<string, string>>=} titleByParam Title overrides keyed by parameter.
 */

/** @type {ReadonlyArray<Readonly<CoreRoute>>} */
export const CORE_ROUTES = Object.freeze([
    { id: 'migration', path: '/migrate', placement: 'root', component: 'DatabaseMigration', title: 'Database Migration' },
    { id: 'setup', path: '/setup', placement: 'root', component: 'Setup', guard: 'setup', title: 'Setup' },
    { id: 'login', path: '/login', placement: 'root', component: 'Login', guard: 'public', title: 'Login' },
    { id: 'sso-callback', path: '/login/callback/:provider', placement: 'root', component: 'SSOCallback', guard: 'public', title: 'Login' },
    { id: 'register', path: '/register', placement: 'root', component: 'Register', guard: 'public', title: 'Register' },
    { id: 'connection-callback', path: '/connections/callback/:provider', placement: 'root', component: 'SourceConnectionCallback', guard: 'private', title: 'GitHub Connection', titlePath: '/connections/callback/github' },
    { id: 'github-app-callback', path: '/connections/github-app/callback', placement: 'root', component: 'GithubAppCallback', guard: 'private', title: 'GitHub Setup' },
    { id: 'public-status', path: '/status/:slug', placement: 'root', component: 'PublicStatusPage' },

    { id: 'dashboard', path: '/', placement: 'dashboard', component: 'Dashboard', title: 'Dashboard', index: true },
    { id: 'services', path: '/services', placement: 'dashboard', group: 'services', component: 'Services', title: 'Services' },
    { id: 'new-service', path: '/services/new', placement: 'dashboard', group: 'services', component: 'NewService', title: 'New Service' },
    { id: 'templates', path: '/templates', placement: 'dashboard', group: 'services', component: 'Templates', title: 'Templates' },
    { id: 'deployments', path: '/deployments', placement: 'dashboard', group: 'services', component: 'Deployments', title: 'Deployment Activity' },
    { id: 'deploy-console', path: '/deployments/:jobId', placement: 'dashboard', group: 'services', component: 'DeployConsole', title: 'Deployment Activity' },
    { id: 'service-detail', path: '/services/:id', placement: 'dashboard', component: 'ServiceDetail', title: 'Services' },
    { id: 'service-detail-tab', path: '/services/:id/:tab', placement: 'dashboard', component: 'ServiceDetail', title: 'Services' },
    { id: 'service-detail-section', path: '/services/:id/:tab/:section', placement: 'dashboard', component: 'ServiceDetail', title: 'Services' },
    { id: 'imports', path: '/imports', placement: 'dashboard', component: 'ImportWizard', title: 'Import a Site' },
    { id: 'imports-coexistence', path: '/imports/coexistence', placement: 'dashboard', component: 'Coexistence', title: 'Running Alongside Another Panel' },
    { id: 'legacy-apps', path: '/apps', placement: 'dashboard', redirect: '/services' },
    { id: 'legacy-app-detail', path: '/apps/:id', placement: 'dashboard', legacyRedirect: 'apps' },
    { id: 'legacy-app-tab', path: '/apps/:id/:tab', placement: 'dashboard', legacyRedirect: 'apps' },
    { id: 'legacy-workflow', path: '/workflow', placement: 'dashboard', redirect: '/automations' },

    { id: 'domains', path: '/domains', placement: 'dashboard', group: 'domains', component: 'Domains', title: 'Domains' },
    { id: 'ssl', path: '/ssl', placement: 'dashboard', group: 'domains', component: 'SSLCertificates', title: 'SSL Certificates' },
    { id: 'legacy-dns', path: '/dns', placement: 'dashboard', redirect: '/domains', title: 'DNS Zones' },
    { id: 'legacy-dynamic-dns', path: '/dynamic-dns', placement: 'dashboard', redirect: '/domains', title: 'Dynamic DNS' },
    { id: 'databases', path: '/databases', placement: 'dashboard', component: 'Databases', title: 'Databases' },
    { id: 'databases-tab', path: '/databases/:tab', placement: 'dashboard', component: 'Databases', title: 'Databases' },
    { id: 'docker', path: '/docker', placement: 'dashboard', component: 'Docker', title: 'Docker' },
    { id: 'docker-tab', path: '/docker/:tab', placement: 'dashboard', component: 'Docker', title: 'Docker' },

    { id: 'servers', path: '/servers', placement: 'dashboard', group: 'servers', component: 'Servers', title: 'Servers' },
    { id: 'fleet', path: '/fleet', placement: 'dashboard', group: 'servers', component: 'AgentFleet', title: 'Agent Fleet' },
    { id: 'fleet-proxy', path: '/fleet-proxy', placement: 'dashboard', group: 'servers', component: 'FleetProxy', title: 'Fleet Proxy' },
    { id: 'server-templates', path: '/server-templates', placement: 'dashboard', group: 'servers', component: 'ServerTemplates', title: 'Server Templates' },
    { id: 'server-detail', path: '/servers/:id', placement: 'dashboard', component: 'ServerDetail', title: 'Servers' },
    { id: 'server-detail-tab', path: '/servers/:id/:tab', placement: 'dashboard', component: 'ServerDetail', title: 'Servers' },
    { id: 'legacy-agent-plugins', path: '/agent-plugins', placement: 'dashboard', redirect: '/extensions', title: 'Extensions' },

    { id: 'projects', path: '/projects', placement: 'dashboard', group: 'organization', component: 'Projects', title: 'Projects' },
    { id: 'shared-variables', path: '/shared-variables', placement: 'dashboard', group: 'organization', component: 'SharedVariables', title: 'Shared Variables' },
    { id: 'vaults', path: '/vaults', placement: 'dashboard', group: 'organization', component: 'Vaults', title: 'Vaults' },
    { id: 'workspaces', path: '/workspaces', placement: 'dashboard', group: 'organization', component: 'Workspaces', title: 'Workspaces' },
    { id: 'project-detail', path: '/projects/:id', placement: 'dashboard', component: 'ProjectDetail', title: 'Projects' },
    { id: 'project-detail-tab', path: '/projects/:id/:tab', placement: 'dashboard', component: 'ProjectDetail', title: 'Projects' },
    { id: 'workspace-detail', path: '/workspaces/:id', placement: 'dashboard', component: 'WorkspaceDetail', title: 'Workspace' },
    {
        id: 'workspace-detail-tab', path: '/workspaces/:id/:tab', placement: 'dashboard', component: 'WorkspaceDetail', title: 'Workspace',
        titleByParam: { tab: { overview: 'Workspace Overview', servers: 'Workspace Servers', services: 'Workspace Services', sites: 'Workspace Sites', members: 'Workspace Members', settings: 'Workspace Settings' } },
    },
    {
        id: 'workspace-detail-section', path: '/workspaces/:id/:tab/:section', placement: 'dashboard', component: 'WorkspaceDetail', title: 'Workspace',
        titleByParam: {
            tab: { settings: 'Workspace Settings' },
            section: { general: 'Workspace Settings', navigation: 'Workspace Navigation Permissions' },
        },
    },

    { id: 'extensions', path: '/extensions', placement: 'dashboard', group: 'marketplace', component: 'Marketplace', title: 'Extensions' },
    { id: 'installed-extensions', path: '/extensions/installed', placement: 'dashboard', group: 'marketplace', component: 'Marketplace', title: 'Installed Extensions' },
    { id: 'downloads', path: '/downloads', placement: 'dashboard', group: 'marketplace', component: 'Downloads', title: 'Downloads' },
    { id: 'legacy-marketplace', path: '/marketplace', placement: 'dashboard', redirect: '/extensions' },
    { id: 'legacy-marketplace-installed', path: '/marketplace/installed', placement: 'dashboard', redirect: '/extensions/installed' },
    { id: 'style-guide', path: '/style-guide', placement: 'dashboard', component: 'StyleGuide', title: 'Style Guide' },
    { id: 'style-guide-tab', path: '/style-guide/:tab', placement: 'dashboard', component: 'StyleGuide', title: 'Style Guide' },
    { id: 'app-map', path: '/app-map', placement: 'dashboard', component: 'AppMap', title: 'App Map' },
    { id: 'app-map-tab', path: '/app-map/:tab', placement: 'dashboard', component: 'AppMap', title: 'App Map' },
    { id: 'documentation', path: '/documentation', placement: 'dashboard', component: 'Documentation', title: 'Documentation' },
    { id: 'legacy-firewall', path: '/firewall', placement: 'dashboard', redirect: '/security/firewall' },
    { id: 'legacy-git-extension', path: '/git-ext', placement: 'dashboard', legacyRedirect: 'git-extension' },
    { id: 'legacy-git-extension-tab', path: '/git-ext/:tab', placement: 'dashboard', legacyRedirect: 'git-extension' },

    { id: 'files', path: '/files', placement: 'dashboard', group: 'files', component: 'FileManager', title: 'File Manager' },
    { id: 'monitoring', path: '/monitoring', placement: 'dashboard', group: 'monitoring', component: 'Monitoring', title: 'Monitoring' },
    { id: 'monitors', path: '/monitoring/monitors', placement: 'dashboard', group: 'monitoring', component: 'Monitors', title: 'Monitors' },
    { id: 'incidents', path: '/monitoring/incidents', placement: 'dashboard', group: 'monitoring', component: 'Incidents', title: 'Incidents' },
    { id: 'legacy-alerts', path: '/monitoring/alerts', placement: 'dashboard', group: 'monitoring', redirect: '/monitoring/incidents' },
    { id: 'legacy-fleet-alerts', path: '/monitoring/fleet-alerts', placement: 'dashboard', group: 'monitoring', redirect: '/monitoring/incidents' },
    { id: 'jobs', path: '/monitoring/jobs', placement: 'dashboard', group: 'monitoring', component: 'Jobs', title: 'Jobs' },
    { id: 'scheduled-jobs', path: '/monitoring/jobs/scheduled', placement: 'dashboard', group: 'monitoring', component: 'Jobs', title: 'Monitoring' },
    { id: 'errors', path: '/monitoring/errors', placement: 'dashboard', group: 'monitoring', component: 'Errors', title: 'Errors' },
    { id: 'monitoring-tab', path: '/monitoring/:tab', placement: 'dashboard', group: 'monitoring', component: 'Monitoring', title: 'Monitoring' },
    { id: 'telemetry', path: '/telemetry', placement: 'dashboard', group: 'monitoring', component: 'Telemetry', title: 'Telemetry' },
    { id: 'monitor-detail', path: '/monitoring/monitors/:monitorId', placement: 'dashboard', component: 'MonitorDetail', title: 'Monitoring' },
    { id: 'legacy-observability', path: '/observability', placement: 'dashboard', redirect: '/monitoring', title: 'Monitoring' },
    { id: 'legacy-fleet-monitor', path: '/fleet-monitor', placement: 'dashboard', redirect: '/monitoring' },

    { id: 'backups', path: '/backups', placement: 'dashboard', group: 'backups', component: 'Backups', title: 'Backups' },
    { id: 'backups-tab', path: '/backups/:tab', placement: 'dashboard', group: 'backups', component: 'Backups', title: 'Backups' },
    { id: 'cron', path: '/cron', placement: 'dashboard', component: 'CronJobs', title: 'Cron Jobs' },
    { id: 'security', path: '/security', placement: 'dashboard', group: 'security', component: 'Security', title: 'Security' },
    { id: 'security-tab', path: '/security/:tab', placement: 'dashboard', group: 'security', component: 'Security', title: 'Security' },
    { id: 'terminal', path: '/terminal', placement: 'dashboard', component: 'Terminal', title: 'Terminal' },
    { id: 'legacy-terminal', path: '/terminal/terminal', placement: 'dashboard', redirect: '/terminal/shell' },
    { id: 'terminal-tab', path: '/terminal/:tab', placement: 'dashboard', component: 'Terminal', title: 'Terminal' },
    { id: 'legacy-webhooks', path: '/webhooks', placement: 'dashboard', redirect: '/settings/webhooks' },
    { id: 'legacy-secret-webhooks', path: '/secrets/webhooks', placement: 'dashboard', redirect: '/settings/webhooks' },
    { id: 'legacy-secrets', path: '/secrets', placement: 'dashboard', redirect: '/vaults' },
    { id: 'legacy-secrets-tab', path: '/secrets/:tab', placement: 'dashboard', redirect: '/vaults' },
    { id: 'queue', path: '/queue', placement: 'dashboard', component: 'QueueOperations', title: 'Queue Bus' },
    { id: 'test-sandbox', path: '/test-sandbox', placement: 'dashboard', component: 'TestSandbox', title: 'Test Sandbox', devOnly: true },
    { id: 'queue-detail', path: '/queue/:groupSlug/:queueSlug', placement: 'dashboard', component: 'QueueDetail', title: 'Queue Bus' },
    { id: 'notifications', path: '/notifications', placement: 'dashboard', component: 'Notifications', title: 'Notifications' },
    { id: 'notification-delivery-log', path: '/admin/notifications', placement: 'dashboard', component: 'DeliveryLog', title: 'Notification Delivery Log' },
    { id: 'legacy-jobs', path: '/jobs', placement: 'dashboard', redirect: '/monitoring/jobs', title: 'Jobs' },
    { id: 'legacy-scheduled-jobs', path: '/jobs/scheduled', placement: 'dashboard', redirect: '/monitoring/jobs/scheduled', title: 'Jobs' },
    { id: 'settings', path: '/settings', placement: 'dashboard', component: 'Settings', title: 'Settings' },
    { id: 'settings-tab', path: '/settings/:tab', placement: 'dashboard', component: 'Settings', title: 'Settings' },
    { id: 'not-found', path: '*', placement: 'dashboard', component: 'NotFound' },
]);

export const ROUTE_GROUP_IDS = Object.freeze([
    'services',
    'domains',
    'servers',
    'organization',
    'marketplace',
    'files',
    'monitoring',
    'backups',
    'security',
]);

export function routesForPlacement(placement) {
    return CORE_ROUTES.filter((route) => route.placement === placement);
}

export function routesForGroup(group) {
    return CORE_ROUTES.filter((route) => route.group === group);
}

function matchPattern(pattern, pathname) {
    const patternParts = pattern.split('/').filter(Boolean);
    const pathParts = pathname.split('/').filter(Boolean);

    if (pattern === '/' && pathname === '/') return { params: {}, score: 1000 };
    if (pattern === '*' || patternParts.length !== pathParts.length) return null;

    const params = {};
    let staticSegments = 0;
    for (let index = 0; index < patternParts.length; index += 1) {
        const expected = patternParts[index];
        const actual = pathParts[index];
        if (expected.startsWith(':')) {
            params[expected.slice(1)] = actual;
        } else if (expected === actual) {
            staticSegments += 1;
        } else {
            return null;
        }
    }

    return { params, score: staticSegments * 100 - patternParts.length };
}

export function resolveCoreRouteTitle(pathname) {
    let best = null;

    for (const route of CORE_ROUTES) {
        if (!route.title) continue;
        const titlePattern = route.titlePath || route.path;
        const match = matchPattern(titlePattern, pathname);
        if (!match || (best && match.score <= best.score)) continue;

        let title = route.title;
        if (route.titleByParam) {
            for (const [param, titles] of Object.entries(route.titleByParam)) {
                title = titles[match.params[param]] || title;
            }
        }
        best = { score: match.score, title };
    }

    return best?.title || '';
}

export function resolveExactCoreRouteTitle(pathname) {
    const route = CORE_ROUTES.find((candidate) => {
        const titlePath = candidate.titlePath || candidate.path;
        return candidate.title && !titlePath.includes(':') && titlePath === pathname;
    });
    return route?.title || '';
}
