import assert from 'node:assert/strict';
import test from 'node:test';

import {
    appendServiceLogLines,
    normalizeServiceLogSnapshot,
} from '../../hooks/serviceLogStream.js';

test('normalizes REST log snapshots from strings and arrays', () => {
    assert.deepEqual(normalizeServiceLogSnapshot('first\nsecond\n'), ['first', 'second']);
    assert.deepEqual(normalizeServiceLogSnapshot(['first', 2, '']), ['first', '2']);
});

test('bounds service log sessions to their newest lines', () => {
    assert.deepEqual(appendServiceLogLines(['one', 'two'], ['three', 'four'], 3), ['two', 'three', 'four']);
});
