// The extension's own /api/v1/email client, built on the panel's ApiClient
// via the SDK singleton (JWT refresh, workspace headers, error normalization
// included) — moved out of the host's services/api/system.js with the page.
//
// Two email surfaces deliberately STAY core and are not duplicated here:
// the DNS-provider connections (/email/dns-providers — a core blueprint that
// keeps its historical prefix) and the Settings → Connections relay tile's
// calls. The relay methods below are this extension's own copies for the
// Relay tab; the page and the Settings tile hit the same endpoints.
import { api } from 'serverkit-sdk';

const emailApi = {
    // Server
    getEmailStatus: () => api.request('/email/status'),
    installEmailServer: (data = {}) => api.request('/email/install', { method: 'POST', body: JSON.stringify(data) }),
    controlEmailService: (component, action) => api.request(`/email/service/${component}/${action}`, { method: 'POST' }),

    // Domains
    getEmailDomains: () => api.request('/email/domains'),
    addEmailDomain: (data) => api.request('/email/domains', { method: 'POST', body: JSON.stringify(data) }),
    getEmailDomain: (domainId) => api.request(`/email/domains/${domainId}`),
    deleteEmailDomain: (domainId) => api.request(`/email/domains/${domainId}`, { method: 'DELETE' }),
    verifyEmailDNS: (domainId) => api.request(`/email/domains/${domainId}/verify-dns`, { method: 'POST' }),
    deployEmailDNS: (domainId) => api.request(`/email/domains/${domainId}/deploy-dns`, { method: 'POST' }),

    // Accounts
    getEmailAccounts: (domainId) => api.request(`/email/domains/${domainId}/accounts`),
    createEmailAccount: (domainId, data) => api.request(`/email/domains/${domainId}/accounts`, { method: 'POST', body: JSON.stringify(data) }),
    getEmailAccount: (accountId) => api.request(`/email/accounts/${accountId}`),
    updateEmailAccount: (accountId, data) => api.request(`/email/accounts/${accountId}`, { method: 'PUT', body: JSON.stringify(data) }),
    deleteEmailAccount: (accountId) => api.request(`/email/accounts/${accountId}`, { method: 'DELETE' }),
    changeEmailPassword: (accountId, password) => api.request(`/email/accounts/${accountId}/password`, { method: 'POST', body: JSON.stringify({ password }) }),

    // Aliases
    getEmailAliases: (domainId) => api.request(`/email/domains/${domainId}/aliases`),
    createEmailAlias: (domainId, data) => api.request(`/email/domains/${domainId}/aliases`, { method: 'POST', body: JSON.stringify(data) }),
    deleteEmailAlias: (aliasId) => api.request(`/email/aliases/${aliasId}`, { method: 'DELETE' }),

    // Forwarding
    getEmailForwarding: (accountId) => api.request(`/email/accounts/${accountId}/forwarding`),
    createEmailForwarding: (accountId, data) => api.request(`/email/accounts/${accountId}/forwarding`, { method: 'POST', body: JSON.stringify(data) }),
    updateEmailForwarding: (ruleId, data) => api.request(`/email/forwarding/${ruleId}`, { method: 'PUT', body: JSON.stringify(data) }),
    deleteEmailForwarding: (ruleId) => api.request(`/email/forwarding/${ruleId}`, { method: 'DELETE' }),

    // Outbound SMTP relay (smarthost)
    getEmailRelay: () => api.request('/email/relay'),
    updateEmailRelay: (data) => api.request('/email/relay', { method: 'PUT', body: JSON.stringify(data) }),
    testEmailRelay: (data) => api.request('/email/relay/test', { method: 'POST', body: JSON.stringify(data) }),
    disableEmailRelay: () => api.request('/email/relay', { method: 'DELETE' }),

    // SpamAssassin
    getSpamConfig: () => api.request('/email/spam/config'),
    updateSpamConfig: (data) => api.request('/email/spam/config', { method: 'PUT', body: JSON.stringify(data) }),
    updateSpamRules: () => api.request('/email/spam/update-rules', { method: 'POST' }),

    // Roundcube webmail
    getWebmailStatus: () => api.request('/email/webmail/status'),
    installWebmail: (data = {}) => api.request('/email/webmail/install', { method: 'POST', body: JSON.stringify(data) }),
    controlWebmail: (action) => api.request(`/email/webmail/service/${action}`, { method: 'POST' }),
    configureWebmailProxy: (domain) => api.request('/email/webmail/configure-proxy', { method: 'POST', body: JSON.stringify({ domain }) }),

    // Mail queue & logs
    getMailQueue: () => api.request('/email/queue'),
    flushMailQueue: () => api.request('/email/queue/flush', { method: 'POST' }),
    deleteMailQueueItem: (queueId) => api.request(`/email/queue/${queueId}`, { method: 'DELETE' }),
    getMailLogs: (lines = 100) => api.request(`/email/logs?lines=${lines}`),
};

export default emailApi;
