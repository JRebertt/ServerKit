import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Activity, Bell, BookOpenCheck, Building2, Check, ChevronUp,
    Command, Server, ShieldAlert, Sparkles, X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import api from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { useNotifications } from '../contexts/NotificationsContext';
import { useOperations } from '../contexts/OperationsContext';
import { useServerkitAI } from '../contexts/AIContext';
import { useWalkthroughs } from '../contexts/walkthroughContextValue';
import { useWorkspace } from '../contexts/WorkspaceContext';
import { timeAgo } from '../utils/time';

const SERVER_SCOPE_KEY = 'serverkit.activeServerScope';

function readServerScope() {
    try { return localStorage.getItem(SERVER_SCOPE_KEY) || 'local'; } catch { return 'local'; }
}

function statusTone(server) {
    const value = String(server?.status || server?.agent_status || '').toLowerCase();
    if (['offline', 'failed', 'error', 'disconnected'].some((state) => value.includes(state))) return 'down';
    if (['pending', 'warning', 'idle', 'unknown'].some((state) => value.includes(state))) return 'idle';
    return 'online';
}

function alertTone(item) {
    if (item?.severity === 'critical') return 'critical';
    if (item?.severity === 'warning') return 'warning';
    if (item?.severity === 'success') return 'success';
    return 'info';
}

function AlertsPanel({ onClose }) {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const notifications = useNotifications();
    const [view, setView] = useState('attention');
    const {
        items = [], loading, markRead, markAllRead, dismissNotice,
    } = notifications || {};

    const visibleItems = useMemo(() => (
        view === 'all'
            ? items
            : items.filter((item) => (
                item.kind === 'notice'
                || item.severity === 'critical'
                || item.severity === 'warning'
            ))
    ), [items, view]);

    const openItem = (item) => {
        if (item.kind !== 'notice' && !item.read && markRead) markRead(item.delivery_id);
        if (item.action_path) {
            navigate(item.action_path);
            onClose();
        }
    };

    return (
        <section className="shell-panel shell-alerts" aria-label={t('notifications.heading', 'Notifications')}>
            <header className="shell-panel__head">
                <div className="shell-panel__tabs" role="tablist">
                    <button
                        type="button"
                        className={view === 'attention' ? 'is-active' : ''}
                        onClick={() => setView('attention')}
                        role="tab"
                        aria-selected={view === 'attention'}
                    >
                        {t('app.operationsDock.needsAttention', 'Needs attention')}
                    </button>
                    <button
                        type="button"
                        className={view === 'all' ? 'is-active' : ''}
                        onClick={() => setView('all')}
                        role="tab"
                        aria-selected={view === 'all'}
                    >
                        {t('notifications.everything', 'Everything')}
                    </button>
                </div>
                <span className="shell-panel__spacer" />
                {items.some((item) => item.kind !== 'notice' && !item.read) && (
                    <button type="button" className="shell-panel__action" onClick={markAllRead}>
                        <Check size={13} /> {t('notifications.markAllRead', 'Mark all read')}
                    </button>
                )}
                <button
                    type="button"
                    className="shell-panel__close"
                    onClick={onClose}
                    aria-label={t('common.actions.close', 'Close')}
                >
                    <X size={15} />
                </button>
            </header>

            <div className="shell-alerts__list">
                {loading && items.length === 0 ? (
                    <div className="shell-panel__empty">{t('common.state.loading', 'Loading')}</div>
                ) : visibleItems.length === 0 ? (
                    <div className="shell-panel__empty">{t('notifications.empty', 'You’re all caught up.')}</div>
                ) : visibleItems.map((item) => (
                    <div
                        key={item.delivery_id || item.notice_id}
                        className={`shell-alerts__row is-${alertTone(item)}${item.read ? ' is-read' : ''}`}
                    >
                        <button type="button" className="shell-alerts__hit" onClick={() => openItem(item)}>
                            <span className="shell-alerts__dot" aria-hidden="true" />
                            <span className="shell-alerts__copy">
                                <strong>{item.title}</strong>
                                {item.body && <span>{item.body}</span>}
                            </span>
                            <span className="shell-alerts__meta mono">
                                {item.kind === 'notice'
                                    ? item.action_label || t('notifications.review', 'Review')
                                    : timeAgo(item.created_at)}
                            </span>
                        </button>
                        {item.kind === 'notice' && (
                            <button
                                type="button"
                                className="shell-alerts__dismiss"
                                onClick={() => dismissNotice?.(item.notice_id)}
                                aria-label={t('notifications.dismissItem', 'Dismiss {{title}}', { title: item.title })}
                            >
                                <X size={14} />
                            </button>
                        )}
                    </div>
                ))}
            </div>

            <footer className="shell-panel__footer">
                <span>{t('notifications.recentActivity', 'Recent system and delivery activity')}</span>
                <button type="button" onClick={() => { navigate('/notifications'); onClose(); }}>
                    {t('notifications.seeAll', 'See all notifications')}
                </button>
            </footer>
        </section>
    );
}

