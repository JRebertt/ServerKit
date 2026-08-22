// One list behind every "create something new" entry point: the sidebar "+"
// and the command palette's Create tiles. Route-based flows navigate directly;
// flows living in a modal/drawer on a list page deep-link with
// `?focus=create:<kind>`, which the destination opens via useFocusParam.
//
// `more: true` marks the second shelf — hidden behind the palette's
// "+ n more" expander until asked for, like the prototype.
import {
    Activity, Archive, Boxes, Clock, Container, Database, FolderKanban,
    Globe, KeyRound, LayoutGrid, Server, Webhook,
} from 'lucide-react';

export const CREATE_ITEMS = [
    { kind: 'service', labelKey: 'common.labels.service', label: 'Service', icon: Boxes, path: '/services/new' },
    { kind: 'server', labelKey: 'common.labels.server', label: 'Server', icon: Server, path: '/servers?focus=create:server' },
    { kind: 'domain', labelKey: 'common.labels.domain', label: 'Domain', icon: Globe, path: '/domains?focus=create:domain' },
    { kind: 'database', labelKey: 'app.quickCreate.database', label: 'Database', icon: Database, path: '/databases' },
    { kind: 'monitor', labelKey: 'app.quickCreate.monitor', label: 'Monitor', icon: Activity, path: '/monitoring/monitors?focus=create:monitor' },
    { kind: 'cron', labelKey: 'app.quickCreate.cronJob', label: 'Cron job', icon: Clock, path: '/cron?focus=create:cron' },
    { kind: 'backup', labelKey: 'app.quickCreate.backup', label: 'Backup', icon: Archive, path: '/backups' },
    { kind: 'project', labelKey: 'common.labels.project', label: 'Project', icon: FolderKanban, path: '/projects?focus=create:project' },
    { kind: 'workspace', labelKey: 'common.labels.workspace', label: 'Workspace', icon: LayoutGrid, path: '/workspaces?focus=create:workspace' },
    { kind: 'vault', labelKey: 'app.quickCreate.vault', label: 'Vault', icon: KeyRound, path: '/vaults', more: true },
    { kind: 'webhook', labelKey: 'app.quickCreate.webhook', label: 'Webhook', icon: Webhook, path: '/settings/webhooks', more: true },
    { kind: 'container', labelKey: 'app.quickCreate.container', label: 'Container', icon: Container, path: '/docker', more: true },
];

export default CREATE_ITEMS;
