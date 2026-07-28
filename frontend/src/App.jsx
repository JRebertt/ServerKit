import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ToastProvider } from './contexts/ToastContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { LayoutProvider } from './contexts/LayoutContext';
import { ResourceTierProvider } from './contexts/ResourceTierContext';
import { NotificationsProvider } from './contexts/NotificationsContext';
import { Toaster } from './components/ui/sonner';
import ThemeSync from './components/ThemeSync';
import DashboardLayout from './layouts/DashboardLayout';
import AppLoader from './components/AppLoader';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import Register from './pages/Register';
import Setup from './pages/Setup';
import Docker from './pages/Docker';
import Databases from './pages/Databases';
import Domains from './pages/Domains';
import Monitoring from './pages/Monitoring';
import Backups from './pages/Backups';
import Terminal from './pages/Terminal';
import Settings from './pages/Settings';
import FileManager from './pages/FileManager';
// Firewall is now part of Security page
import CronJobs from './pages/CronJobs';
import Security from './pages/Security';
import Services from './pages/Services';
import NewService from './pages/new-service/NewService';
import ImportWizard from './pages/ImportWizard';
import Coexistence from './pages/Coexistence';
import ServiceDetail from './pages/ServiceDetail';
import Templates from './pages/Templates';
import Servers from './pages/Servers';
import ServerDetail from './pages/ServerDetail';
import AgentFleet from './pages/AgentFleet';
import TabGroupLayout from './layouts/TabGroupLayout';
import { SERVER_TABS } from './components/servers/serverTabs';
import { DOMAIN_TABS } from './components/domains/domainTabs';
import { SERVICE_TABS } from './components/services/serviceTabs';
import { FILE_TABS } from './components/files/fileTabs';
import { MONITOR_TABS } from './components/monitoring/monitorTabs';
import { MARKET_TABS } from './components/marketplace/marketTabs';
import { BACKUP_TABS } from './components/backups/backupTabs';
import { SECURITY_TABS } from './components/security/securityTabs';
import { ORG_TABS } from './components/organization/organizationTabs';
import { JOBS_TABS } from './components/jobs/jobsTabs';
import Downloads from './pages/Downloads';
import SSLCertificates from './pages/SSLCertificates';
import SSOCallback from './pages/SSOCallback';
import SourceConnectionCallback from './pages/SourceConnectionCallback';
import GithubAppCallback from './pages/GithubAppCallback';
import DatabaseMigration from './pages/DatabaseMigration';
import ServerTemplates from './pages/ServerTemplates';
import Workspaces from './pages/Workspaces';
import WorkspaceDetail from './pages/WorkspaceDetail';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import SharedVariables from './pages/SharedVariables';
import FleetProxy from './pages/FleetProxy';
import PublicStatusPage from './pages/PublicStatusPage';
import Marketplace from './pages/Marketplace';
import Vaults from './pages/Vaults';
import StyleGuide from './pages/StyleGuide';
import NotFound from './pages/NotFound';
import AppMap from './pages/AppMap';
import Documentation from './pages/Documentation';
import Deployments from './pages/Deployments';
import DeployConsole from './pages/DeployConsole';
import QueueOperations from './pages/QueueOperations';
import QueueDetail from './pages/QueueDetail';
import Notifications from './pages/Notifications';
import DeliveryLog from './pages/DeliveryLog';
import Telemetry from './pages/Telemetry';
import Jobs from './pages/Jobs';
import TestSandbox from './pages/TestSandbox';
import useDevMode from './hooks/useDevMode';
import useExtensionRoutes from './plugins/ExtensionRoutes';
import { useContributions } from './plugins/contributions';

