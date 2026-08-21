import { AlertTriangle, Paperclip, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { attachmentKey } from '../../lib/ai/attachments';
import IconButton from '../IconButton';

const WARNING_STATUSES = new Set(['denied', 'stale', 'unknown', 'unavailable', 'omitted']);

export default function AttachmentChip({ attachment, onRemove }) {
    const { t } = useTranslation();
    const warning = WARNING_STATUSES.has(attachment.status);
    const statusLabel = attachment.status === 'denied'
        ? t('app.attachmentChip.denied', 'Access denied')
        : attachment.status === 'stale'
            ? t('app.attachmentChip.stale', 'No longer available')
            : attachment.status === 'unknown'
                ? t('app.attachmentChip.unknown', 'Unsupported attachment')
                : attachment.status === 'omitted'
                    ? t('app.attachmentChip.omitted', 'Context limit reached')
                    : t('app.attachmentChip.unavailable', 'Unavailable');
    const title = warning ? (attachment.warning || statusLabel) : attachment.label;

    return (
        <span
            className={`sk-ai-attachment${warning ? ' is-warning' : ''}`}
            title={title}
        >
            {warning ? <AlertTriangle size={12} aria-hidden="true" /> : <Paperclip size={12} aria-hidden="true" />}
            <span className="sk-ai-attachment__type">{attachment.runKind || attachment.type}</span>
            <span className="sk-ai-attachment__label">{attachment.label}</span>
            {warning && <span className="sk-ai-attachment__status">{statusLabel}</span>}
            {onRemove && (
                <IconButton
                    className="sk-ai-attachment__remove"
                    onClick={() => onRemove(attachmentKey(attachment))}
                    label={t('app.attachmentChip.remove', 'Remove {{label}}', { label: attachment.label })}
                    icon={<X size={12} aria-hidden="true" />}
                />
            )}
        </span>
    );
}
