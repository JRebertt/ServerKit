import assert from 'node:assert/strict';
import test from 'node:test';

import {
    DEFAULT_SCALE_POLICY,
    normalizeScalePolicy,
    replicaTarget,
    resolvedReplicaCount,
    scalePolicyPayload,
} from '../autoScalePolicy.js';

test('normalizes a missing policy to the UI defaults', () => {
    assert.deepEqual(normalizeScalePolicy(null), DEFAULT_SCALE_POLICY);
    assert.deepEqual(normalizeScalePolicy({ enabled: true, service_name: 'web' }), {
        ...DEFAULT_SCALE_POLICY,
        enabled: true,
        service_name: 'web',
    });
});

test('coerces backend nulls back to form-safe values', () => {
    // The backend stores an unset service_name as null; the form must never
    // receive it or the inputs flip from controlled to uncontrolled.
    assert.deepEqual(normalizeScalePolicy({
        enabled: null,
        service_name: null,
        min_replicas: null,
        max_replicas: 'not-a-number',
        current_replicas: null,
    }), DEFAULT_SCALE_POLICY);
});

test('serializes the policy using the same bounds as the API', () => {
    assert.deepEqual(scalePolicyPayload({
        enabled: true,
        service_name: '  web  ',
        min_replicas: '0',
        max_replicas: '-2',
        cpu_high_percent: '120',
        cpu_low_percent: '-4',
        cooldown_seconds: '-30',
    }), {
        enabled: true,
        service_name: 'web',
        min_replicas: 1,
        max_replicas: 1,
        cpu_high_percent: 100,
        cpu_low_percent: 0,
        cooldown_seconds: 0,
    });
});

test('manual scale never asks for zero replicas and reports the API result', () => {
    assert.equal(replicaTarget('0'), 1);
    assert.equal(replicaTarget('4'), 4);
    assert.equal(resolvedReplicaCount({ replicas: 2 }, 5), 2);
    assert.equal(resolvedReplicaCount(null, 5), 5);
});
