import test from 'node:test';
import assert from 'node:assert/strict';

import ApiClient from '../api/client.js';
import {
    ACTIVE_WORKSPACE_ID_KEY,
    ACTIVE_WORKSPACE_KEY,
    WORKSPACE_ACCENT_KEY,
    createWorkspaceStore,
} from '../workspaceStore.js';

function createMemoryStorage() {
    const values = new Map();
    return {
        getItem: (key) => (values.has(key) ? values.get(key) : null),
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: (key) => values.delete(key),
        values,
    };
}

test('persists one coherent workspace snapshot and publishes changes', () => {
    const storage = createMemoryStorage();
    const store = createWorkspaceStore({ storage, eventTarget: new EventTarget() });
    let changes = 0;
    const unsubscribe = store.subscribe(() => { changes += 1; });

    const workspace = { id: 17, name: 'Production', primary_color: '#123456' };
    store.setActiveWorkspace(workspace);

    assert.equal(storage.getItem(ACTIVE_WORKSPACE_ID_KEY), '17');
    assert.deepEqual(JSON.parse(storage.getItem(ACTIVE_WORKSPACE_KEY)), workspace);
    assert.equal(storage.getItem(WORKSPACE_ACCENT_KEY), '#123456');
    assert.deepEqual(store.getSnapshot(), {
        activeWorkspaceId: '17',
        activeWorkspace: workspace,
        workspaceAccent: '#123456',
    });
    assert.equal(changes, 1);

    store.refreshActiveWorkspace({ ...workspace, name: 'Production EU' });
    assert.equal(store.getSnapshot().activeWorkspace.name, 'Production EU');
    assert.equal(changes, 2);

    store.clearActiveWorkspace();
    assert.equal(store.getSnapshot().activeWorkspaceId, 'all');
    assert.equal(storage.getItem(ACTIVE_WORKSPACE_ID_KEY), null);
    assert.equal(storage.getItem(ACTIVE_WORKSPACE_KEY), null);
    assert.equal(storage.getItem(WORKSPACE_ACCENT_KEY), null);
    assert.equal(changes, 3);
    unsubscribe();
});

test('storage events synchronize changes made by another tab', () => {
    const storage = createMemoryStorage();
    const eventTarget = new EventTarget();
    const store = createWorkspaceStore({ storage, eventTarget });
    let changes = 0;
    store.subscribe(() => { changes += 1; });

    const workspace = { id: '9', name: 'Shared tab' };
    storage.setItem(ACTIVE_WORKSPACE_ID_KEY, '9');
    storage.setItem(ACTIVE_WORKSPACE_KEY, JSON.stringify(workspace));
    const storageEvent = new Event('storage');
    Object.defineProperty(storageEvent, 'key', { value: ACTIVE_WORKSPACE_ID_KEY });
    eventTarget.dispatchEvent(storageEvent);

    assert.equal(changes, 1);
    assert.equal(store.getSnapshot().activeWorkspaceId, '9');
    assert.deepEqual(store.getSnapshot().activeWorkspace, workspace);
    store.destroy();
});

test('keeps live workspace state when persistence is unavailable', () => {
    const unavailableStorage = {
        getItem: () => { throw new Error('blocked'); },
        setItem: () => { throw new Error('blocked'); },
        removeItem: () => { throw new Error('blocked'); },
    };
    const store = createWorkspaceStore({
        storage: unavailableStorage,
        eventTarget: new EventTarget(),
    });

    store.setActiveWorkspace({ id: 11, name: 'In memory' });

    assert.equal(store.getSnapshot().activeWorkspaceId, '11');
    assert.equal(store.getSnapshot().activeWorkspace.name, 'In memory');
    store.destroy();
});

test('ApiClient scopes coalescing and request headers from the injected store', async () => {
    const storage = createMemoryStorage();
    globalThis.localStorage = storage;
    storage.setItem('access_token', 'token');

    let activeWorkspaceId = '42';
    const workspace = {
        getSnapshot: () => ({ activeWorkspaceId }),
        clearActiveWorkspace: () => { activeWorkspaceId = 'all'; },
    };
    const requests = [];
    globalThis.fetch = async (url, options) => {
        requests.push({ url, options });
        return {
            ok: true,
            status: 200,
            url,
            json: async () => ({ ok: true }),
        };
    };

    const client = new ApiClient({ workspace });
    client.baseUrl = '/api/v1';
    await client.request('/servers');
    assert.equal(requests[0].options.headers['X-Workspace-Id'], '42');
    assert.equal(requests[0].options.headers.Authorization, 'Bearer token');

    activeWorkspaceId = 'all';
    await client.request('/servers');
    assert.equal('X-Workspace-Id' in requests[1].options.headers, false);
});
