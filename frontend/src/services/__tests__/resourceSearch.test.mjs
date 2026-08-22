import assert from 'node:assert/strict';
import test from 'node:test';

import { buildResourceSearchQuery } from '../api/search.js';

test('serializes the ResourcePicker filters without duplicating values', () => {
    const query = buildResourceSearchQuery({
        query: '  nyc  ',
        types: ['server', 'server', 'project'],
        scope: { workspaceId: 4, projectId: 9 },
        capabilities: ['docker', 'systemd', 'docker'],
        cursor: 'djE6MjA',
        limit: 40,
    });

    assert.equal(
        query,
        'q=nyc&types=server%2Cproject&workspace_id=4&project_id=9&capabilities=docker%2Csystemd&cursor=djE6MjA&limit=40',
    );
});

test('omits all-workspace and empty optional filters', () => {
    assert.equal(
        buildResourceSearchQuery({ types: ['environment'], scope: { workspaceId: 'all' } }),
        'types=environment&limit=20',
    );
});
