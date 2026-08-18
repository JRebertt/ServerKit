export const EMPTY_USER_FORM = Object.freeze({
    email: '',
    username: '',
    password: '',
    confirmPassword: '',
    role: 'developer',
    is_active: true,
});

export function valuesForUser(user) {
    if (!user) return { ...EMPTY_USER_FORM };

    return {
        ...EMPTY_USER_FORM,
        email: user.email || '',
        username: user.username || '',
        role: user.role || 'developer',
        is_active: user.is_active !== false,
    };
}

export function validateUser(values, { isEditing = false } = {}) {
    const errors = {};
    if (!values.email?.trim()) errors.email = 'Email is required';
    if (!values.username?.trim()) errors.username = 'Username is required';
    if (!isEditing && !values.password) errors.password = 'Password is required for new users';
    if (values.password && values.password.length < 8) {
        errors.password = 'Password must be at least 8 characters';
    }
    if (values.password && values.password !== values.confirmPassword) {
        errors.confirmPassword = 'Passwords do not match';
    }
    return errors;
}

export function userPayload(values, { permissions, includePermissions = false } = {}) {
    const payload = {
        email: values.email.trim(),
        username: values.username.trim(),
        role: values.role,
        is_active: values.is_active,
    };
    if (values.password) payload.password = values.password;
    if (includePermissions && values.role !== 'admin') payload.permissions = permissions;
    return payload;
}
