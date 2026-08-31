// Cloudflare operations — zone settings (SSL/TLS, Speed, Caching, Security) and
// one-click hardening, layered on the existing Cloudflare DNS connection. Zones
// are addressed by their ServerKit DNS zone id (same as the /dns API).
//
// The extension's own /api/v1/cloudflare client, built on the panel's
// ApiClient via the SDK singleton — moved out of the host's services/api/
// with the zone-ops surface (plan 52 Phase 2). The DNS-record layer and the
// Cloudflare connection itself stay core (they back /domains).
import { api } from 'serverkit-sdk';

async function getCloudflareZoneSettings(zoneId) {
    return api.request(`/cloudflare/zones/${zoneId}/settings`);
}

async function getCloudflareZoneSetting(zoneId, settingId) {
    return api.request(`/cloudflare/zones/${zoneId}/settings/${settingId}`);
}

async function updateCloudflareZoneSetting(zoneId, settingId, value) {
    return api.request(`/cloudflare/zones/${zoneId}/settings/${settingId}`, {
        method: 'PATCH',
        body: { value },
    });
}

async function applyCloudflareSettingsPreset(zoneId) {
    return api.request(`/cloudflare/zones/${zoneId}/settings/apply-preset`, {
        method: 'POST',
    });
}

// Purge the zone's Cloudflare cache. payload is { purge_everything: true } or
// { files: [...] } (and on Enterprise, hosts/prefixes/tags).
async function purgeCloudflareCache(zoneId, payload) {
    return api.request(`/cloudflare/zones/${zoneId}/purge-cache`, {
        method: 'POST',
        body: payload,
    });
}

// WAF custom firewall rules (http_request_firewall_custom phase).
async function getCloudflareWafRules(zoneId) {
    return api.request(`/cloudflare/zones/${zoneId}/waf/rules`);
}

async function addCloudflareWafRule(zoneId, rule) {
    return api.request(`/cloudflare/zones/${zoneId}/waf/rules`, {
        method: 'POST',
        body: rule,
    });
}

async function applyCloudflareWafPreset(zoneId, presetKey, params = {}) {
    return api.request(`/cloudflare/zones/${zoneId}/waf/presets/${presetKey}`, {
        method: 'POST',
        body: { params },
    });
}

async function updateCloudflareWafRule(zoneId, rulesetId, ruleId, fields) {
    return api.request(`/cloudflare/zones/${zoneId}/waf/rulesets/${rulesetId}/rules/${ruleId}`, {
        method: 'PATCH',
        body: fields,
    });
}

async function deleteCloudflareWafRule(zoneId, rulesetId, ruleId) {
    return api.request(`/cloudflare/zones/${zoneId}/waf/rulesets/${rulesetId}/rules/${ruleId}`, {
        method: 'DELETE',
    });
}

// Workers (edge hosting). Account is resolved from the zone server-side.
async function getCloudflareWorkers(zoneId) {
    return api.request(`/cloudflare/zones/${zoneId}/workers`);
}

async function deployCloudflareWorker(zoneId, payload) {
    return api.request(`/cloudflare/zones/${zoneId}/workers`, {
        method: 'POST',
        body: payload,
    });
}

async function deleteCloudflareWorker(zoneId, name) {
    return api.request(`/cloudflare/zones/${zoneId}/workers/${encodeURIComponent(name)}`, {
        method: 'DELETE',
    });
}

async function addCloudflareWorkerRoute(zoneId, pattern, script) {
    return api.request(`/cloudflare/zones/${zoneId}/workers/routes`, {
        method: 'POST',
        body: { pattern, script },
    });
}

async function deleteCloudflareWorkerRoute(zoneId, routeId) {
    return api.request(`/cloudflare/zones/${zoneId}/workers/routes/${routeId}`, {
        method: 'DELETE',
    });
}

// Cloudflare Tunnels (cloudflared) — expose a local service through the edge.
async function getCloudflareTunnels(zoneId) {
    return api.request(`/cloudflare/zones/${zoneId}/tunnels`);
}

