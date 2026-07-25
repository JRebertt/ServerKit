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

// Queued runs float to the top; everything else falls into a day bucket so the
// feed reads chronologically without printing a date on every row.
export function activityGroup(job, now = Date.now()) {
    if (job.status === 'pending' || !job.started_at) return 'Queued';
    const mins = (now - new Date(job.started_at).getTime()) / 60000;
    return mins < 1440 ? 'Today' : 'Earlier';
}

const GROUP_ORDER = { Queued: 0, Today: 1, Earlier: 2 };

// Group into ordered buckets, newest first inside each.
export function groupDeploys(jobs, now = Date.now()) {
    const buckets = new Map();
    jobs.forEach((job) => {
        const g = activityGroup(job, now);
        if (!buckets.has(g)) buckets.set(g, []);
        buckets.get(g).push(job);
    });
    return [...buckets.entries()]
        .sort((a, b) => GROUP_ORDER[a[0]] - GROUP_ORDER[b[0]])
        .map(([group, items]) => ({
            group,
            items: items.sort((a, b) => {
                const ta = new Date(a.started_at || a.created_at).getTime() || 0;
                const tb = new Date(b.started_at || b.created_at).getTime() || 0;
                return tb - ta;
            }),
        }));
}
