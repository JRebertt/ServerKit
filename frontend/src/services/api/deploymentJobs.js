// Deployment jobs and logs

export async function getDeploymentJobs(params = {}) {
    const query = new URLSearchParams();
    if (params.status) query.append('status', params.status);
    if (params.appId) query.append('app_id', params.appId);
    if (params.serverId) query.append('server_id', params.serverId);
    if (params.limit) query.append('limit', params.limit);
    const suffix = query.toString() ? `?${query}` : '';
    return this.request(`/deployment-jobs${suffix}`);
}

export async function getDeploymentJob(jobId, includeLogs = true, includePlan = false) {
    const query = new URLSearchParams({ logs: String(includeLogs) });
    if (includePlan) query.append('plan', 'true');
    return this.request(`/deployment-jobs/${jobId}?${query}`);
}

export async function getDeploymentJobLogs(jobId, afterId = null) {
    const suffix = afterId ? `?after_id=${afterId}` : '';
    return this.request(`/deployment-jobs/${jobId}/logs${suffix}`);
}

// Retry a failed deployment job — clones it and enqueues a fresh run (plan 51
// D8). Returns { job_id, job } for the new job so the console can swap to it.
export async function retryDeploymentJob(jobId) {
    return this.request(`/deployment-jobs/${jobId}/retry`, { method: 'POST' });
}

// Simulated deployments (plan 51.5 dev tool). The GET 404s when the backend
// gate (DEMO_DEPLOYS_ENABLED) is off — callers treat that as "hidden".
export async function getDeploySimulateInfo() {
    return this.request('/deployment-jobs/simulate');
}

export async function simulateDeployment(scenario, speed = 'fast') {
    return this.request('/deployment-jobs/simulate', {
        method: 'POST',
        body: { scenario, speed },
    });
}
