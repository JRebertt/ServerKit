import assert from 'node:assert/strict';
import test from 'node:test';

import {
    evaluateScale,
    getScalePolicy,
    scaleApp,
    updateScalePolicy,
} from '../containerOps.js';

function recorder(response = { ok: true }) {
    const calls = [];
    return {
        calls,
        context: {
            request(path, options) {
                calls.push({ path, options });
                return Promise.resolve(response);
            },
        },
    };
}

test('scale-policy frontend methods preserve the backend route contract', async () => {
    const { calls, context } = recorder({ replicas: 3 });
    const policy = { enabled: true, service_name: 'web', min_replicas: 2 };

    await getScalePolicy.call(context, 42);
    await updateScalePolicy.call(context, 42, policy);
    const result = await scaleApp.call(context, 42, 3);
    await evaluateScale.call(context, 42);

    assert.deepEqual(calls, [
        { path: '/apps/42/scale-policy', options: undefined },
        { path: '/apps/42/scale-policy', options: { method: 'PUT', body: policy } },
        { path: '/apps/42/scale', options: { method: 'POST', body: { replicas: 3 } } },
        { path: '/apps/42/scale/evaluate', options: { method: 'POST' } },
    ]);
    assert.deepEqual(result, { replicas: 3 });
});
