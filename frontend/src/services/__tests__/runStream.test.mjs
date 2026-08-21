import assert from 'node:assert/strict';
import test from 'node:test';

import { buildRunLogsPath } from '../api/runs.js';
import {
    isTerminalRunStatus,
    mergeRunLogLines,
} from '../../hooks/runStream.js';

test('builds an encoded generalized run log catch-up path', () => {
    assert.equal(
        buildRunLogsPath('doctor repair', 'run/42', 19),
        '/runs/doctor%20repair/run%2F42/logs?after_id=19',
    );
});

test('recognizes only the unified terminal run statuses', () => {
    assert.equal(isTerminalRunStatus('succeeded'), true);
    assert.equal(isTerminalRunStatus('failed'), true);
    assert.equal(isTerminalRunStatus('cancelled'), true);
    assert.equal(isTerminalRunStatus('completed'), false);
    assert.equal(isTerminalRunStatus('running'), false);
});

test('de-duplicates persisted log ids and retains a bounded tail', () => {
    const seen = new Set(['1']);
    const merged = mergeRunLogLines(
        [{ id: 1, message: 'old' }],
        [{ id: 1, message: 'duplicate' }, { id: 2 }, { id: 3 }, { message: 'live' }],
        seen,
        3,
    );

    assert.deepEqual(merged.lines, [{ id: 2 }, { id: 3 }, { message: 'live' }]);
    assert.equal(merged.maxId, 3);
    assert.deepEqual([...seen], ['1', '2', '3']);
});
