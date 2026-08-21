import assert from 'node:assert/strict';
import test from 'node:test';

import {
    getRecentResourceKeys,
    groupResourceOptions,
    normalizeResourceRef,
    recordRecentResource,
} from '../resourceRefs.js';

const memoryStorage = () => {
    const entries = new Map();
    return {
        getItem: (key) => entries.get(key) ?? null,
        setItem: (key, value) => entries.set(key, String(value)),
    };
};

const server = (id, label = `server-${id}`) => ({
    type: 'server',
    id,
    label,
    sublabel: 'online',
    path: `/servers/${id}`,
    scope: { workspace_id: 4, project_id: null, environment_id: null },
    status: 'online',
    capabilities: ['systemd', 'docker', 'docker'],
});

test('normalizes API rows into the camel-case ResourceRef contract', () => {
    assert.deepEqual(normalizeResourceRef(server(12)), {
        type: 'server',
        id: '12',
        label: 'server-12',
        sublabel: 'online',
        path: '/servers/12',
        scope: { workspaceId: 4, projectId: null, environmentId: null },
        status: 'online',
        capabilities: ['docker', 'systemd'],
    });
    assert.equal(normalizeResourceRef({ type: 'server' }), null);
});

test('recent selections stay isolated by user and capped per resource type', () => {
    const storage = memoryStorage();
    for (let id = 1; id <= 7; id += 1) recordRecentResource(server(id), 41, storage);
    recordRecentResource({ ...server(30), type: 'project' }, 41, storage);
    recordRecentResource(server(99), 52, storage);

    assert.deepEqual(
        getRecentResourceKeys(41, ['server'], storage),
        ['server:7', 'server:6', 'server:5', 'server:4', 'server:3'],
    );
    assert.deepEqual(getRecentResourceKeys(52, ['server'], storage), ['server:99']);
    assert.deepEqual(getRecentResourceKeys(41, ['project'], storage), ['project:30']);
});

test('favorites and recents are presentation groups, not resource mutations', () => {
    const options = [server('a'), server('b'), server('c')].map(normalizeResourceRef);
    const before = structuredClone(options);
    const groups = groupResourceOptions(options, {
        favoriteEntries: [{ type: 'server', id: 'b' }],
        recentKeys: ['server:a', 'server:b'],
    });

    assert.deepEqual(groups.map((group) => [group.id, group.options.map((item) => item.id)]), [
        ['favorites', ['b']],
        ['recent', ['a']],
        ['results', ['c']],
    ]);
    assert.deepEqual(options, before);
    assert.equal('favorite' in options[1], false);
});
