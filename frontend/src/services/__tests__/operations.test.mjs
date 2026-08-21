import assert from 'node:assert/strict';
import test from 'node:test';

import {
    boundOperationHistory,
    normalizeDeploymentOperation,
    normalizeJobOperation,
    normalizeOperations,
    operationKey,
    reconcileOperationStatus,
} from '../operations.js';

test('normalizes deployment progress, resource, and detail route', () => {
    const operation = normalizeDeploymentOperation({
        id: 'dep-1',
        kind: 'app_deploy',
        status: 'running',
        app_id: 8,
        app_name: 'api-production',
        current_step: 2,
        total_steps: 5,
        started_at: '2026-08-19T14:22:00Z',
    });

    assert.equal(operationKey(operation), 'deploy:dep-1');
    assert.equal(operation.title, 'Deploy api-production');
    assert.deepEqual(operation.progress, { completed: 2, total: 5, percent: 40 });
    assert.equal(operation.resource.type, 'app');
    assert.equal(operation.detailPath, '/deployments/dep-1');
});

test('normalizes proof job kinds and keeps deploy queue mirrors out', () => {
    const backup = normalizeJobOperation({
        id: 'job-1',
        kind: 'backup.policy.run',
        status: 'pending',
        owner_type: 'backup_policy',
        owner_id: 12,
    });
    assert.equal(backup.title, 'Backup policy run');
    assert.equal(backup.detailPath, '/monitoring/jobs?focus=job-1');

    const operations = normalizeOperations({
        deployments: [{ id: 'dep-1', status: 'running' }],
        jobs: [{ id: 'mirror', kind: 'deploy.app', status: 'running' }, { id: 'job-1', kind: 'doctor.run' }],
    });
    assert.deepEqual(operations.map(operationKey).sort(), ['deploy:dep-1', 'job:job-1']);
});

test('bounds terminal history without dropping active or selected work', () => {
    const operations = [
        normalizeJobOperation({ id: 'active', status: 'running', updated_at: '2026-08-21T03:00:00Z' }),
        normalizeJobOperation({ id: 'recent', status: 'succeeded', updated_at: '2026-08-21T02:00:00Z' }),
        normalizeJobOperation({ id: 'selected', status: 'succeeded', updated_at: '2026-08-21T01:00:00Z' }),
    ];
    const bounded = boundOperationHistory(operations, 1, 'job:selected');
    assert.deepEqual(bounded.map(operationKey), ['job:active', 'job:recent', 'job:selected']);
});

test('reconciles one run and marks a newly failed terminal operation unread', () => {
    const current = [normalizeJobOperation({ id: 'job-1', kind: 'doctor.run', status: 'running' })];
    const result = reconcileOperationStatus(current, {
        run_kind: 'job',
        run_id: 'job-1',
        status: { status: 'failed', error_message: 'repair failed' },
    });
    assert.equal(result.matched, true);
    assert.equal(result.attentionKey, 'job:job-1');
    assert.equal(result.operations[0].status, 'failed');
    assert.equal(result.operations[0].error, 'repair failed');
});

test('preserves operation identity while accepting and clearing server capabilities', () => {
    const current = [normalizeJobOperation({
        id: 'job-2',
        kind: 'security.lynis_scan',
        status: 'running',
        can_retry: true,
    })];
    const result = reconcileOperationStatus(current, {
        run_kind: 'job',
        run_id: 'job-2',
        status: { status: 'running', requires_action: true, can_retry: false },
    });
    assert.equal(result.attentionKey, 'job:job-2');
    assert.equal(result.operations[0].title, 'Security scan');
    assert.equal(result.operations[0].canRetry, false);
    assert.equal(result.operations[0].requiresAction, true);
});