// Page title mapping
const PAGE_TITLES = {
    '/': 'Dashboard',
    '/login': 'Login',
    '/register': 'Register',
    '/setup': 'Setup',
    '/services': 'Services',
    '/services/new': 'New Service',
    '/imports': 'Import a Site',
    '/imports/coexistence': 'Running Alongside Another Panel',
    '/projects': 'Projects',
    '/shared-variables': 'Shared Variables',
    '/fleet-proxy': 'Fleet Proxy',
    // WordPress list-page titles come from the serverkit-wordpress manifest
    // (page_titles) now; the dynamic detail-page fallbacks below stay in core.
    '/templates': 'Templates',
    '/deployments': 'Deployment Activity',
    '/domains': 'Domains',
    '/databases': 'Databases',
    '/ssl': 'SSL Certificates',
    '/docker': 'Docker',
    '/servers': 'Servers',
    '/downloads': 'Downloads',
    '/files': 'File Manager',
    '/observability': 'Monitoring',
    '/monitoring': 'Monitoring',
    '/backups': 'Backups',
    '/cron': 'Cron Jobs',
    '/security': 'Security',
    '/terminal': 'Terminal',
    '/settings': 'Settings',
    '/connections/callback/github': 'GitHub Connection',
    '/connections/github-app/callback': 'GitHub Setup',
    '/migrate': 'Database Migration',
    '/fleet': 'Agent Fleet',
    '/agent-plugins': 'Extensions',
    '/server-templates': 'Server Templates',
    '/workspaces': 'Workspaces',
    '/workspaces/:id': 'Workspace',
    '/workspaces/:id/overview': 'Workspace Overview',
    '/workspaces/:id/servers': 'Workspace Servers',
    '/workspaces/:id/services': 'Workspace Services',
    '/workspaces/:id/sites': 'Workspace Sites',
    '/workspaces/:id/members': 'Workspace Members',
    '/workspaces/:id/settings': 'Workspace Settings',
    '/workspaces/:id/settings/general': 'Workspace Settings',
    '/workspaces/:id/settings/navigation': 'Workspace Navigation Permissions',
    '/dns': 'DNS Zones',
    '/extensions': 'Extensions',
    '/extensions/installed': 'Installed Extensions',
    '/vaults': 'Vaults',
    '/style-guide': 'Style Guide',
    '/app-map': 'App Map',
    '/documentation': 'Documentation',
    '/dynamic-dns': 'Dynamic DNS',
    '/queue': 'Queue Bus',
    '/notifications': 'Notifications',
    '/admin/notifications': 'Notification Delivery Log',
    '/telemetry': 'Telemetry',
    '/jobs': 'Jobs',
    '/test-sandbox': 'Test Sandbox',
};

// /apps/* is the legacy URL space for what is now "Services" (§1 unification).
// The list route already redirects; this preserves deep links to a single app
// (and its active tab) by forwarding to the matching /services/* path.
function LegacyAppRedirect() {
    const { id, tab } = useParams();
    const suffix = [id, tab].filter(Boolean).join('/');
    return <Navigate to={`/services/${suffix}`} replace />;
}

function PageTitleUpdater() {
    const location = useLocation();
    const { page_titles: pluginTitles } = useContributions();
    const { panelTitle, publicTitle } = useAuth();

    useEffect(() => {
        const path = location.pathname;
        let title = PAGE_TITLES[path] || (pluginTitles && pluginTitles[path]);

        // Handle dynamic routes and tab sub-routes
        if (!title) {
            if (path.startsWith('/workspaces/')) {
                const parts = path.split('/');
                const tab = parts[3];
                const section = parts[4];
                if (tab === 'settings' && section) {
                    title = PAGE_TITLES[`/workspaces/:id/settings/${section}`] || 'Workspace Settings';
                } else if (tab) {
                    title = PAGE_TITLES[`/workspaces/:id/${tab}`] || 'Workspace';
                } else {
                    title = 'Workspace';
                }
            }
            // Check if it's a base page with a tab suffix (e.g., /security/firewall)
            else {
                const basePath = '/' + path.split('/')[1];
                if (PAGE_TITLES[basePath]) {
                    title = PAGE_TITLES[basePath];
                } else if (pluginTitles && pluginTitles[basePath]) {
                    title = pluginTitles[basePath];
                } else if (path.startsWith('/services/')) title = 'Service Details';
                else if (path.startsWith('/servers/')) title = 'Server Details';
                else if (path.startsWith('/wordpress/pipelines/') || path.startsWith('/wordpress/projects/')) title = 'WordPress Pipeline';
                else if (path.startsWith('/wordpress/')) title = 'WordPress Site';
                else title = '';
            }
        }

        // Public (pre-auth) routes stay brand-neutral; the app interior uses the panel brand.
        const isPublicRoute = ['/login', '/register', '/setup', '/forgot'].some(p => path.startsWith(p));
        const brand = isPublicRoute ? (publicTitle || 'Control Panel') : (panelTitle || 'ServerKit');
        document.title = title ? `${title} | ${brand}` : brand;
    }, [location, pluginTitles, panelTitle, publicTitle]);

    return null;
}

