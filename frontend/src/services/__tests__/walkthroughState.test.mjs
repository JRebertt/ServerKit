import test from 'node:test';
import assert from 'node:assert/strict';

import {
    completeWalkthroughStepState,
    dismissWalkthroughState,
    getWalkthroughProgress,
    normalizeWalkthroughState,
    routeMatches,
    startWalkthroughState,
} from '../walkthroughState.js';


const walkthrough = {
    id: 'create-service',
    steps: [{ id: 'open' }, { id: 'choose' }, { id: 'launch' }],
};

test('starts, resumes, and completes one walkthrough without losing other progress', () => {
    const initial = normalizeWalkthroughState({
        active_id: null,
        progress: {
            old: { status: 'completed', completed_steps: ['done'] },
        },
    }, ['old', 'create-service']);
    const started = startWalkthroughState(initial, walkthrough.id, 'start');
    assert.equal(started.active_id, walkthrough.id);
    assert.equal(started.progress.old.status, 'completed');

    const first = completeWalkthroughStepState(
        started, walkthrough.id, 'open', walkthrough.steps.map((step) => step.id), 'one');
    assert.deepEqual(getWalkthroughProgress(first, walkthrough).completed, ['open']);

    const done = ['choose', 'launch'].reduce((state, stepId) => (
        completeWalkthroughStepState(
            state, walkthrough.id, stepId,
            walkthrough.steps.map((step) => step.id), stepId)
    ), first);
    assert.equal(done.active_id, null);
    assert.equal(done.progress[walkthrough.id].status, 'completed');
    assert.equal(getWalkthroughProgress(done, walkthrough).percent, 100);
});

test('dismisses only the active guide and a restart begins from zero', () => {
    const started = startWalkthroughState(
        { version: 1, active_id: null, progress: {} }, walkthrough.id, 'start');
    const dismissed = dismissWalkthroughState(started, walkthrough.id, 'stop');
    assert.equal(dismissed.active_id, null);
    assert.equal(dismissed.progress[walkthrough.id].status, 'dismissed');
    const restarted = startWalkthroughState(dismissed, walkthrough.id, 'again');
    assert.deepEqual(restarted.progress[walkthrough.id].completed_steps, []);
});

test('switching guides preserves unfinished progress for later resume', () => {
    let state = startWalkthroughState(
        { version: 1, active_id: null, progress: {} }, walkthrough.id, 'start');
    state = completeWalkthroughStepState(
        state, walkthrough.id, 'open', walkthrough.steps.map((step) => step.id), 'one');
    state = startWalkthroughState(state, 'enable-two-factor', 'second');
    const resumed = startWalkthroughState(state, walkthrough.id, 'resume');
    assert.deepEqual(resumed.progress[walkthrough.id].completed_steps, ['open']);
});

test('drops unknown definitions and matches only route boundaries', () => {
    const normalized = normalizeWalkthroughState({
        active_id: 'removed-guide',
        progress: { 'removed-guide': { status: 'active', completed_steps: [] } },
    }, ['create-service']);
    assert.equal(normalized.active_id, null);
    assert.deepEqual(normalized.progress, {});
    assert.equal(routeMatches('/settings/security', '/settings/security'), true);
    assert.equal(routeMatches('/settings/security/sessions', '/settings/security'), true);
    assert.equal(routeMatches('/settings/security-old', '/settings/security'), false);
});
