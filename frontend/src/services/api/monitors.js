// Monitors — synthetic uptime checks (http / keyword / tcp / dns / smtp / ping)
// and the incidents they raise. Core API: /api/v1/monitors.

export async function getMonitors(params = {}) {
    const query = new URLSearchParams();
    if (params.status) query.append('status', params.status);
    if (params.type) query.append('type', params.type);
    if (params.q) query.append('q', params.q);
    if (params.page_id != null) query.append('page_id', params.page_id);
    const suffix = query.toString() ? `?${query}` : '';
    return this.request(`/monitors${suffix}`);
}

export async function getMonitorStats() {
    return this.request('/monitors/stats');
}

export async function getMonitor(monitorId) {
    return this.request(`/monitors/${monitorId}`);
}

export async function createMonitor(data) {
    return this.request('/monitors', {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function updateMonitor(monitorId, data) {
    return this.request(`/monitors/${monitorId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
    });
}

export async function deleteMonitor(monitorId) {
    return this.request(`/monitors/${monitorId}`, { method: 'DELETE' });
}

export async function runMonitorCheck(monitorId) {
    return this.request(`/monitors/${monitorId}/check`, { method: 'POST' });
}

export async function setMonitorPaused(monitorId, paused) {
    return this.request(`/monitors/${monitorId}/pause`, {
        method: 'POST',
        body: JSON.stringify({ paused }),
    });
}

export async function getMonitorHistory(monitorId, params = {}) {
    const query = new URLSearchParams();
    if (params.hours) query.append('hours', params.hours);
    if (params.limit) query.append('limit', params.limit);
    const suffix = query.toString() ? `?${query}` : '';
    return this.request(`/monitors/${monitorId}/history${suffix}`);
}

export async function getMonitorUptime(monitorId, days = 90) {
    return this.request(`/monitors/${monitorId}/uptime?days=${days}`);
}

// --- Incidents ---

export async function getIncidents(params = {}) {
    const query = new URLSearchParams();
    if (params.state) query.append('state', params.state);
    if (params.limit) query.append('limit', params.limit);
    const suffix = query.toString() ? `?${query}` : '';
    return this.request(`/monitors/incidents${suffix}`);
}

export async function createIncident(data) {
    return this.request('/monitors/incidents', {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function updateIncident(incidentId, data) {
    return this.request(`/monitors/incidents/${incidentId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
    });
}

export async function deleteIncident(incidentId) {
    return this.request(`/monitors/incidents/${incidentId}`, { method: 'DELETE' });
}
