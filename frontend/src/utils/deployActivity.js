// Shaping helpers for the Deploy Activity feed (/deployments) and the deploy
// console header. The list endpoint returns a flat job row — no per-step array —
// so the pipeline tick states are derived here from current_step/total_steps/
// status, keeping the feed a single cheap request.

export const KIND_CHIP = {
    app_deploy: 'app',
    template_install: 'template',
    demo_deploy: 'test',
};

export const KIND_LABELS = {
    app_deploy: 'App deploy',
    template_install: 'Template install',
    demo_deploy: 'Test (simulated)',
};

// One tick per pipeline step, coloured by how far the run got.
export function stepTicks(job) {
    const total = job.total_steps || 0;
    const current = job.current_step || 0;
    const ticks = [];
    for (let i = 1; i <= total; i += 1) {
        let state = 'pending';
        if (job.status === 'succeeded') state = 'done';
        else if (i < current) state = 'done';
        else if (i === current) {
            if (job.status === 'failed') state = 'failed';
            else if (job.status === 'running') state = 'running';
            else state = 'done';
        }
        ticks.push(state);
    }
    return ticks;
}

// "main@3f8c1d2", an image tag, or the template ref — whatever identifies what
// was actually deployed. Null when nothing does (a simulated run, say), so
// callers can choose between a fallback and omitting the field entirely.
export function sourceRef(job) {
    if (job.commit_hash) {
        const short = job.commit_hash.slice(0, 7);
        const branch = job.branch || job.result?.branch;
        return branch ? `${branch}@${short}` : short;
    }
    if (job.image_tag) return job.image_tag;
    if (job.kind === 'template_install') return job.result?.template || job.app_name || 'template';
    return null;
}

export function formatDuration(seconds) {
    if (seconds == null) return '—';
    if (seconds < 10) return `${seconds.toFixed(1)}s`;
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s ? `${m}m ${s}s` : `${m}m`;
}

export function relativeTime(iso, now = Date.now()) {
    if (!iso) return '—';
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return '—';
    const mins = (now - t) / 60000;
    if (mins < 1) return 'just now';
    if (mins < 60) return `${Math.floor(mins)}m ago`;
    if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
    return `${Math.floor(mins / 1440)}d ago`;
}

// Day bucket for a run, so the table can group chronologically without printing
// a date on every row. Queued runs are their own bucket — they have no start
// time to place them by, and they are the ones worth reading first.
//
// The hand-rolled orderer that used to sit here went with the feed: the table's
// own grouping sorts the buckets by the active sort, which is the same answer
// without a second copy of the ordering rules.
export function activityGroup(job, now = Date.now()) {
    if (job.status === 'pending' || !job.started_at) return 'Queued';
    const mins = (now - new Date(job.started_at).getTime()) / 60000;
    return mins < 1440 ? 'Today' : 'Earlier';
}
