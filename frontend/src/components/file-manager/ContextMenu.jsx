import { useTranslation } from 'react-i18next';
import {
    Folder, Eye, Download, Edit3, Lock, Copy, Trash2,
} from 'lucide-react';

export default function ContextMenu({
    menu,                  // { x, y, entry }
    selectionCount,        // total items selected
    onClose,
    onOpen,
    onDownload,
    onRename,
    onPermissions,
    onCopyPath,
    onDelete,
}) {
    const { t } = useTranslation();
    if (!menu) return null;
    const { x, y, entry } = menu;
    const multi = selectionCount > 1;

    return (
        <div
            className="context-menu"
            style={{ top: y, left: x }}
            onClick={(e) => e.stopPropagation()}
        >
            <button type="button" onClick={() => { onOpen(entry); onClose(); }}>
                {entry.is_dir ? <Folder size={14} /> : <Eye size={14} />}
                {entry.is_dir ? 'Open' : 'Preview'}
            </button>
            {!entry.is_dir && (
                <button type="button" onClick={() => { onDownload(entry); onClose(); }}>
                    <Download size={14} /> {t('app.contextMenu.download', 'Download')}
                </button>
            )}
            <button type="button" onClick={() => { onRename(entry); onClose(); }}>
                <Edit3 size={14} /> {t('app.contextMenu.rename', 'Rename')}
            </button>
            <button type="button" onClick={() => { onPermissions(entry); onClose(); }}>
                <Lock size={14} /> {t('app.contextMenu.permissions', 'Permissions')}
            </button>
            <button type="button" onClick={() => { onCopyPath(entry.path); onClose(); }}>
                <Copy size={14} /> {t('app.contextMenu.copyPath', 'Copy path')}
            </button>
            <div className="context-menu-divider" />
            <button type="button" className="danger" onClick={() => { onDelete(entry); onClose(); }}>
                <Trash2 size={14} /> {t('app.contextMenu.delete', 'Delete')}{multi ? ` ${selectionCount} items` : ''}
            </button>
        </div>
    );
}
