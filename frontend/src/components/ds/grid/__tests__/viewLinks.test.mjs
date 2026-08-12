// Proving tests for scoped shareable links.
//
// A tab that renders TWO tables (Security's allowlist + blocklist, Settings'
// three API tables) has two chrome instances on ONE route. Every link param is
// a global name — `view`, `sort`, `hide`, `f` — so without a scope the second
// table reads the first's sort and then overwrites its `?view=`.
//
// The invariant that matters most here is the FIRST one: an unscoped call must
// produce and accept byte-identical URLs to before scopes existed, or every
// single-table page's links silently change meaning.
//
// Run: node --test src/components/ds/grid/__tests__/viewLinks.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';

import {
    stateToParams, paramsToState, readViewParams, withViewParam, copyableLink, scopedKey,
} from '../viewLinks.js';

const STATE = {
    sorts: [{ key: 'name', direction: 'asc' }],
    hiddenKeys: ['comment'],
    columnOrder: null,
    groupBy: null,
    columnFilters: { match: 'any', rules: [{ id: 'r1', field: 'status', op: 'any', value: ['active', 'banned'] }] },
    page: { search: 'nginx' },
};

// ---------------------------------------------------------------- unscoped

test('unscoped params are unchanged by the introduction of scopes', () => {
    const qs = stateToParams(STATE).toString();
    assert.match(qs, /(^|&)sort=name%3Aasc(&|$)/);
    assert.match(qs, /(^|&)hide=comment(&|$)/);
    assert.match(qs, /(^|&)match=any(&|$)/);
    assert.match(qs, /(^|&)f=status%3Aany%3Aactive%2Cbanned(&|$)/);
    // No key carries a prefix.
    for (const key of new URLSearchParams(qs).keys()) {
        assert.ok(!key.includes('.'), `unscoped key should not be namespaced: ${key}`);
    }
});

test('the page bag is flattened into the URL', () => {
    // The envelope nests page-owned primitives under `page`. Objects are
    // skipped by design, so without flattening a shared link silently stopped
    // carrying the search box and status filter it used to carry.
    const qs = stateToParams(STATE).toString();
    assert.match(qs, /(^|&)search=nginx(&|$)/);
    assert.equal(paramsToState(new URLSearchParams(qs)).search, 'nginx');
});

test('scopedKey is identity without a scope', () => {
    assert.equal(scopedKey('', 'view'), 'view');
    assert.equal(scopedKey(undefined, 'sort'), 'sort');
    assert.equal(scopedKey('allowlist', 'view'), 'allowlist.view');
});

// ------------------------------------------------------------------ scoped

test('a scope round-trips its own state', () => {
    const qs = stateToParams(STATE, 'allowlist').toString();
    const back = paramsToState(new URLSearchParams(qs), 'allowlist');
    assert.deepEqual(back.sorts, STATE.sorts);
    assert.deepEqual(back.hiddenKeys, STATE.hiddenKeys);
    assert.equal(back.columnFilters.match, 'any');
    assert.deepEqual(back.columnFilters.rules[0].value, ['active', 'banned']);
    assert.equal(back.search, 'nginx');
});

test('two scopes on one query string do not see each other', () => {
    const allow = stateToParams({ sorts: [{ key: 'ip', direction: 'asc' }] }, 'allowlist');
    const block = stateToParams({ sorts: [{ key: 'added', direction: 'desc' }] }, 'blocklist');
    const merged = new URLSearchParams(`${allow}&${block}`);

    assert.deepEqual(paramsToState(merged, 'allowlist').sorts, [{ key: 'ip', direction: 'asc' }]);
    assert.deepEqual(paramsToState(merged, 'blocklist').sorts, [{ key: 'added', direction: 'desc' }]);
});

test('an unscoped reader ignores another table scoped params', () => {
    // Otherwise `blocklist.status=banned` would be swallowed as page state and
    // pushed through the unscoped table's own setters.
    const merged = new URLSearchParams('blocklist.sort=added:desc&blocklist.status=banned');
    assert.equal(paramsToState(merged), null);
});

test('readViewParams reads only its own scope handle', () => {
    const search = '?allowlist.view=trusted&blocklist.view=recent';
    assert.deepEqual(
        { kind: readViewParams(search, 'allowlist').kind, slug: readViewParams(search, 'allowlist').slug },
        { kind: 'saved', slug: 'trusted' },
    );
    assert.equal(readViewParams(search, 'blocklist').slug, 'recent');
    // And an unscoped reader finds neither.
    assert.equal(readViewParams(search).kind, null);
});

test('writing one scope handle leaves the other alone', () => {
    const next = withViewParam('?allowlist.view=trusted&blocklist.view=recent', 'flagged', 'blocklist');
    assert.equal(next.get('allowlist.view'), 'trusted');
    assert.equal(next.get('blocklist.view'), 'flagged');
});

test('clearing one scope handle leaves the other alone', () => {
    const next = withViewParam('?allowlist.view=trusted&blocklist.view=recent', null, 'blocklist');
    assert.equal(next.get('allowlist.view'), 'trusted');
    assert.equal(next.get('blocklist.view'), null);
});

test('the legacy ?v= blob is only read unscoped', () => {
    // Nothing has generated one since before scopes existed, so a scoped table
    // must not adopt a blob that was written for the page as a whole.
    const search = '?v=eyJzb3J0cyI6W119';
    assert.equal(readViewParams(search, 'allowlist').kind, null);
});

test('copyableLink namespaces the handle it puts on the clipboard', () => {
    const url = copyableLink({
        pathname: '/security/ip-lists',
        view: { name: 'Trusted', slug: 'trusted' },
        isDirty: false,
        state: {},
        origin: 'https://panel.example.com',
        scope: 'allowlist',
    });
    assert.equal(url, 'https://panel.example.com/security/ip-lists?allowlist.view=trusted');
});

test('a dirty scoped view copies its state, still namespaced', () => {
    const url = copyableLink({
        pathname: '/security/ip-lists',
        view: { name: 'Trusted', slug: 'trusted' },
        isDirty: true,
        state: { sorts: [{ key: 'ip', direction: 'asc' }] },
        origin: 'https://panel.example.com',
        scope: 'allowlist',
    });
    assert.equal(url, 'https://panel.example.com/security/ip-lists?allowlist.sort=ip%3Aasc');
});
