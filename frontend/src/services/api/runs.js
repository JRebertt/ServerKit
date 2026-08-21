export function buildRunLogsPath(runKind, runId, afterId = null) {
    const kind = encodeURIComponent(String(runKind));
    const id = encodeURIComponent(String(runId));
    const suffix = afterId == null ? '' : `?after_id=${encodeURIComponent(String(afterId))}`;
    return `/runs/${kind}/${id}/logs${suffix}`;
}

export async function getRunLogs(runKind, runId, afterId = null) {
    return this.request(buildRunLogsPath(runKind, runId, afterId));
}