// Guard for developer-only pages (Test Sandbox). Reads the same shared flag as
// the sidebar's requiresCondition: 'devMode', so the nav entry and the route can
// never disagree. Off ⇒ the URL behaves as if the page doesn't exist.
function DevOnlyRoute({ children }) {
    const { devMode, resolved } = useDevMode({ withStatus: true });
    if (!resolved) return <AppLoader />;
    if (!devMode) return <Navigate to="/" replace />;
    return children;
}

function PrivateRoute({ children }) {
    const { isAuthenticated, loading, needsSetup, needsMigration } = useAuth();

    if (loading) {
        return <AppLoader />;
    }

    // Priority: migrations > setup > auth
    if (needsMigration) {
        return <Navigate to="/migrate" />;
    }

    if (needsSetup) {
        return <Navigate to="/setup" />;
    }

    return isAuthenticated ? children : <Navigate to="/login" />;
}

function PublicRoute({ children }) {
    const { isAuthenticated, loading, needsSetup, needsMigration } = useAuth();

    if (loading) {
        return <AppLoader />;
    }

    // Priority: migrations > setup > auth
    if (needsMigration) {
        return <Navigate to="/migrate" />;
    }

    if (needsSetup) {
        return <Navigate to="/setup" />;
    }

    return isAuthenticated ? <Navigate to="/" /> : children;
}

function SetupRoute({ children }) {
    const { loading, needsSetup, isAuthenticated } = useAuth();

    if (loading) {
        return <AppLoader />;
    }

    // If setup is not needed, redirect appropriately
    if (!needsSetup) {
        return isAuthenticated ? <Navigate to="/" /> : <Navigate to="/login" />;
    }

    return children;
}

function LegacyGitExtRedirect() {
    const { tab } = useParams();
    return <Navigate to={tab ? `/git/${tab}` : '/git'} replace />;
}

