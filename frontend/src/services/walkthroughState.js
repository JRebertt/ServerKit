export const EMPTY_WALKTHROUGH_STATE = Object.freeze({
    version: 1,
    active_id: null,
    progress: {},
});

const isoNow = () => new Date().toISOString();

export function normalizeWalkthroughState(raw, knownIds = []) {
    const allowed = new Set(knownIds);
    const source = raw && typeof raw === 'object' ? raw : EMPTY_WALKTHROUGH_STATE;
    const progress = {};
    for (const [id, entry] of Object.entries(source.progress || {})) {
        if (!allowed.has(id) || !entry || typeof entry !== 'object') continue;
        progress[id] = {
            status: ['active', 'completed', 'dismissed'].includes(entry.status)
                ? entry.status
                : 'active',
            completed_steps: [...new Set(
                Array.isArray(entry.completed_steps) ? entry.completed_steps : [],
            )],
            started_at: entry.started_at || null,
            updated_at: entry.updated_at || null,
            completed_at: entry.completed_at || null,
        };
    }
    const activeId = allowed.has(source.active_id)
        && progress[source.active_id]?.status === 'active'
        ? source.active_id
        : null;
    return { version: 1, active_id: activeId, progress };
}

export function startWalkthroughState(state, walkthroughId, now = isoNow()) {
    const current = state.progress?.[walkthroughId];
    if (state.active_id === walkthroughId && current?.status === 'active') return state;
    if (current?.status === 'active') {
        return { ...state, active_id: walkthroughId };
    }
    return {
        version: 1,
        active_id: walkthroughId,
        progress: {
            ...(state.progress || {}),
            [walkthroughId]: {
                status: 'active',
                completed_steps: [],
                started_at: now,
                updated_at: now,
                completed_at: null,
            },
        },
    };
}

export function completeWalkthroughStepState(
    state,
    walkthroughId,
    stepId,
    allStepIds,
    now = isoNow(),
) {
    const current = state.progress?.[walkthroughId];
    if (!current || current.status !== 'active') return state;
    const completed = [...new Set([...(current.completed_steps || []), stepId])];
    const done = allStepIds.every((id) => completed.includes(id));
    return {
        ...state,
        active_id: done && state.active_id === walkthroughId ? null : state.active_id,
        progress: {
            ...state.progress,
            [walkthroughId]: {
                ...current,
                status: done ? 'completed' : 'active',
                completed_steps: completed,
                updated_at: now,
                completed_at: done ? now : null,
            },
        },
    };
}

export function dismissWalkthroughState(state, walkthroughId, now = isoNow()) {
    const current = state.progress?.[walkthroughId];
    if (!current) return { ...state, active_id: null };
    return {
        ...state,
        active_id: state.active_id === walkthroughId ? null : state.active_id,
        progress: {
            ...state.progress,
            [walkthroughId]: {
                ...current,
                status: 'dismissed',
                updated_at: now,
            },
        },
    };
}

export function getWalkthroughProgress(state, walkthrough) {
    const entry = state.progress?.[walkthrough.id];
    const completed = entry?.completed_steps || [];
    const total = walkthrough.steps.length;
    const count = walkthrough.steps.filter((step) => completed.includes(step.id)).length;
    return {
        entry,
        completed,
        total,
        count,
        percent: total ? Math.round((count / total) * 100) : 0,
        currentStep: walkthrough.steps.find((step) => !completed.includes(step.id)) || null,
    };
}

export function routeMatches(pathname, route) {
    return Boolean(route) && (pathname === route || pathname.startsWith(`${route}/`));
}
