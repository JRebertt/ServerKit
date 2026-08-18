import assert from 'node:assert/strict';
import test from 'node:test';

import {
    EMPTY_USER_FORM,
    userPayload,
    validateUser,
    valuesForUser,
} from '../userForm.js';

test('user form derives safe create and edit values', () => {
    assert.deepEqual(valuesForUser(null), { ...EMPTY_USER_FORM });
    assert.deepEqual(valuesForUser({
        email: 'ada@example.com',
        username: 'ada',
        role: 'admin',
        is_active: false,
        password: 'must-not-be-copied',
    }), {
        ...EMPTY_USER_FORM,
        email: 'ada@example.com',
        username: 'ada',
        role: 'admin',
        is_active: false,
    });
});

test('new users require a valid matching password', () => {
    const values = {
        ...EMPTY_USER_FORM,
        email: 'user@example.com',
        username: 'user',
        password: 'short',
        confirmPassword: 'different',
    };

    assert.deepEqual(validateUser(values), {
        password: 'Password must be at least 8 characters',
        confirmPassword: 'Passwords do not match',
    });
    assert.deepEqual(validateUser({ ...values, password: '', confirmPassword: '' }), {
        password: 'Password is required for new users',
    });
});

test('edits permit a blank password and payloads omit confirmation state', () => {
    const values = {
        ...EMPTY_USER_FORM,
        email: '  user@example.com ',
        username: ' user ',
    };

    assert.deepEqual(validateUser(values, { isEditing: true }), {});
    assert.deepEqual(userPayload(values, {
        permissions: { applications: ['read'] },
        includePermissions: true,
    }), {
        email: 'user@example.com',
        username: 'user',
        role: 'developer',
        is_active: true,
        permissions: { applications: ['read'] },
    });
});

test('admin payloads never include custom permissions', () => {
    assert.deepEqual(userPayload({
        ...EMPTY_USER_FORM,
        email: 'admin@example.com',
        username: 'admin',
        role: 'admin',
        password: 'long-enough',
        confirmPassword: 'long-enough',
    }, {
        permissions: { applications: [] },
        includePermissions: true,
    }), {
        email: 'admin@example.com',
        username: 'admin',
        role: 'admin',
        is_active: true,
        password: 'long-enough',
    });
});
