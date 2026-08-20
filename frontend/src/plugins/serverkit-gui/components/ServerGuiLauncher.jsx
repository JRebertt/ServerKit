import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import ServerGui from './ServerGui.jsx';
import { useTranslation } from 'serverkit-sdk';

/**
 * Floating launcher that appears only on /servers/:id pages.
 * Opens the streaming desktop in a modal.
 *
 * This is a temporary integration until the PluginLoader exposes a
 * `serverDetailTab` extension point — at which point we'll mount
 * ServerGui directly as a tab.
 */
const SERVER_DETAIL_RE = /^\/servers\/([^/]+)(\/[^/]*)?$/;

export default function ServerGuiLauncher({ api }) {
    const { t } = useTranslation();
    const location = useLocation();
    const [open, setOpen] = useState(false);

    const match = SERVER_DETAIL_RE.exec(location.pathname);
    const serverId = match ? match[1] : null;

    useEffect(() => {
        if (!serverId) setOpen(false);
    }, [serverId]);

    if (!serverId) return null;

    return (
        <>
            <button type="button"
                className="sk-gui-launcher"
                onClick={() => setOpen(true)}
                title={t('gui.launcher.open', 'Open desktop view')}
            >
                <DesktopIcon />
                <span>{t('gui.launcher.label', 'Desktop')}</span>
            </button>

            {open && (
                <div className="sk-gui-modal" onClick={() => setOpen(false)}>
                    <div className="sk-gui-modal__inner" onClick={e => e.stopPropagation()}>
                        <header className="sk-gui-modal__header">
                            <h3>{t('gui.launcher.title', 'Desktop view')}</h3>
                            <button type="button"
                                className="sk-gui-modal__close"
                                onClick={() => setOpen(false)}
                                aria-label={t('common.actions.close', 'Close')}
                            >
                                ×
                            </button>
                        </header>
                        <div className="sk-gui-modal__body">
                            <ServerGui api={api} serverId={serverId} />
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}

const DesktopIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="4" width="20" height="14" rx="2" />
        <line x1="8" y1="22" x2="16" y2="22" />
        <line x1="12" y1="18" x2="12" y2="22" />
    </svg>
);
