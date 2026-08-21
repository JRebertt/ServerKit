import assert from 'node:assert/strict';
import test from 'node:test';

import { sanitizeOverflowIndices } from '../useOverflowItems.js';

test('drops stale overflow indexes when a route switches to fewer tabs', () => {
    assert.deepEqual(sanitizeOverflowIndices([2, 4, 7, 9], 4), [2]);
});

test('rejects malformed and duplicate overflow indexes', () => {
    assert.deepEqual(
        sanitizeOverflowIndices([-1, 1, 1, 2.5, '2', 3, null], 4),
        [1, 3]
    );
});

test('returns no overflow indexes for an empty item list', () => {
    assert.deepEqual(sanitizeOverflowIndices([0, 1], 0), []);
});
