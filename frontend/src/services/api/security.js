// Firewall, SSL certificates, file integrity, SSH keys, IP lists and the
// security audit — the core security surfaces. The install-gated tool
// clients (ClamAV/YARA/quarantine, fail2ban, Lynis, auto-updates) moved into
// their security extensions with their tabs (plan 47 Ph3b-4).

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
