import {
    LayoutDashboard, Shield, Ban, Key, Network, Radar, ShieldOff,
    FileCheck, ScrollText, Bug, RefreshCw, Bell, Settings,
} from 'lucide-react';

// Shared sub-nav for the Security page group. Rendered in the shared PageTopbar
// tabs so every section lives in the page top bar — matching the Domains/
// Services top-bar layout (see docs/REDESIGN_MAP.md §6 decision 3). There are 13
// sections, more than fit on one row, so the PageTopbar collapses the overflow
// into a "More" menu. All sections render from the single Security page, keyed
// off the /security/:tab route.
export const SECURITY_TABS = [
    { to: '/security', labelKey: 'common.labels.overview', label: 'Overview', end: true, icon: <LayoutDashboard size={15} /> },
    { to: '/security/firewall', labelKey: 'app.securityTabs.firewall', label: 'Firewall', icon: <Shield size={15} /> },
    { to: '/security/fail2ban', labelKey: 'app.securityTabs.fail2ban', label: 'Fail2ban', icon: <Ban size={15} /> },
    { to: '/security/ssh-keys', labelKey: 'app.securityTabs.sshKeys', label: 'SSH Keys', icon: <Key size={15} /> },
    { to: '/security/ip-lists', labelKey: 'app.securityTabs.ipLists', label: 'IP Lists', icon: <Network size={15} /> },
    { to: '/security/scanner', labelKey: 'app.securityTabs.malwareScanner', label: 'Malware Scanner', icon: <Radar size={15} /> },
    { to: '/security/quarantine', labelKey: 'app.securityTabs.quarantine', label: 'Quarantine', icon: <ShieldOff size={15} /> },
    { to: '/security/integrity', labelKey: 'app.securityTabs.fileIntegrity', label: 'File Integrity', icon: <FileCheck size={15} /> },
    { to: '/security/audit', labelKey: 'app.securityTabs.audit', label: 'Audit', icon: <ScrollText size={15} /> },
    { to: '/security/vulnerability', labelKey: 'app.securityTabs.vulnerabilityScan', label: 'Vulnerability Scan', icon: <Bug size={15} /> },
    { to: '/security/updates', labelKey: 'app.securityTabs.autoUpdates', label: 'Auto Updates', icon: <RefreshCw size={15} /> },
    { to: '/security/events', labelKey: 'app.securityTabs.events', label: 'Events', icon: <Bell size={15} /> },
    { to: '/security/settings', labelKey: 'common.labels.settings', label: 'Settings', icon: <Settings size={15} /> },
];