export default function GlobalStatusBar({ onOpenPalette }) {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { isAdmin } = useAuth();
    const notifications = useNotifications();
    const {
        activeOperations, attentionOperations, collapsed, setCollapsed,
    } = useOperations();
    const {
        open: recipesOpen, setOpen: setRecipesOpen, activeWalkthrough, activeProgress,
    } = useWalkthroughs();
    const {
        isOpen: assistantOpen, unread: assistantUnread, close: closeAssistant, toggle: toggleAssistant,
    } = useServerkitAI();
    const {
        activeWorkspaceId, clearActiveWorkspace, setActiveWorkspace,
    } = useWorkspace();
    const [workspaces, setWorkspaces] = useState([]);
    const [servers, setServers] = useState([]);
    const [serverId, setServerId] = useState(readServerScope);
    const [alertsOpen, setAlertsOpen] = useState(false);
    const [setupHealth, setSetupHealth] = useState(null);

    useEffect(() => {
        let alive = true;
        Promise.all([
            api.getWorkspaces().catch(() => ({ workspaces: [] })),
            api.getAvailableServers().catch(() => []),
            isAdmin ? api.getSetupHealth().catch(() => null) : Promise.resolve(null),
        ]).then(([workspaceData, serverData, healthData]) => {
            if (!alive) return;
            setWorkspaces(workspaceData?.workspaces || []);
            setServers(Array.isArray(serverData) ? serverData : []);
            setSetupHealth(healthData);
        });
        return () => { alive = false; };
    }, [isAdmin]);

    useEffect(() => {
        const availableIds = new Set(['local', ...servers.map((server) => String(server.id))]);
        if (!availableIds.has(String(serverId))) setServerId('local');
    }, [serverId, servers]);

    useEffect(() => {
        if (!alertsOpen) return undefined;
        notifications?.refresh?.();
        const onEscape = (event) => {
            if (event.key === 'Escape') setAlertsOpen(false);
        };
        window.addEventListener('keydown', onEscape);
        return () => window.removeEventListener('keydown', onEscape);
    }, [alertsOpen, notifications]);

    const workspaceName = workspaces.find(
        (workspace) => String(workspace.id) === activeWorkspaceId,
    )?.name || t('app.workspaceSwitcher.allWorkspaces', 'All workspaces');
    const scopedServers = useMemo(() => ([
        { id: 'local', name: t('app.dashboard.localThisServer', 'Local (this server)'), status: 'online' },
        ...servers.filter((server) => String(server.id) !== 'local'),
    ]), [servers, t]);
    const selectedServer = scopedServers.find(
        (server) => String(server.id) === String(serverId),
    ) || scopedServers[0];
    const runningCount = activeOperations.length;
    const attentionCount = attentionOperations.length;
    const unreadCount = notifications?.unreadCount || 0;
    const setupSummary = setupHealth?.summary;

    const changeWorkspace = (event) => {
        const value = event.target.value;
        if (value === 'all') clearActiveWorkspace();
        else {
            const workspace = workspaces.find((item) => String(item.id) === value);
            if (workspace) setActiveWorkspace(workspace);
        }
        window.location.reload();
    };

    const changeServer = (event) => {
        const value = event.target.value;
        setServerId(value);
        try { localStorage.setItem(SERVER_SCOPE_KEY, value); } catch { /* ignore */ }
        window.dispatchEvent(new CustomEvent('serverkit:server-scope', { detail: { serverId: value } }));
    };

    const toggleOperations = () => {
        setAlertsOpen(false);
        setRecipesOpen(false);
        closeAssistant();
        setCollapsed(!collapsed);
    };

    const toggleRecipes = () => {
        setCollapsed(true);
        setAlertsOpen(false);
        closeAssistant();
        setRecipesOpen(!recipesOpen);
    };

    const toggleAlerts = () => {
        setCollapsed(true);
        setRecipesOpen(false);
        closeAssistant();
        setAlertsOpen(!alertsOpen);
    };

    const openAssistant = () => {
        setCollapsed(true);
        setRecipesOpen(false);
        setAlertsOpen(false);
        toggleAssistant();
    };

    return (
        <>
            {alertsOpen && <AlertsPanel onClose={() => setAlertsOpen(false)} />}
            <footer className="global-statusbar" aria-label={t('app.statusbar.shellStatus', 'ServerKit status and tools')}>
                <label className="statusbar-select statusbar-select--workspace" title={t('app.workspaceSwitcher.activeWorkspace', 'Active workspace')}>
                    <Building2 size={13} aria-hidden="true" />
                    <span className="statusbar-select__value">{workspaceName}</span>
                    <ChevronUp size={12} aria-hidden="true" />
                    <select value={activeWorkspaceId} onChange={changeWorkspace} aria-label={t('app.workspaceSwitcher.activeWorkspace', 'Active workspace')}>
                        <option value="all">{t('app.workspaceSwitcher.allWorkspaces', 'All workspaces')}</option>
                        {workspaces.map((workspace) => (
                            <option key={workspace.id} value={String(workspace.id)}>{workspace.name}</option>
                        ))}
                    </select>
                </label>

                <span className="global-statusbar__separator" aria-hidden="true" />

                <label className="statusbar-select" title={t('app.statusbar.activeServer', 'Active server')}>
                    <span className={`global-statusbar__dot is-${statusTone(selectedServer)}`} aria-hidden="true" />
                    <Server size={13} className="global-statusbar__mobile-icon" aria-hidden="true" />
                    <span className="statusbar-select__value mono">{selectedServer.name || selectedServer.id}</span>
                    <ChevronUp size={12} aria-hidden="true" />
                    <select value={String(serverId)} onChange={changeServer} aria-label={t('app.statusbar.activeServer', 'Active server')}>
                        {scopedServers.map((server) => (
                            <option key={server.id} value={String(server.id)}>{server.name || server.id}</option>
                        ))}
                    </select>
                </label>

                <span className="global-statusbar__separator" aria-hidden="true" />

                <button
                    type="button"
                    className={`global-statusbar__segment${!collapsed ? ' is-active' : ''}`}
                    onClick={toggleOperations}
                    aria-expanded={!collapsed}
                    aria-label={t('app.operationsDock.title', 'Operations')}
                >
                    <Activity size={13} />
                    <span>{t('app.operationsDock.title', 'Operations')}</span>
                    <span className="global-statusbar__muted mono">
                        {runningCount
                            ? t('app.statusbar.runningCount', '{{count}} running', { count: runningCount })
                            : t('app.statusbar.idle', 'idle')}
                    </span>
                    {attentionCount > 0 && <span className="global-statusbar__pip is-warning" aria-hidden="true" />}
                </button>

                <span className="global-statusbar__separator" aria-hidden="true" />
                <button
                    type="button"
                    className={`global-statusbar__segment${recipesOpen ? ' is-active' : ''}`}
                    onClick={toggleRecipes}
                    aria-expanded={recipesOpen}
                    aria-label={activeWalkthrough?.title || t('app.walkthroughs.recipes', 'Recipes')}
                >
                    <BookOpenCheck size={13} />
                    <span>{activeWalkthrough?.title || t('app.walkthroughs.recipes', 'Recipes')}</span>
                    {activeWalkthrough && (
                            <span className="global-statusbar__muted mono">{activeProgress?.count || 0}/{activeProgress?.total || 0}</span>
                    )}
                </button>

                <span className="global-statusbar__spacer" />

                {setupSummary && (
                    <button
                        type="button"
                        className="global-statusbar__segment global-statusbar__setup"
                        onClick={() => navigate('/monitoring/doctor')}
                        title={t('app.setupHealthWidget.setupHealth', 'Setup Health')}
                    >
                        <ShieldAlert size={13} />
                        <span className="global-statusbar__muted mono">
                            {t('app.statusbar.setupScore', 'setup {{score}}%', { score: setupSummary.score })}
                        </span>
                        <progress max="100" value={setupSummary.score} aria-label={t('app.setupHealthWidget.progress', 'Setup health progress')} />
                    </button>
                )}

                <span className="global-statusbar__separator" aria-hidden="true" />

                <button
                    type="button"
                    className={`global-statusbar__segment${alertsOpen ? ' is-active' : ''}`}
                    onClick={toggleAlerts}
                    aria-expanded={alertsOpen}
                    aria-label={t('app.statusbar.alerts', 'Alerts')}
                >
                    <Bell size={13} />
                    <span>{t('app.statusbar.alerts', 'Alerts')}</span>
                    {unreadCount > 0 && <span className="global-statusbar__muted mono">{unreadCount}</span>}
                    {unreadCount > 0 && <span className="global-statusbar__pip is-critical" aria-hidden="true" />}
                </button>

                <span className="global-statusbar__separator" aria-hidden="true" />

                <button
                    type="button"
                    className={`global-statusbar__segment${assistantOpen ? ' is-active' : ''}`}
                    onClick={openAssistant}
                    aria-expanded={assistantOpen}
                    aria-label={t('app.ai.assistant', 'Assistant')}
                >
                    <Sparkles size={13} />
                    <span>{t('app.ai.assistant', 'Assistant')}</span>
                    {assistantUnread > 0 && <span className="global-statusbar__muted mono">{assistantUnread}</span>}
                </button>

                <span className="global-statusbar__separator" aria-hidden="true" />

                <button
                    type="button"
                    className="global-statusbar__segment global-statusbar__command"
                    onClick={onOpenPalette}
                    title={t('palette.label', 'Command palette')}
                    aria-label={t('palette.label', 'Command palette')}
                >
                    <Command size={12} />
                    <span className="mono">{t('app.statusbar.commandShortcut', 'Ctrl K')}</span>
                </button>
            </footer>
        </>
    );
}
