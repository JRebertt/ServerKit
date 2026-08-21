import { memo } from 'react';
import { Check, Download, Edit3, Lock, Trash2 } from 'lucide-react';
import FileIcon from './FileIcon';
import { useTranslation } from 'react-i18next';

function FileRow({
    entry,
    selected,
    selectMode,
    onOpen,
    onToggleSelect,
    onContext,
    onDownload,
    onRename,
    onPermissions,
    onDelete,
}) {
    const { t } = useTranslation();
    return (
        <div
            className={`file-item ${selected ? 'selected' : ''} ${selectMode ? 'select-mode' : ''}`}
            onClick={(e) => {
                if (e.ctrlKey || e.metaKey || e.shiftKey || selectMode) {
                    onToggleSelect(entry, e);
                } else {
                    onOpen(entry);
                }
            }}
            onDoubleClick={(e) => {
                e.stopPropagation();
                onOpen(entry);
            }}
            onContextMenu={(e) => onContext(e, entry)}
        >
            <span className="col-check" onClick={(e) => e.stopPropagation()}>
                <button type="button"
                    className="checkbox-btn"
                    onClick={(e) => onToggleSelect(entry, { ...e, ctrlKey: true })}
                    aria-label={selected ? t('app.fileRow.deselect', 'Deselect') : t('app.fileRow.select', 'Select')}
                >
                    <span className={`checkbox ${selected ? 'checked' : ''}`}>
                        {selected && <Check size={12} />}
                    </span>
                </button>
            </span>
            <span className="col-name">
                <FileIcon entry={entry} size={16} />
                <span className="file-item-name">{entry.name}</span>
                {entry.is_link && <span className="link-indicator">↗</span>}
            </span>
            <span className="col-size">{entry.is_dir ? '—' : entry.size_human}</span>
            <span className="col-modified">
                {new Date(entry.modified).toLocaleDateString()}
            </span>
            <span className="col-permissions">{entry.permissions}</span>
            <span className="col-owner">{entry.owner}</span>
            <span className="col-actions" onClick={(e) => e.stopPropagation()}>
                {!entry.is_dir && (
                    <button type="button" className="row-action" onClick={() => onDownload(entry)} title={t('app.fileRow.download', 'Download')}>
                        <Download size={14} />
                    </button>
                )}
                <button type="button" className="row-action" onClick={() => onRename(entry)} title={t('app.fileRow.rename', 'Rename')}>
                    <Edit3 size={14} />
                </button>
                <button type="button" className="row-action" onClick={() => onPermissions(entry)} title={t('app.fileRow.permissions', 'Permissions')}>
                    <Lock size={14} />
                </button>
                <button type="button" className="row-action danger" onClick={() => onDelete(entry)} title={t('app.fileRow.delete', 'Delete')}>
                    <Trash2 size={14} />
                </button>
            </span>
        </div>
    );
}

export default memo(FileRow);
