// Shared vocabulary for the monitor surfaces (list, detail, overview, incidents).
// Keeping the status mapping in one place stops the list and the detail page
// disagreeing about what "degraded" looks like.

export const CHECK_TYPES = [
    { value: 'http', label: 'HTTP', hint: 'status code of a URL' },
    { value: 'keyword', label: 'Keyword', hint: 'URL must contain a phrase' },
    { value: 'tcp', label: 'Port', hint: 'host:port accepts a connection' },
    { value: 'ping', label: 'Ping', hint: 'host answers ICMP' },
    { value: 'dns', label: 'DNS', hint: 'name resolves' },
    { value: 'smtp', label: 'SMTP', hint: 'mail server greets' },
];

export const MONITOR_STATUS = [
    { value: 'operational', label: 'Operational' },
    { value: 'degraded', label: 'Degraded' },
    { value: 'major_outage', label: 'Down' },
    { value: 'maintenance', label: 'Maintenance' },
    { value: 'paused', label: 'Paused' },
];

// Paused is deliberately not a `status` on the model — it is its own flag, so a
// paused monitor keeps the last thing it knew rather than looking like an
// outage. Resolve it here, once.
export function monitorStateOf(monitor) {
    if (!monitor) return { key: 'unknown', label: 'Unknown', tone: 'gray' };
    if (monitor.is_paused) return { key: 'paused', label: 'Paused', tone: 'gray' };
    switch (monitor.status) {
        case 'operational':
            return { key: 'up', label: 'Operational', tone: 'green' };
        case 'degraded':
        case 'partial_outage':
            return { key: 'degraded', label: 'Degraded', tone: 'amber' };
        case 'major_outage':
            return { key: 'down', label: 'Down', tone: 'red' };
        case 'maintenance':
            return { key: 'maintenance', label: 'Maintenance', tone: 'cyan' };
        default:
            return { key: 'unknown', label: monitor.status || 'Unknown', tone: 'gray' };
    }
}

export const INCIDENT_STATES = ['investigating', 'identified', 'monitoring', 'resolved'];

export const IMPACT_TONE = {
    critical: 'red',
    major: 'red',
    minor: 'amber',
    none: 'gray',
};
