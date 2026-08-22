import { Maximize2, Minimize2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { useNotifications } from '../contexts/NotificationsContext';
import { useOperations } from '../contexts/OperationsContext';
import { useServerkitAI } from '../contexts/AIContext';
import { useShellDock } from '../contexts/ShellDockContext';
import { useWalkthroughs } from '../contexts/walkthroughContextValue';

// Shared header strip for every shell console panel. Wherever a panel opens
// (Operations, Alerts, Recipes bottom console; Assistant right drawer), the
// same four tabs sit on top so switching surfaces is one click, like moving
// between tabs of a single console rather than four unrelated popovers.
export default function ShellDockTabs({ controls = null, expandable = true }) {
    const { t } = useTranslation();
    const {
        activeTab, openTab, close, expanded, setExpanded,
    } = useShellDock();
    const { activeOperations, attentionOperations } = useOperations();
    const notifications = useNotifications();
    const { activeWalkthrough, activeProgress } = useWalkthroughs();
    const { unread: assistantUnread } = useServerkitAI();

    const operationsBadge = activeOperations.length + attentionOperations.length;
    const tabs = [
        { id: 'ops', label: t('app.operationsDock.title', 'Operations'), badge: operationsBadge || null },
        { id: 'alerts', label: t('app.statusbar.alerts', 'Alerts'), badge: notifications?.unreadCount || null },
        {
            id: 'recipes',
            label: t('app.walkthroughs.recipes', 'Recipes'),
            badge: activeWalkthrough
                ? `${activeProgress?.count || 0}/${activeProgress?.total || 0}`
                : null,
        },
        { id: 'assistant', label: t('app.ai.assistant', 'Assistant'), badge: assistantUnread || null },
    ];

    return (
        <div className="shell-dock-tabs" role="tablist" aria-label={t('app.statusbar.consolePanels', 'Console panels')}>
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === tab.id}
                    className={`shell-dock-tabs__tab${activeTab === tab.id ? ' is-active' : ''}`}
                    onClick={() => openTab(tab.id)}
                >
                    {tab.label}
                    {tab.badge ? <span className="shell-dock-tabs__badge mono">{tab.badge}</span> : null}
                </button>
            ))}
            <span className="shell-dock-tabs__spacer" />
            {controls}
            {expandable && (
                <button
                    type="button"
                    className="shell-dock-tabs__control"
                    onClick={() => setExpanded(!expanded)}
                    aria-pressed={expanded}
                    aria-label={expanded
                        ? t('app.statusbar.collapsePanel', 'Collapse panel')
                        : t('app.statusbar.expandPanel', 'Expand panel')}
                    title={expanded
                        ? t('app.statusbar.collapsePanel', 'Collapse panel')
                        : t('app.statusbar.expandPanel', 'Expand panel')}
                >
                    {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                </button>
            )}
            <button
                type="button"
                className="shell-dock-tabs__control"
                onClick={close}
                aria-label={t('common.actions.close', 'Close')}
                title={t('app.statusbar.closeEsc', 'Close (Esc)')}
            >
                <X size={15} />
            </button>
        </div>
    );
}
