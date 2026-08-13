// Firewall, fail2ban, SSL certificates, ClamAV, file integrity,
// SSH keys, IP lists, security audit, Lynis, auto-updates

// Firewall endpoints
export async function getFirewallStatus() {
    return this.request('/firewall/status');
}

export async function enableFirewall(firewall = null) {
    return this.request('/firewall/enable', {
        method: 'POST',
        body: firewall ? { firewall } : {}
    });
}

export async function disableFirewall(firewall = null) {
    return this.request('/firewall/disable', {
        method: 'POST',
        body: firewall ? { firewall } : {}
    });
}

export async function getFirewallRules(firewall = null) {
    const params = firewall ? `?firewall=${firewall}` : '';
    return this.request(`/firewall/rules${params}`);
}

export async function addFirewallRule(ruleData) {
    return this.request('/firewall/rules', {
        method: 'POST',
        body: ruleData
    });
}

export async function removeFirewallRule(ruleData) {
    return this.request('/firewall/rules', {
        method: 'DELETE',
        body: ruleData
    });
}

export async function blockIP(ip, permanent = true) {
    return this.request('/firewall/block-ip', {
        method: 'POST',
        body: { ip, permanent }
    });
}

export async function unblockIP(ip, permanent = true) {
    return this.request('/firewall/unblock-ip', {
        method: 'POST',
        body: { ip, permanent }
    });
}

export async function getBlockedIPs() {
    return this.request('/firewall/blocked-ips');
}

export async function allowPort(port, protocol = 'tcp', permanent = true) {
    return this.request('/firewall/allow-port', {
        method: 'POST',
        body: { port, protocol, permanent }
    });
}

export async function denyPort(port, protocol = 'tcp', permanent = true) {
    return this.request('/firewall/deny-port', {
        method: 'POST',
        body: { port, protocol, permanent }
    });
}

export async function getFirewallZones() {
    return this.request('/firewall/zones');
}

export async function setDefaultZone(zone) {
    return this.request('/firewall/zones/default', {
        method: 'POST',
        body: { zone }
    });
}

export async function installFirewall(firewall = 'ufw') {
    return this.request('/firewall/install', {
        method: 'POST',
        body: { firewall }
    });
}

// SSL endpoints
export async function getSSLStatus() {
    return this.request('/ssl/status');
}

export async function getCertificates() {
    return this.request('/ssl/certificates');
}

export async function obtainCertificate(data) {
    return this.request('/ssl/certificates', {
        method: 'POST',
        body: data
    });
}

// Panel-wide Let's Encrypt contact, used to prefill certificate forms so the
// same address isn't retyped per certificate.
export async function getAcmeContact() {
    return this.request('/ssl/acme-contact');
}

export async function renewCertificate(domain) {
    return this.request(`/ssl/certificates/${domain}/renew`, { method: 'POST' });
}

export async function renewAllCertificates() {
    return this.request('/ssl/certificates/renew-all', { method: 'POST' });
}

export async function revokeCertificate(domain) {
    return this.request(`/ssl/certificates/${domain}`, { method: 'DELETE' });
}

export async function setupAutoRenewal() {
    return this.request('/ssl/auto-renewal', { method: 'POST' });
}

export async function installCertbot() {
    return this.request('/ssl/install-certbot', { method: 'POST' });
}

// Advanced SSL endpoints — unified under the one /ssl surface (§5). The old
// /ssl/advanced/* paths still resolve (deprecated alias).
export async function getSSLProfiles() {
    return this.request('/ssl/profiles');
}

export async function issueWildcardCert(domain, dnsProvider, credentials) {
    return this.request('/ssl/wildcard', {
        method: 'POST', body: { domain, dns_provider: dnsProvider, credentials }
    });
}

export async function issueSANCert(domains) {
    return this.request('/ssl/san', {
        method: 'POST', body: { domains }
    });
}

export async function uploadCustomCert(domain, certificate, privateKey, chain) {
    return this.request('/ssl/upload', {
        method: 'POST', body: { domain, certificate, private_key: privateKey, chain }
    });
}

export async function getSSLHealth(domain) {
    return this.request(`/ssl/health/${domain}`);
}

export async function getSSLExpiryAlerts(days = 30) {
    return this.request(`/ssl/expiry-alerts?days=${days}`);
}

// Security (ClamAV, File Integrity) endpoints
export async function getSecurityStatus() {
    return this.request('/security/status');
}

export async function getSecurityConfig() {
    return this.request('/security/config');
}

export async function updateSecurityConfig(config) {
    return this.request('/security/config', {
        method: 'PUT',
        body: config
    });
}

export async function getClamAVStatus() {
    return this.request('/security/clamav/status');
}

export async function installClamAV() {
    return this.request('/security/clamav/install', { method: 'POST' });
}

export async function updateVirusDefinitions() {
    return this.request('/security/clamav/update', { method: 'POST' });
}

export async function startClamAV() {
    return this.request('/security/clamav/start', { method: 'POST' });
}

export async function scanFile(path) {
    return this.request('/security/scan/file', {
        method: 'POST',
        body: { path }
    });
}