function AppRoutes() {
    const { dashboardRoutes, groupRoutes, standaloneGroups } = useExtensionRoutes();
    return (
        <Routes>
            <Route path="/migrate" element={<DatabaseMigration />} />
            <Route path="/setup" element={
                <SetupRoute>
                    <Setup />
                </SetupRoute>
            } />
            <Route path="/login" element={
                <PublicRoute>
                    <Login />
                </PublicRoute>
            } />
            <Route path="/login/callback/:provider" element={
                <PublicRoute>
                    <SSOCallback />
                </PublicRoute>
            } />
            <Route path="/register" element={
                <PublicRoute>
                    <Register />
                </PublicRoute>
            } />
            <Route path="/connections/callback/:provider" element={
                <PrivateRoute>
                    <SourceConnectionCallback />
                </PrivateRoute>
            } />
            <Route path="/connections/github-app/callback" element={
                <PrivateRoute>
                    <GithubAppCallback />
                </PrivateRoute>
            } />
            <Route path="/status/:slug" element={<PublicStatusPage />} />
            {/* Standalone plugin layouts — bare or custom. Each group is
                a sibling top-level Route under PrivateRoute, so the
                plugin owns the chrome (no DashboardLayout sidebar). */}
            {standaloneGroups.map((group) => {
                const Layout = group.LayoutComponent;
                return (
                    <Route
                        key={`standalone:${group.layoutId}`}
                        element={<PrivateRoute><Layout /></PrivateRoute>}
                    >
                        {group.routes}
                    </Route>
                );
            })}
            <Route path="/" element={
                <PrivateRoute>
                    <DashboardLayout />
                </PrivateRoute>
            }>
                <Route index element={<Dashboard />} />
                {/* Tab groups — each parent TabGroupLayout renders the shared
                    PageTopbar + sub-nav once and swaps only the routed content
                    below, so the tabs act like real tabs (no full-page remount)
                    and keep the group's sidebar item lit. Detail / full-bleed
                    routes (services/:id, wordpress/:id, …) stay outside. */}
                <Route element={<TabGroupLayout tabs={SERVICE_TABS} />}>
                    <Route path="services" element={<Services />} />
                    <Route path="services/new" element={<NewService />} />
                    <Route path="templates" element={<Templates />} />
                    <Route path="deployments" element={<Deployments />} />
                    <Route path="deployments/:jobId" element={<DeployConsole />} />
                </Route>
                <Route path="services/:id" element={<ServiceDetail />} />
                <Route path="services/:id/:tab" element={<ServiceDetail />} />
                {/* Settings sub-section in the URL (e.g. .../settings/git)
                    so the Settings left-nav is shareable and survives a refresh. */}
                <Route path="services/:id/:tab/:section" element={<ServiceDetail />} />
                <Route path="imports" element={<ImportWizard />} />
                <Route path="imports/coexistence" element={<Coexistence />} />
                <Route path="apps" element={<Navigate to="/services" replace />} />
                <Route path="apps/:id" element={<LegacyAppRedirect />} />
                <Route path="apps/:id/:tab" element={<LegacyAppRedirect />} />
                {/* WordPress moved into the serverkit-wordpress builtin extension
                    (Phase 5 #38). It contributes a single splat route wordpress/*
                    via its manifest and self-renders the whole sub-router (tab
                    group + full-bleed detail + legacy /projects redirects), so all
                    the WordPress routing now lives in the extension. */}
                {/* The React-Flow Workflow Builder (serverkit-workflows) was
                    retired in plan 45; the Automations extension (tramo) replaces
                    it. Keep the old /workflow path working by redirecting. */}
                <Route path="workflow" element={<Navigate to="/automations" replace />} />
                <Route element={<TabGroupLayout tabs={DOMAIN_TABS} />}>
                    <Route path="domains" element={<Domains />} />
                    <Route path="ssl" element={<SSLCertificates />} />
                </Route>
                {/* DNS Zones + Dynamic DNS were merged into the Domains surface
                    (records + per-record Dynamic DNS live in the domain drawer) —
                    keep the old paths working by redirecting. */}
                <Route path="dns" element={<Navigate to="/domains" replace />} />
                <Route path="dynamic-dns" element={<Navigate to="/domains" replace />} />
                {/* Cloudflare zone settings moved into the serverkit-cloudflare-ops
                    builtin extension (#36); it contributes the
                    cloudflare/zones/:zoneId route via its manifest. Reached from the
                    "Open in Cloudflare" button on a Cloudflare-managed domain. */}
                <Route path="databases" element={<Databases />} />
                <Route path="databases/:tab" element={<Databases />} />
                <Route path="docker" element={<Docker />} />
                <Route path="docker/:tab" element={<Docker />} />
                {/* /cloud and /remote-access are now the serverkit-cloud-provision
                    and serverkit-remote-access builtin extensions: they join this
                    group via tabs contributions + group-nested routes
                    (groupRoutes.servers). */}
                <Route element={<TabGroupLayout tabs={SERVER_TABS} groupId="servers" />}>
                    <Route path="servers" element={<Servers />} />
                    <Route path="fleet" element={<AgentFleet />} />
                    <Route path="fleet-proxy" element={<FleetProxy />} />
                    <Route path="server-templates" element={<ServerTemplates />} />
                    {groupRoutes.servers}
                </Route>
                <Route path="servers/:id" element={<ServerDetail />} />
                <Route path="servers/:id/:tab" element={<ServerDetail />} />
                <Route path="agent-plugins" element={<Navigate to="/extensions" replace />} />
                {/* Organization tab group — Projects / Shared Variables /
                    Workspaces share one PageTopbar + tabs (ORG_TABS) instead of
                    a collapsible sidebar sub-menu. Detail routes stay outside. */}
                <Route element={<TabGroupLayout tabs={ORG_TABS} />}>
                    <Route path="projects" element={<Projects />} />
                    <Route path="shared-variables" element={<SharedVariables />} />
                    <Route path="vaults" element={<Vaults />} />
                    <Route path="workspaces" element={<Workspaces />} />
                </Route>
                <Route path="projects/:id" element={<ProjectDetail />} />
                <Route path="projects/:id/:tab" element={<ProjectDetail />} />
                <Route path="workspaces/:id" element={<WorkspaceDetail />} />
                <Route path="workspaces/:id/:tab" element={<WorkspaceDetail />} />
                <Route path="workspaces/:id/:tab/:section" element={<WorkspaceDetail />} />
                <Route element={<TabGroupLayout tabs={MARKET_TABS} />}>
                    <Route path="extensions" element={<Marketplace />} />
                    <Route path="extensions/installed" element={<Marketplace />} />
                    <Route path="downloads" element={<Downloads />} />
                </Route>
                {/* Old /marketplace paths redirect to /extensions (renamed for clarity). */}
                <Route path="marketplace" element={<Navigate to="/extensions" replace />} />
                <Route path="marketplace/installed" element={<Navigate to="/extensions/installed" replace />} />
                <Route path="style-guide" element={<StyleGuide />} />
                <Route path="style-guide/:tab" element={<StyleGuide />} />
                <Route path="app-map" element={<AppMap />} />
                <Route path="app-map/:tab" element={<AppMap />} />
                <Route path="documentation" element={<Documentation />} />
                <Route path="firewall" element={<Navigate to="/security/firewall" replace />} />
                <Route path="git-ext" element={<LegacyGitExtRedirect />} />
                <Route path="git-ext/:tab" element={<LegacyGitExtRedirect />} />
                {/* /ftp is now the serverkit-ftp builtin extension: it joins
                    this group via a tabs contribution + group-nested routes
                    (groupRoutes.files), so tab + page disappear together when
                    it's uninstalled. */}
                <Route element={<TabGroupLayout tabs={FILE_TABS} groupId="files" />}>
                    <Route path="files" element={<FileManager />} />
                    {groupRoutes.files}
                </Route>
                {/* Observability tab group (§4): Monitoring / Events / Status
                    Pages share one PageTopbar. /observability lands on Monitoring. */}
                {/* /status-pages is now the serverkit-status builtin extension
                    (tabs contribution + group-nested route, groupRoutes.monitoring);
                    the public /status/:slug route stays core above. */}
                <Route element={<TabGroupLayout tabs={MONITOR_TABS} groupId="monitoring" />}>
                    <Route path="monitoring" element={<Monitoring />} />
                    <Route path="monitoring/:tab" element={<Monitoring />} />
                    <Route path="telemetry" element={<Telemetry />} />
                    {groupRoutes.monitoring}
                </Route>
                <Route path="observability" element={<Navigate to="/monitoring" replace />} />
                {/* Fleet Monitor folded into /monitoring: it asked the same
                    questions at fleet scope, so its heatmap is now the Host
                    health grid on the overview (click a card to re-scope the
                    page) and its analytics are the Capacity tab. */}
                <Route path="fleet-monitor" element={<Navigate to="/monitoring" replace />} />
                {/* /gpu is contributed by the standalone serverkit-gpu extension. */}
                <Route element={<TabGroupLayout tabs={BACKUP_TABS} />}>
                    <Route path="backups" element={<Backups />} />
                    <Route path="backups/:tab" element={<Backups />} />
                </Route>
                <Route path="cron" element={<CronJobs />} />
                {/* Security tab group. groupId="security" (plan 47 Phase 3a) lets
                    extracted security features (fail2ban, clamav, …) contribute
                    tabs + group-nested routes via their manifests, so they return
                    as tabs in the place users know. */}
                <Route element={<TabGroupLayout tabs={SECURITY_TABS} groupId="security" />}>
                    <Route path="security" element={<Security />} />
                    <Route path="security/:tab" element={<Security />} />
                    {groupRoutes.security}
                </Route>
                {/* Email routes are gated by the Email module toggle
                    (Settings → Modules); disabled ⇒ redirect to the dashboard. */}
                {/* /email is now the serverkit-email builtin extension (contributes
                    the route via its manifest). */}
                <Route path="terminal" element={<Terminal />} />
                <Route path="terminal/terminal" element={<Navigate to="/terminal/shell" replace />} />
                <Route path="terminal/:tab" element={<Terminal />} />
                {/* Retired "Secrets & Webhooks" page: Vaults moved into the
                    Organization tab group (/vaults); the inbound-webhook console
                    is now a Settings → Admin tab (it's server configuration, not
                    a daily ops surface). Redirect old links/bookmarks. */}
                <Route path="webhooks" element={<Navigate to="/settings/webhooks" replace />} />
                <Route path="secrets/webhooks" element={<Navigate to="/settings/webhooks" replace />} />
                <Route path="secrets" element={<Navigate to="/vaults" replace />} />
                <Route path="secrets/:tab" element={<Navigate to="/vaults" replace />} />
                <Route path="queue" element={<QueueOperations />} />
                {/* Developer tooling, not an operator surface — see the
                    matching requiresCondition on the sidebar item. */}
                <Route path="test-sandbox" element={<DevOnlyRoute><TestSandbox /></DevOnlyRoute>} />
                <Route path="queue/:groupSlug/:queueSlug" element={<QueueDetail />} />
                <Route path="notifications" element={<Notifications />} />
                <Route path="admin/notifications" element={<DeliveryLog />} />
                <Route element={<TabGroupLayout tabs={JOBS_TABS} />}>
                    <Route path="jobs" element={<Jobs />} />
                    <Route path="jobs/scheduled" element={<Jobs />} />
                </Route>
                <Route path="settings" element={<Settings />} />
                <Route path="settings/:tab" element={<Settings />} />
                {dashboardRoutes}
                {/* Catch-all: an unknown URL, or an extension route whose
                    extension isn't installed (never registered above). Renders
                    inside the dashboard chrome instead of a blank page. */}
                <Route path="*" element={<NotFound />} />
            </Route>
        </Routes>
    );
}

function App() {
    return (
        <Router>
            <ThemeProvider>
                <LayoutProvider>
                    <AuthProvider>
                        {/* Inside AuthProvider — PageTitleUpdater reads panelTitle/
                            publicTitle via useAuth (branding), so it must sit under
                            the provider. It stays inside Router for useLocation. */}
                        <PageTitleUpdater />
                        <ThemeSync />
                        <ResourceTierProvider>
                            <ToastProvider>
                                <NotificationsProvider>
                                    <AppRoutes />
                                </NotificationsProvider>
                                <Toaster />
                            </ToastProvider>
                        </ResourceTierProvider>
                    </AuthProvider>
                </LayoutProvider>
            </ThemeProvider>
        </Router>
    );
}

export default App;
