import assert from 'node:assert/strict';
import test from 'node:test';

import {
    createFormState,
    dirtyFieldsFor,
    formReducer,
    mapServerFormError,
    normalizeFieldErrors,
    touchedFieldsFor,
} from '../formState.js';

test('form state tracks changed fields and resets to a new record', () => {
    const initial = createFormState({ name: 'Ada', active: true });
    const changed = formReducer(initial, {
        type: 'setValue',
        name: 'name',
        value: 'Grace',
        clearError: true,
    });

    assert.deepEqual(changed.values, { name: 'Grace', active: true });
    assert.deepEqual(dirtyFieldsFor(changed), { name: true });

    const reset = formReducer(changed, {
        type: 'reset',
        values: { name: 'Linus', active: false },
    });
    assert.deepEqual(reset.values, { name: 'Linus', active: false });
    assert.deepEqual(reset.touched, {});
    assert.deepEqual(dirtyFieldsFor(reset), {});
});

test('validation failures reveal every field and preserve field messages', () => {
    const initial = createFormState({ email: '', role: 'developer' });
    const errors = normalizeFieldErrors({ email: ['Missing data.'] });
    const invalid = formReducer(initial, {
        type: 'validationFailed',
        errors,
        touched: touchedFieldsFor(initial.values),
    });

    assert.deepEqual(invalid.errors, { email: 'Missing data.' });
    assert.deepEqual(invalid.touched, { email: true, role: true });
    assert.equal(invalid.submitCount, 1);
});

test('server validation details map to fields without losing the request message', () => {
    const error = new Error('Invalid request');
    error.data = {
        code: 'validation_error',
        details: {
            fields: {
                email: ['Not a valid email address.'],
                profile: { name: ['Required.'] },
            },
        },
    };

    assert.deepEqual(mapServerFormError(error), {
        fieldErrors: {
            email: 'Not a valid email address.',
            profile: 'Required.',
        },
        formError: 'Invalid request',
    });
});

test('legacy field error shapes remain consumable during API convergence', () => {
    assert.deepEqual(mapServerFormError({
        message: 'Could not save',
        fieldErrors: { username: 'Already exists' },
    }), {
        fieldErrors: { username: 'Already exists' },
        formError: 'Could not save',
    });
});
