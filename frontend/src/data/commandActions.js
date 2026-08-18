// Runnable actions for the command palette (plan 41, Phase 3). Typing `>` filters
// results to this list. v1 ships only safe, non-destructive verbs — openers and
// navigation-with-intent — never blind destructive/exec commands (those belong to
// entity rows with confirm dialogs; see the plan's "Deliberately deferred").
//
// Each action: { id, label, keywords, adminOnly?, suggested?, perform(ctx) }.
// `ctx` = { navigate, toggleTheme, logout, api } is assembled by CommandPalette
// from the app's hooks. `suggested: true` surfaces the action on the empty-query
// screen. Every action still passes the Phase-1 authz filter (adminOnly + nav).

import { copyToClipboard } from '@/utils/clipboard';

export const COMMAND_ACTIONS = [
    {
        id: 'new-service',
        label: 'New Service',
        keywords: 'create app deploy add service container',
        suggested: true,
        perform: ({ navigate }) => navigate('/services/new'),
    },
    {
        id: 'add-server',
        label: 'Add Server',
        keywords: 'connect agent fleet new server node',
        suggested: true,
        perform: ({ navigate }) => navigate('/servers'),
    },
    {
        id: 'add-domain',
        label: 'Add Domain',
        keywords: 'dns new create domain zone',
        perform: ({ navigate }) => navigate('/domains'),
    },
    {
        id: 'new-cron',
        label: 'New Cron Job',
        keywords: 'schedule task create cron job',
        perform: ({ navigate }) => navigate('/cron'),
    },
    {
        id: 'new-backup-policy',
        label: 'New Backup Policy',
        keywords: 'backup schedule protection create policy',
        perform: ({ navigate }) => navigate('/backups'),
    },
    {
        id: 'install-extension',
        label: 'Install Extension',
        keywords: 'marketplace plugin add manual install extension',
        perform: ({ navigate }) => navigate('/extensions'),
    },
    {
        id: 'open-terminal',
        label: 'Open Terminal',
        keywords: 'shell ssh console terminal logs',
        perform: ({ navigate }) => navigate('/terminal'),
    },
    {
        id: 'toggle-theme',
        label: 'Toggle Theme',
        keywords: 'dark light mode appearance theme switch',
        perform: ({ toggleTheme }) => toggleTheme && toggleTheme(),
    },
    {
        id: 'copy-version',
        label: 'Copy Panel Version',
        keywords: 'about build version copy',
        perform: async ({ api }) => {
            try {
                const data = (await (api.getSystemInfo
                    ? api.getSystemInfo()
                    : api.getSystemSettings())) || {};
                const version = data.version || data.app_version || data.panel_version;
                if (version) await copyToClipboard(version);
            } catch {
                /* best-effort clipboard copy — never surface an error */
            }
        },
    },
    {
        id: 'sign-out',
        label: 'Sign Out',
        keywords: 'logout log out exit sign out',
        perform: ({ logout }) => logout && logout(),
    },
];

export default COMMAND_ACTIONS;
