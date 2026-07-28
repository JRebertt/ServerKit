// Static top-level pages for the command palette (plan 41). Extracted from the
// old inline STATIC_PAGES so the palette component stays about orchestration.
//
// `navId` ties a page to its sidebar item id, letting the palette apply the SAME
// workspace nav-permission gate the sidebar uses (a member whose workspace hides
// "servers" shouldn't find the Servers page here). Pages with no navId (e.g.
// Import a Site) have no sidebar item and are always reachable.
//
// The seven hand-typed `Settings: X` rows that used to live here retired in
// favor of data/settingsIndex.js, which indexes settings at the card level.
// WordPress / FTP / Status / GPU / Workflow / Remote-Access / Cloud-Provision
// palette entries are contributed by their extensions (command_palette).

export const PALETTE_PAGES = [
    { label: 'Services', path: '/services', navId: 'services', keywords: 'apps containers' },
    { label: 'Docker', path: '/docker', navId: 'docker', keywords: 'containers images' },
    { label: 'Databases', path: '/databases', navId: 'databases', keywords: 'mysql postgres sql mongo' },
    { label: 'Domains', path: '/domains', navId: 'domains', keywords: 'dns nginx records nameserver zones' },
    { label: 'SSL Certificates', path: '/ssl', navId: 'domains', keywords: 'https tls certificate' },
    { label: 'Templates', path: '/templates', navId: 'services', keywords: 'deploy one-click gallery' },
    { label: 'Deployments', path: '/deployments', navId: 'services', keywords: 'deploy jobs status logs' },
    { label: 'Files', path: '/files', navId: 'files', keywords: 'file manager explorer' },
    { label: 'Monitoring', path: '/monitoring', navId: 'monitoring', keywords: 'metrics uptime observability alerts host health' },
    { label: 'Events', path: '/telemetry', navId: 'monitoring', keywords: 'telemetry metrics observability system events' },
    { label: 'Backups', path: '/backups', navId: 'backups', keywords: 'snapshots restore protection' },
    { label: 'Cron Jobs', path: '/cron', navId: 'cron', keywords: 'schedule tasks' },
    { label: 'Security', path: '/security', navId: 'security', keywords: 'firewall fail2ban' },
    { label: 'Terminal', path: '/terminal', navId: 'terminal', keywords: 'shell ssh console logs' },
    { label: 'Servers', path: '/servers', navId: 'servers', keywords: 'fleet agents' },
    { label: 'Fleet Monitor', path: '/monitoring', navId: 'monitoring', keywords: 'agents status heatmap fleet host health servers' },
    { label: 'Capacity Forecast', path: '/monitoring/capacity', navId: 'monitoring', keywords: 'compare anomaly forecast disk trend' },
    { label: 'Alert Rules', path: '/monitoring/rules', navId: 'monitoring', keywords: 'thresholds limits notifications delivery' },
    { label: 'Extensions', path: '/extensions', navId: 'marketplace', keywords: 'extensions plugins marketplace' },
    { label: 'Downloads', path: '/downloads', navId: 'marketplace', keywords: 'agent installer' },
    { label: 'Import a Site', path: '/imports', keywords: 'import migrate cpanel directadmin hestia backup adoption move existing' },
    { label: 'Projects', path: '/projects', navId: 'organization', keywords: 'organization group' },
    { label: 'Shared Variables', path: '/shared-variables', navId: 'organization', keywords: 'env secrets shared' },
    { label: 'Workspaces', path: '/workspaces', navId: 'organization', keywords: 'organization team' },
    { label: 'Vaults', path: '/vaults', navId: 'organization', keywords: 'secrets tokens credentials vault' },
    { label: 'Queue Bus', path: '/queue', navId: 'queue', keywords: 'bus operations tasks' },
    { label: 'Jobs', path: '/monitoring/jobs', navId: 'monitoring', keywords: 'scheduler background work' },
    { label: 'Monitors', path: '/monitoring/monitors', navId: 'monitoring', keywords: 'uptime check probe http ping website' },
    { label: 'Incidents', path: '/monitoring/incidents', navId: 'monitoring', keywords: 'outage alert downtime postmortem' },
    // No navId: the inbound-webhook console is a Settings tab now, not a
    // sidebar page, so there's no nav item for the permission gate to consult.
    { label: 'Webhooks', path: '/settings/webhooks', keywords: 'webhook receive forward delivery inbound' },
].map((p) => ({ ...p, id: `page:${p.path}`, category: 'Pages' }));

export default PALETTE_PAGES;