async function createCloudflareTunnel(zoneId, name) {
    return api.request(`/cloudflare/zones/${zoneId}/tunnels`, {
        method: 'POST',
        body: { name },
    });
}

async function deleteCloudflareTunnel(zoneId, tunnelId) {
    return api.request(`/cloudflare/zones/${zoneId}/tunnels/${tunnelId}`, {
        method: 'DELETE',
    });
}

async function getCloudflareTunnelInstall(zoneId, tunnelId) {
    return api.request(`/cloudflare/zones/${zoneId}/tunnels/${tunnelId}/install`);
}

async function getCloudflareTunnelHostnames(zoneId, tunnelId) {
    return api.request(`/cloudflare/zones/${zoneId}/tunnels/${tunnelId}/hostnames`);
}

async function addCloudflareTunnelHostname(zoneId, tunnelId, hostname, service) {
    return api.request(`/cloudflare/zones/${zoneId}/tunnels/${tunnelId}/hostnames`, {
        method: 'POST',
        body: { hostname, service },
    });
}

async function removeCloudflareTunnelHostname(zoneId, tunnelId, hostname) {
    return api.request(`/cloudflare/zones/${zoneId}/tunnels/${tunnelId}/hostnames`, {
        method: 'DELETE',
        body: { hostname },
    });
}

// Developer platform — R2 buckets, KV namespaces, D1 databases (account-scoped).
async function getCloudflareStorage(zoneId) {
    return api.request(`/cloudflare/zones/${zoneId}/storage`);
}

async function createCloudflareR2Bucket(zoneId, name) {
    return api.request(`/cloudflare/zones/${zoneId}/storage/r2`, {
        method: 'POST',
        body: { name },
    });
}

async function deleteCloudflareR2Bucket(zoneId, name) {
    return api.request(`/cloudflare/zones/${zoneId}/storage/r2/${encodeURIComponent(name)}`, {
        method: 'DELETE',
    });
}

async function createCloudflareKvNamespace(zoneId, title) {
    return api.request(`/cloudflare/zones/${zoneId}/storage/kv`, {
        method: 'POST',
        body: { title },
    });
}

async function deleteCloudflareKvNamespace(zoneId, namespaceId) {
    return api.request(`/cloudflare/zones/${zoneId}/storage/kv/${namespaceId}`, {
        method: 'DELETE',
    });
}

async function createCloudflareD1Database(zoneId, name) {
    return api.request(`/cloudflare/zones/${zoneId}/storage/d1`, {
        method: 'POST',
        body: { name },
    });
}

async function deleteCloudflareD1Database(zoneId, databaseId) {
    return api.request(`/cloudflare/zones/${zoneId}/storage/d1/${databaseId}`, {
        method: 'DELETE',
    });
}

const cloudflareApi = {
    getCloudflareZoneSettings,
    getCloudflareZoneSetting,
    updateCloudflareZoneSetting,
    applyCloudflareSettingsPreset,
    purgeCloudflareCache,
    getCloudflareWafRules,
    addCloudflareWafRule,
    applyCloudflareWafPreset,
    updateCloudflareWafRule,
    deleteCloudflareWafRule,
    getCloudflareWorkers,
    deployCloudflareWorker,
    deleteCloudflareWorker,
    addCloudflareWorkerRoute,
    deleteCloudflareWorkerRoute,
    getCloudflareTunnels,
    createCloudflareTunnel,
    deleteCloudflareTunnel,
    getCloudflareTunnelInstall,
    getCloudflareTunnelHostnames,
    addCloudflareTunnelHostname,
    removeCloudflareTunnelHostname,
    getCloudflareStorage,
    createCloudflareR2Bucket,
    deleteCloudflareR2Bucket,
    createCloudflareKvNamespace,
    deleteCloudflareKvNamespace,
    createCloudflareD1Database,
    deleteCloudflareD1Database,
};

export default cloudflareApi;
