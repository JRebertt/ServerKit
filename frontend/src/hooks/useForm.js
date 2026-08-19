import { useCallback, useMemo, useReducer, useRef } from 'react';
import {
    createFormState,
    dirtyFieldsFor,
    formReducer,
    mapServerFormError,
    normalizeFieldErrors,
    touchedFieldsFor,
} from './formState';

/**
 * Owns form lifecycle state while leaving field rendering and domain payloads
 * to the caller. `initialValues` are read on mount; call `reset(nextValues)`
 * when an asynchronously loaded record changes.
 */
export default function useForm({ initialValues = {}, validate, onSubmit }) {
    const [state, dispatch] = useReducer(formReducer, initialValues, createFormState);
    const initialValuesRef = useRef(initialValues);
    const validateRef = useRef(validate);
    const onSubmitRef = useRef(onSubmit);
    validateRef.current = validate;
    onSubmitRef.current = onSubmit;

    const dirtyFields = useMemo(() => dirtyFieldsFor(state), [state]);

    const setValue = useCallback((name, value, { touch = false } = {}) => {
        dispatch({ type: 'setValue', name, value, clearError: true });
        if (touch) dispatch({ type: 'touch', name });
    }, []);

    const setValues = useCallback((values) => {
        dispatch({ type: 'setValues', values });
    }, []);

    const setFieldTouched = useCallback((name) => {
        dispatch({ type: 'touch', name });
    }, []);

    const handleChange = useCallback((event) => {
        const { name, type, checked, value } = event.target;
        setValue(name, type === 'checkbox' ? checked : value);
    }, [setValue]);

    const reset = useCallback((values) => {
        const nextValues = values || initialValuesRef.current;
        initialValuesRef.current = nextValues;
        dispatch({ type: 'reset', values: nextValues });
    }, []);

    const handleSubmit = useCallback(async (event) => {
        event?.preventDefault?.();
        const values = state.values;
        const errors = normalizeFieldErrors(
            validateRef.current ? await validateRef.current(values) : {},
        );
        const touched = touchedFieldsFor(values);

        if (Object.keys(errors).length > 0) {
            dispatch({ type: 'validationFailed', errors, touched });
            return { ok: false, errors };
        }

        dispatch({ type: 'submitStarted' });
        try {
            const result = await onSubmitRef.current?.(values);
            dispatch({ type: 'submitFinished' });
            return { ok: true, value: result };
        } catch (error) {
            const mapped = mapServerFormError(error);
            const failedTouched = Object.fromEntries(
                Object.keys(mapped.fieldErrors).map((name) => [name, true]),
            );
            dispatch({
                type: 'submitFailed',
                errors: mapped.fieldErrors,
                touched: failedTouched,
                submitError: mapped.formError,
            });
            return { ok: false, error, errors: mapped.fieldErrors };
        }
    }, [state.values]);

    const getFieldError = useCallback((name) => (
        state.touched[name] ? state.errors[name] : undefined
    ), [state.errors, state.touched]);

    const getFieldProps = useCallback((name) => ({
        name,
        value: state.values[name] ?? '',
        onChange: handleChange,
        onBlur: () => setFieldTouched(name),
        'aria-invalid': Boolean(getFieldError(name)),
    }), [getFieldError, handleChange, setFieldTouched, state.values]);

    return {
        values: state.values,
        errors: state.errors,
        touched: state.touched,
        dirtyFields,
        isDirty: Object.keys(dirtyFields).length > 0,
        isSubmitting: state.isSubmitting,
        submitCount: state.submitCount,
        submitError: state.submitError,
        setValue,
        setValues,
        setFieldTouched,
        getFieldError,
        getFieldProps,
        handleChange,
        handleSubmit,
        reset,
    };
}