export async function scanDirectory(path, recursive = true) {
    return this.request('/security/scan/directory', {
        method: 'POST',
        body: { path, recursive }
    });
}

export async function getScanStatus() {
    return this.request('/security/scan/status');
}

export async function cancelScan() {
    return this.request('/security/scan/cancel', { method: 'POST' });
}

export async function getScanHistory(limit = 50) {
    return this.request(`/security/scan/history?limit=${limit}`);
}

export async function runQuickScan() {
    return this.request('/security/scan/quick', { method: 'POST' });
}

export async function runFullScan() {
    return this.request('/security/scan/full', { method: 'POST' });
}

export async function scanApp(appId) {
    // Job-backed malware scan (YARA + ClamAV) of an app's docroot → { job_id }
    return this.request(`/security/scan/app/${appId}`, { method: 'POST' });
}

export async function scanPathJob(path) {
    return this.request('/security/scan/job', {
        method: 'POST',
        body: { path }
    });
}

// YARA web-shell rules
export async function getYaraRules() {
    return this.request('/security/yara/rules');
}

export async function uploadYaraRule(filename, content) {
    return this.request('/security/yara/rules', {
        method: 'POST',
        body: { filename, content }
    });
}

export async function deleteYaraRule(filename) {
    return this.request(`/security/yara/rules/${encodeURIComponent(filename)}`, {
        method: 'DELETE'
    });
}

export async function getQuarantinedFiles() {
    return this.request('/security/quarantine');
}

export async function quarantineFile(path) {
    return this.request('/security/quarantine', {
        method: 'POST',
        body: { path }
    });
}

export async function deleteQuarantinedFile(filename) {
    return this.request(`/security/quarantine/${encodeURIComponent(filename)}`, {
        method: 'DELETE'
    });
}

export async function restoreQuarantinedFile(filename) {
    return this.request(`/security/quarantine/${encodeURIComponent(filename)}/restore`, {
        method: 'POST'
    });
}

export async function initializeIntegrityDatabase(paths = null) {
    return this.request('/security/integrity/initialize', {
        method: 'POST',
        body: paths ? { paths } : {}
    });
}

export async function checkFileIntegrity() {
    return this.request('/security/integrity/check');
}

export async function getFailedLogins(hours = 24) {
    return this.request(`/security/failed-logins?hours=${hours}`);
}

export async function getSecurityEvents(limit = 100) {
    return this.request(`/security/events?limit=${limit}`);
}

// Fail2ban endpoints
export async function getFail2banStatus() {
    return this.request('/security/fail2ban/status');
}

export async function installFail2ban() {
    return this.request('/security/fail2ban/install', { method: 'POST' });
}

export async function getFail2banJailStatus(jail) {
    return this.request(`/security/fail2ban/jails/${jail}`);
}

export async function getAllFail2banBans() {
    return this.request('/security/fail2ban/bans');
}

export async function fail2banUnban(ip, jail = null) {
    return this.request('/security/fail2ban/unban', {
        method: 'POST',
        body: { ip, jail }
    });
}

export async function fail2banBan(ip, jail = 'sshd') {
    return this.request('/security/fail2ban/ban', {
        method: 'POST',
        body: { ip, jail }
    });
}

// SSH Key endpoints
export async function getSSHKeys(user = 'root') {
    return this.request(`/security/ssh-keys?user=${user}`);
}

export async function addSSHKey(key, user = 'root') {
    return this.request('/security/ssh-keys', {
        method: 'POST',
        body: { key, user }
    });
}

export async function removeSSHKey(keyId, user = 'root') {
    return this.request(`/security/ssh-keys/${keyId}?user=${user}`, {
        method: 'DELETE'
    });
}

// IP Lists endpoints
export async function getIPLists() {
    return this.request('/security/ip-lists');
}

export async function addToIPList(ip, listType, comment = '') {
    return this.request(`/security/ip-lists/${listType}`, {
        method: 'POST',
        body: { ip, comment }
    });
}

export async function removeFromIPList(ip, listType) {
    return this.request(`/security/ip-lists/${listType}/${encodeURIComponent(ip)}`, {
        method: 'DELETE'
    });
}

// Security Audit endpoints
export async function generateSecurityAudit() {
    return this.request('/security/audit');
}

// Lynis (Vulnerability Scanning) endpoints
export async function getLynisStatus() {
    return this.request('/security/lynis/status');
}

export async function installLynis() {
    return this.request('/security/lynis/install', { method: 'POST' });
}

export async function runLynisScan() {
    return this.request('/security/lynis/scan', { method: 'POST' });
}

export async function getLynisScanStatus() {
    return this.request('/security/lynis/scan/status');
}

// Auto Updates endpoints
export async function getAutoUpdatesStatus() {
    return this.request('/security/auto-updates/status');
}

export async function installAutoUpdates() {
    return this.request('/security/auto-updates/install', { method: 'POST' });
}

export async function enableAutoUpdates() {
    return this.request('/security/auto-updates/enable', { method: 'POST' });
}

export async function disableAutoUpdates() {
    return this.request('/security/auto-updates/disable', { method: 'POST' });
}
