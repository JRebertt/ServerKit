export const DEFAULT_SCALE_POLICY = Object.freeze({
    enabled: false,
    service_name: '',
    min_replicas: 1,
    max_replicas: 3,
    cpu_high_percent: 75,
    cpu_low_percent: 25,
    cooldown_seconds: 300,
    current_replicas: 1,
});

function integerOr(value, fallback) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function percentage(value, fallback) {
    return Math.min(100, Math.max(0, integerOr(value, fallback)));
}

export function normalizeScalePolicy(data) {
    return { ...DEFAULT_SCALE_POLICY, ...(data || {}) };
}

export function scalePolicyPayload(form) {
    const minReplicas = Math.max(1, integerOr(form.min_replicas, 1));
    const maxReplicas = Math.max(minReplicas, integerOr(form.max_replicas, minReplicas));

    return {
        enabled: !!form.enabled,
        service_name: String(form.service_name || '').trim(),
        min_replicas: minReplicas,
        max_replicas: maxReplicas,
        cpu_high_percent: percentage(form.cpu_high_percent, 75),
        cpu_low_percent: percentage(form.cpu_low_percent, 25),
        cooldown_seconds: Math.max(0, integerOr(form.cooldown_seconds, 0)),
    };
}

export function replicaTarget(value) {
    return Math.max(1, integerOr(value, 1));
}

export function resolvedReplicaCount(result, requested) {
    return replicaTarget(result?.replicas ?? requested);
}
