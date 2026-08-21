export const MAX_AI_ATTACHMENTS = 8;

const RESOLUTION_STATUSES = new Set([
    'resolved', 'denied', 'stale', 'unknown', 'unavailable', 'omitted',
]);

export function attachmentKey(attachment) {
    const runKind = attachment?.runKind || attachment?.run_kind || '';
    return `${attachment?.type || ''}:${runKind}:${attachment?.id || ''}`;
}

export function normalizeAttachment(reference) {
    if (!reference || reference.type == null || reference.id == null) return null;
    const type = reference.type === 'app' || reference.type === 'application'
        ? 'service'
        : String(reference.type);
    const rawStatus = reference.attachmentStatus || reference.status;
    return {
        type,
        id: String(reference.id),
        label: String(reference.label || `${type} ${reference.id}`),
        sublabel: String(reference.sublabel || ''),
        path: reference.path ? String(reference.path) : null,
        runKind: reference.runKind || reference.run_kind || null,
        status: RESOLUTION_STATUSES.has(rawStatus) ? rawStatus : null,
    };
}

export function addAttachment(current, reference) {
    const normalized = normalizeAttachment(reference);
    if (!normalized) return current;
    if (current.some((item) => attachmentKey(item) === attachmentKey(normalized))) {
        return current;
    }
    if (current.length >= MAX_AI_ATTACHMENTS) return current;
    return [...current, normalized];
}

export function removeAttachment(current, key) {
    return current.filter((item) => attachmentKey(item) !== key);
}

export function applyAttachmentWarning(current, warning) {
    const warningKey = attachmentKey({
        ...warning,
        runKind: warning.runKind || warning.run_kind,
    });
    return current.map((item) => (
        attachmentKey(item) === warningKey
            ? { ...item, status: warning.status || 'unavailable', warning: warning.message || '' }
            : item
    ));
}

export function markAttachmentsResolved(current) {
    return current.map((item) => (item.status ? item : { ...item, status: 'resolved' }));
}

export function toAttachmentPayload(reference) {
    const normalized = normalizeAttachment(reference);
    if (!normalized) return null;
    return {
        type: normalized.type,
        id: normalized.id,
        label: normalized.label,
        ...(normalized.runKind ? { run_kind: normalized.runKind } : {}),
    };
}
