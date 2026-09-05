import assert from 'node:assert/strict';
import test from 'node:test';

import { measureNaturalWidths, sanitizeOverflowIndices } from '../useOverflowItems.js';

test('measures stylesheet-hidden items without leaving them visible', () => {
    const visible = {
        style: { display: '' },
        computedDisplay: 'inline-flex',
        get offsetWidth() { return 96; },
    };
    const hiddenByClass = {
        style: { display: '' },
        computedDisplay: 'none',
        get offsetWidth() { return this.style.display === 'inline-flex' ? 128 : 0; },
    };
    const hiddenInline = {
        style: { display: 'none' },
        computedDisplay: 'none',
        get offsetWidth() { return this.style.display === 'inline-flex' ? 84 : 0; },
    };
    const originalGetComputedStyle = globalThis.getComputedStyle;
    globalThis.getComputedStyle = (element) => ({
        display: element.style.display === 'inline-flex'
            ? 'inline-flex'
            : element.computedDisplay,
    });

    try {
        assert.deepEqual(
            measureNaturalWidths([visible, hiddenByClass, hiddenInline, null]),
            [96, 128, 84, 0]
        );
        assert.equal(hiddenByClass.style.display, '');
        assert.equal(hiddenInline.style.display, 'none');
    } finally {
        globalThis.getComputedStyle = originalGetComputedStyle;
    }
});

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
