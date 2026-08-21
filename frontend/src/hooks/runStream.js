export const TERMINAL_RUN_STATUSES = new Set(['succeeded', 'failed', 'cancelled']);
export const MAX_RUN_LOG_LINES = 5000;

export function isTerminalRunStatus(status) {
    return TERMINAL_RUN_STATUSES.has(status);
}

export function mergeRunLogLines(previous, incoming, seenIds, maxLines = MAX_RUN_LOG_LINES) {
    if (!Array.isArray(incoming) || incoming.length === 0) {
        return { lines: previous, maxId: 0 };
    }

    const fresh = [];
    let maxId = 0;
    for (const line of incoming) {
        if (line?.id != null) {
            const key = String(line.id);
            if (seenIds.has(key)) continue;
            seenIds.add(key);
            const numericId = Number(line.id);
            if (Number.isFinite(numericId)) maxId = Math.max(maxId, numericId);
        }
        fresh.push(line);
    }

    if (fresh.length === 0) return { lines: previous, maxId };
    const combined = previous.concat(fresh);
    return {
        lines: combined.length > maxLines ? combined.slice(-maxLines) : combined,
        maxId,
    };
}
