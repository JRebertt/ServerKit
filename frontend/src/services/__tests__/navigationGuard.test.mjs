import assert from 'node:assert/strict';
import test from 'node:test';

import { internalNavigationTarget } from '../navigationGuard.js';

const location = {
    href: 'https://panel.test/dashboard?tab=one',
    origin: 'https://panel.test',
    pathname: '/dashboard',
    search: '?tab=one',
    hash: '',
};

const click = (href, anchor = {}) => ({
    defaultPrevented: false,
    button: 0,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    target: {
        closest: () => ({
            href,
            target: '',
            hasAttribute: () => false,
            ...anchor,
        }),
    },
});

test('returns a same-origin destination with query and hash intact', () => {
    assert.equal(
        internalNavigationTarget(click('/projects/4?tab=apps#top'), location),
        '/projects/4?tab=apps#top',
    );
});

test('ignores the current page, external links, downloads, and modified clicks', () => {
    assert.equal(internalNavigationTarget(click('/dashboard?tab=one'), location), null);
    assert.equal(internalNavigationTarget(click('https://docs.example.test'), location), null);
    assert.equal(internalNavigationTarget(click('/export', {
        hasAttribute: (name) => name === 'download',
    }), location), null);
    assert.equal(internalNavigationTarget({ ...click('/projects'), ctrlKey: true }, location), null);
});
