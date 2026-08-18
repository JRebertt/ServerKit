export const FORM_ERROR = '_form';

const cloneValues = (values) => ({ ...(values || {}) });

const errorText = (value) => {
    if (Array.isArray(value)) {
        return value.map(errorText).filter(Boolean).join(' ');
    }
    if (value && typeof value === 'object') {
        return Object.values(value).map(errorText).filter(Boolean).join(' ');
    }
    return value == null ? '' : String(value);
};

export function normalizeFieldErrors(errors) {
    if (!errors || typeof errors !== 'object' || Array.isArray(errors)) return {};

    return Object.fromEntries(
        Object.entries(errors)
            .map(([field, value]) => [field, errorText(value)])
            .filter(([, message]) => Boolean(message)),
    );
}

export function mapServerFormError(error) {
    const data = error?.data || error?.response?.data || {};
    const candidates = [
        error?.fieldErrors,
        error?.errors,
        data.field_errors,
        data.errors,
        data.details?.fields,
    ];
    const fieldErrors = candidates.reduce((result, candidate) => (
        Object.keys(result).length > 0 ? result : normalizeFieldErrors(candidate)
    ), {});

    return {
        fieldErrors,
        formError: error?.message || data.error || data.message || 'Unable to save changes',
    };
}

export function createFormState(initialValues = {}) {
    const values = cloneValues(initialValues);
    return {
        initialValues: values,
        values,
        touched: {},
        errors: {},
        submitError: '',
        submitCount: 0,
        isSubmitting: false,
    };
}

export function formReducer(state, action) {
    switch (action.type) {
        case 'setValue':
            return {
                ...state,
                values: { ...state.values, [action.name]: action.value },
                errors: action.clearError
                    ? { ...state.errors, [action.name]: undefined }
                    : state.errors,
                submitError: action.clearError ? '' : state.submitError,
            };
        case 'setValues':
            return {
                ...state,
                values: { ...state.values, ...action.values },
            };
        case 'touch':
            return {
                ...state,
                touched: { ...state.touched, [action.name]: true },
            };
        case 'validationFailed':
            return {
                ...state,
                errors: action.errors,
                touched: action.touched,
                submitError: action.errors[FORM_ERROR] || '',
                submitCount: state.submitCount + 1,
            };
        case 'submitStarted':
            return {
                ...state,
                errors: {},
                submitError: '',
                isSubmitting: true,
                submitCount: state.submitCount + 1,
            };
        case 'submitFailed':
            return {
                ...state,
                errors: action.errors,
                touched: { ...state.touched, ...action.touched },
                submitError: action.submitError,
                isSubmitting: false,
            };
        case 'submitFinished':
            return { ...state, isSubmitting: false };
        case 'reset':
            return createFormState(action.values);
        default:
            return state;
    }
}

export function dirtyFieldsFor(state) {
    return Object.fromEntries(
        Object.keys(state.values)
            .filter((name) => !Object.is(state.values[name], state.initialValues[name]))
            .map((name) => [name, true]),
    );
}

export function touchedFieldsFor(values) {
    return Object.fromEntries(Object.keys(values).map((name) => [name, true]));
}
