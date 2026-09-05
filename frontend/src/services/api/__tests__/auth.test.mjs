import test from 'node:test';
import assert from 'node:assert/strict';
import { login, logout, redeemLoginLink, updateCurrentUser } from '../auth.js';

test('MFA challenges do not persist incomplete session credentials', async () => {
    const challenge = { requires_2fa: true, temp_token: 'pending' };
    const client = {
        request: async () => challenge,
        setTokens: () => assert.fail('MFA challenge must not install session tokens'),
    };
    assert.equal(await login.call(client, 'user', 'password'), challenge);
    assert.equal(await redeemLoginLink.call(client, 'link'), challenge);
});

test('password changes replace the revoked token pair before returning', async () => {
    const replacement = { user: { id: 1 }, access_token: 'new-access', refresh_token: 'new-refresh' };
    const events = [];
    const client = {
        request: async (endpoint, options) => {
            assert.equal(endpoint, '/auth/me');
            assert.equal(options.body.current_password, 'current');
            return replacement;
        },
        setTokens: (...pair) => events.push(pair),
    };
    assert.equal(await updateCurrentUser.call(client, { password: 'new-password', current_password: 'current' }), replacement);
    assert.deepEqual(events, [['new-access', 'new-refresh']]);
});

test('logout submits server revocation before clearing local credentials', async () => {
    const events = [];
    await logout.call({
        request: async (endpoint, options) => {
            assert.equal(endpoint, '/auth/logout');
            assert.equal(options.method, 'POST');
            events.push('revoke');
        },
        clearTokens: () => events.push('clear'),
    });
    assert.deepEqual(events, ['revoke', 'clear']);
});

test('logout still clears credentials when server revocation fails', async () => {
    let cleared = false;
    await assert.rejects(logout.call({
        request: async () => { throw new Error('offline'); },
        clearTokens: () => { cleared = true; },
    }), /offline/);
    assert.equal(cleared, true);
});
