export const MAX_SERVICE_LOG_LINES = 1000;

export function normalizeServiceLogSnapshot(logs) {
    if (Array.isArray(logs)) return logs.map((line) => String(line)).filter(Boolean);
    if (typeof logs !== 'string') return [];
    return logs.split('\n').filter(Boolean);
}

export function appendServiceLogLines(previous, incoming, limit = MAX_SERVICE_LOG_LINES) {
    const nextLines = Array.isArray(incoming) ? incoming : [incoming];
    const combined = previous.concat(nextLines.filter((line) => line != null).map(String));
    return combined.length > limit ? combined.slice(-limit) : combined;
}
