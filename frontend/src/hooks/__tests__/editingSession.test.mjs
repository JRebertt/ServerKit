import assert from 'node:assert/strict';
import test from 'node:test';

import { createEditingSession, editingSessionReducer } from '../editingSession.js';

const reduce = (state, action) => editingSessionReducer(state, action);

test('change tracks nested dirty paths and undo/redo state', () => {
    const initial = createEditingSession({ title: 'Ops', layout: [{ x: 0, y: 0 }] });
    const changed = reduce(initial, { type: 'change', path: 'layout.0.x', value: 4 });

    assert.equal(changed.draft.layout[0].x, 4);
    assert.deepEqual(changed.dirtyPaths, ['layout.0.x']);
    assert.equal(changed.isDirty, true);
    assert.equal(changed.canUndo, true);

    const undone = reduce(changed, { type: 'undo' });
    assert.deepEqual(undone.draft, initial.baseline);
    assert.equal(undone.isDirty, false);
    assert.equal(undone.canRedo, true);

    const redone = reduce(undone, { type: 'redo' });
    assert.equal(redone.draft.layout[0].x, 4);
    assert.equal(redone.canUndo, true);
});

test('a new change after undo invalidates redo history', () => {
    let state = createEditingSession({ value: 1 });
    state = reduce(state, { type: 'change', path: 'value', value: 2 });
    state = reduce(state, { type: 'undo' });
    state = reduce(state, { type: 'change', path: 'value', value: 3 });

    assert.equal(state.canRedo, false);
    assert.equal(reduce(state, { type: 'redo' }), state);
});

test('coalesces a user-sized drag transaction into one undo step', () => {
    let state = createEditingSession({ widget: { x: 0, y: 0 } });
    state = reduce(state, {
        type: 'transaction',
        changes: [{ path: 'widget.x', value: 1 }, { path: 'widget.y', value: 2 }],
        coalesceKey: 'drag:widget',
    });
    state = reduce(state, {
        type: 'transaction',
        changes: [{ path: 'widget.x', value: 8 }, { path: 'widget.y', value: 9 }],
        coalesceKey: 'drag:widget',
    });

    assert.equal(state.past.length, 1);
    assert.deepEqual(state.draft.widget, { x: 8, y: 9 });
    assert.deepEqual(reduce(state, { type: 'undo' }).draft.widget, { x: 0, y: 0 });
});

test('bounded history drops the oldest snapshots', () => {
    let state = createEditingSession({ value: 0 }, { historyLimit: 2 });
    for (let value = 1; value <= 4; value += 1) {
        state = reduce(state, { type: 'change', path: 'value', value });
    }

    assert.equal(state.past.length, 2);
    state = reduce(reduce(state, { type: 'undo' }), { type: 'undo' });
    assert.equal(state.draft.value, 2);
    assert.equal(state.canUndo, false);
});

test('save failure preserves the draft and history for retry', () => {
    let state = createEditingSession({ title: 'Before' });
    state = reduce(state, { type: 'change', path: 'title', value: 'After' });
    state = reduce(state, { type: 'saveStarted' });
    const error = new Error('Network unavailable');
    state = reduce(state, { type: 'saveFailed', error });

    assert.equal(state.saveState, 'error');
    assert.equal(state.error, error);
    assert.equal(state.draft.title, 'After');
    assert.equal(state.canUndo, true);
});

test('save success and reset replace the baseline and clear history', () => {
    let state = createEditingSession({ title: 'Before' });
    state = reduce(state, { type: 'change', path: 'title', value: 'After' });
    state = reduce(state, {
        type: 'saveSucceeded',
        baseline: { title: 'Canonical server title' },
    });

    assert.deepEqual(state.baseline, { title: 'Canonical server title' });
    assert.deepEqual(state.draft, state.baseline);
    assert.equal(state.isDirty, false);
    assert.equal(state.saveState, 'saved');
    assert.equal(state.canUndo, false);

    state = reduce(state, { type: 'reset', baseline: { title: 'Another record' } });
    assert.deepEqual(state.draft, { title: 'Another record' });
    assert.equal(state.saveState, 'idle');
});
