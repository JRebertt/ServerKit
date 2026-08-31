// Core Security tabs only. The install-gated tool tabs (Fail2ban, Malware
// Scanner, Quarantine, Vulnerability Scan, Auto Updates) live in their
// security extensions now (serverkit-fail2ban / serverkit-clamav /
// serverkit-lynis / serverkit-auto-updates) and contribute themselves into
// the Security tab group when installed.
export { default as OverviewTab } from './OverviewTab';
export { default as FirewallTab } from './FirewallTab';
export { default as SSHKeysTab } from './SSHKeysTab';
export { default as IPListsTab } from './IPListsTab';
export { default as IntegrityTab } from './IntegrityTab';
export { default as AuditTab } from './AuditTab';
export { default as EventsTab } from './EventsTab';
export { default as SecurityConfigTab } from './SecurityConfigTab';
