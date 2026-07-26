import { Server, Users, FileCog, Network } from 'lucide-react';

// Shared sub-nav for the Servers page group (Servers / Agent Fleet / Fleet
// Proxy / Config Templates). Rendered in each page's
// <PageTopbar tabs={SERVER_TABS}> — the demo's top-bar layout replaces the
// old sidebar sub-menu (see docs/REDESIGN_MAP.md §6 decision 3).
// Fleet Monitor used to sit here; it folded into /monitoring, which was already
// asking the same questions about the panel host.
// The Cloud Servers and Remote Access tabs are contributed by the
// serverkit-cloud-provision and serverkit-remote-access builtin extensions
// (tab-group contribution, #43) and merged in by TabGroupLayout
// groupId="servers". Per-server tunnel management is also available on each
// server's detail page under its "Remote Access" tab (core, unaffected).
export const SERVER_TABS = [
    { to: '/servers', label: 'Servers', end: true, icon: <Server size={15} /> },
    { to: '/fleet', label: 'Agent Fleet', icon: <Users size={15} /> },
    { to: '/fleet-proxy', label: 'Fleet Proxy', icon: <Network size={15} /> },
    { to: '/server-templates', label: 'Config Templates', icon: <FileCog size={15} /> },
];
