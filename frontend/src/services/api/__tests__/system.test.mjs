import assert from 'node:assert/strict';
import test from 'node:test';

import { getMetricsHistory } from '../system.js';


test('getMetricsHistory uses the content-blocker-safe route', async () => {
    const calls = [];
    const context = {
        request(path) {
            calls.push(path);
            return Promise.resolve({ period: '6h' });
        },
    };

    const result = await getMetricsHistory.call(context, '6h');

    assert.deepEqual(calls, ['/system/performance-history?period=6h']);
    assert.deepEqual(result, { period: '6h' });
});
