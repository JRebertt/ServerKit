import { Globe, Lock } from 'lucide-react';

// Shared sub-nav for the Domains / SSL page group. DNS records (and per-record
// Dynamic DNS) now live in the Domains drawer, so DNS Zones / Dynamic DNS are no
// longer separate tabs (the demo's top-bar layout replaces the old sidebar
// sub-menu — see docs/REDESIGN_MAP.md §6 decision 3).
export const DOMAIN_TABS = [
    { to: '/domains', labelKey: 'app.domainTabs.domains', label: 'Domains', end: true, icon: <Globe size={15} /> },
    { to: '/ssl', label: 'SSL', icon: <Lock size={15} /> },
];
