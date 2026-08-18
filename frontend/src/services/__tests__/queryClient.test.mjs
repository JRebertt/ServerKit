import assert from 'node:assert/strict';
import test from 'node:test';

import { createQueryClient } from '../queryClient.js';


test('deduplicates concurrent requests for one scoped key', async () => {
    const client = createQueryClient();
    let calls = 0;
    let resolveRequest;
    const request = () => {
        calls += 1;
        return new Promise((resolve) => { resolveRequest = resolve; });
    };

    const first = client.fetchQuery(['workspace', 'alpha', 'apps'], request);
    const second = client.fetchQuery(['workspace', 'alpha', 'apps'], request);
    await Promise.resolve();
    resolveRequest(['one']);

    assert.deepEqual(await first, ['one']);
    assert.deepEqual(await second, ['one']);
    assert.equal(calls, 1);
    assert.equal(client.getSnapshot(['workspace', 'alpha', 'apps']).status, 'success');
});


test('isolates identical resources between workspaces', async () => {
    const client = createQueryClient();

    await Promise.all([
        client.fetchQuery(['workspace', 'alpha', 'servers'], async () => ['alpha-server']),
        client.fetchQuery(['workspace', 'beta', 'servers'], async () => ['beta-server']),
    ]);

    assert.deepEqual(
        client.getSnapshot(['workspace', 'alpha', 'servers']).data,
        ['alpha-server'],
    );
    assert.deepEqual(
        client.getSnapshot(['workspace', 'beta', 'servers']).data,
        ['beta-server'],
    );
});


test('cancels an in-flight request after its last observer leaves', async () => {
    const client = createQueryClient();
    const key = ['workspace', 'alpha', 'jobs'];
    let signal;
    const unsubscribe = client.subscribe(key, () => {});
    const pending = client.fetchQuery(key, ({ signal: requestSignal }) => {
        signal = requestSignal;
        return new Promise(() => {});
    });

    await Promise.resolve();
    unsubscribe();

    assert.equal(signal.aborted, true);
    assert.equal(client.getSnapshot(key).isFetching, false);
    void pending;
});


test('prefix invalidation targets one workspace and advances revision', async () => {
    const client = createQueryClient();
    const alpha = ['workspace', 'alpha', 'apps'];
    const beta = ['workspace', 'beta', 'apps'];
    await client.fetchQuery(alpha, async () => ['a']);
    await client.fetchQuery(beta, async () => ['b']);

    const alphaRevision = client.getSnapshot(alpha).revision;
    const betaRevision = client.getSnapshot(beta).revision;
    client.invalidateQueries(['workspace', 'alpha']);

    assert.equal(client.getSnapshot(alpha).revision, alphaRevision + 1);
    assert.equal(client.getSnapshot(alpha).updatedAt, 0);
    assert.equal(client.getSnapshot(beta).revision, betaRevision);
});
