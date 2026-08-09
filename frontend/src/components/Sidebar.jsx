import React, { useState, useEffect, useRef, useMemo } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { useLayout } from '../contexts/LayoutContext';
import { Star, Settings, LogOut, Sun, Moon, Monitor, ChevronRight, ChevronDown, ChevronUp, Layers, Palette, PanelLeft, PanelLeftClose, PanelTop, Check, X, Server } from 'lucide-react';
import { api } from '../services/api';
import WorkspaceSwitcher from './WorkspaceSwitcher';
import NotificationBell from './NotificationBell';
import { SIDEBAR_CATEGORIES, CATEGORY_LABELS, SIDEBAR_PRESETS, getHiddenItemIds, getVisibleItems, applyWorkspaceNavPermissions } from './sidebarItems';
import { useContributions } from '../plugins/contributions';
import { sanitizeSvgInner } from '../utils/sanitizeSvg';
import useModules from '../hooks/useModules';
import useDevMode from '../hooks/useDevMode';
import QuickCreate from './QuickCreate';

const Sidebar = ({ mobileOpen = false, isMobile = false, onMobileClose = () => {} }) => {
    const { user, logout, updateUser, hasPermission } = useAuth();
    const { theme, resolvedTheme, setTheme, whiteLabel } = useTheme();
    const { layout, setLayout } = useLayout();
    const navigate = useNavigate();
    const [menuOpen, setMenuOpen] = useState(false);
    const [wpInstalled, setWpInstalled] = useState(false);
    const [gpuAvailable, setGpuAvailable] = useState(false);
    const menuRef = useRef(null);
    const sidebarRef = useRef(null);

    // When collapsed to a drawer and closed, take the whole subtree out of the
    // tab order and the accessibility tree. `inert` is set imperatively so it
    // works on React 18 (which doesn't forward the attribute).
    useEffect(() => {
        const el = sidebarRef.current;
        if (!el) return;
        el.toggleAttribute('inert', isMobile && !mobileOpen);
    }, [isMobile, mobileOpen]);

    // Open drawer: focus the first control, trap Tab, close on Escape, and
    // return focus to the menu toggle on close.
    useEffect(() => {
        if (!isMobile || !mobileOpen) return undefined;
        const el = sidebarRef.current;
        if (!el) return undefined;

        const getFocusable = () => Array.from(
            el.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )
        ).filter((node) => node.offsetParent !== null);

        const focusables = getFocusable();
        (focusables[0] || el).focus();

        const handleKeyDown = (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                onMobileClose();
                return;
            }
            if (e.key !== 'Tab') return;
            const items = getFocusable();
            if (items.length === 0) return;
            const first = items[0];
            const last = items[items.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };

        el.addEventListener('keydown', handleKeyDown);
        return () => {
            el.removeEventListener('keydown', handleKeyDown);
            document.querySelector('.mobile-topbar__toggle')?.focus();
        };
    }, [isMobile, mobileOpen, onMobileClose]);

    // Close the user menu on outside click or Escape; return focus to the
    // trigger when Escape dismisses it.
    useEffect(() => {
        if (!menuOpen) return undefined;
        const handleClickOutside = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) {
                setMenuOpen(false);
            }
        };
        const handleKeyDown = (e) => {
            if (e.key === 'Escape') {
                setMenuOpen(false);
                menuRef.current?.querySelector('.user-mini')?.focus();
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('keydown', handleKeyDown);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [menuOpen]);

    // Check if WordPress is installed
    useEffect(() => {
        api.getWordPressStatus()
            .then(data => setWpInstalled(!!data?.installed))
            .catch(() => setWpInstalled(false));
    }, []);

    // Hide GPU Monitor when the host has no GPU (mirrors the wpInstalled gate).
    useEffect(() => {
        api.getGpuInfo()
            .then(data => setGpuAvailable(!!data?.available))
            .catch(() => setGpuAvailable(false));
    }, []);

    // Feature-module toggles (WordPress; Email is now an extension). Default to
    // enabled until the shared module state loads so items never flicker/hide.
    const { isEnabled: isModuleEnabled } = useModules();
    const wordpressEnabled = isModuleEnabled('wordpress');

    // Developer-only items (Test Sandbox) — same source the route guard reads.
    const devMode = useDevMode();

    const conditions = { wpInstalled, gpuAvailable, wordpressEnabled, devMode };
    const currentPreset = user?.sidebar_config?.preset || 'recommended';
    const [manualExpanded, setManualExpanded] = useState({});
    const [autoExpanded, setAutoExpanded] = useState(null);
    const location = useLocation();

    const toggleExpand = (itemId) => {
        const currentlyExpanded = manualExpanded[itemId] ?? (autoExpanded === itemId);
        setManualExpanded(prev => ({ ...prev, [itemId]: !currentlyExpanded }));
    };

    const handlePresetSwitch = (presetKey) => {
        if (presetKey === currentPreset) return;
        const config = { preset: presetKey, hiddenItems: [] };
        // Update locally first (instant), persist to backend in background
        updateUser({ sidebar_config: config });
        api.updateCurrentUser({ sidebar_config: config }).catch(() => {});
    };

    const { nav: pluginNav, tabs: pluginTabs } = useContributions();

    const visibleItems = useMemo(() => {
        const core = getVisibleItems(user?.sidebar_config);
        const hiddenIds = getHiddenItemIds(user?.sidebar_config);
        // Merge contributed nav items, dedup by id (core wins). Plugins
        // can claim a category; default to 'system' so they always land
        // somewhere visible.
        const existingIds = new Set(core.map((i) => i.id));
        const fromPlugins = (pluginNav || [])
            .filter((item) => (
                item && item.id && item.route
                && !existingIds.has(item.id)
                && !hiddenIds.has(item.id)
            ))
            .map((item) => ({
                ...item,
                category: item.category || 'system',
            }));
        // Top-level items can gate on a runtime condition (e.g. GPU Monitor
        // only when a GPU is present, the Email/WordPress modules being
        // enabled, or dev-only tooling), mirroring sub-item requiresCondition.
        const conds = { wpInstalled, gpuAvailable, wordpressEnabled, devMode };
        let items = [...core, ...fromPlugins].filter(
            (item) => !item.requiresCondition || conds[item.requiresCondition]
        );
        // Per-user feature permissions: a user whose files.read is revoked
        // (custom permissions override the role template) gets 403s from every
        // /api/v1/files endpoint, so don't surface the File Manager at all.
        if (!hasPermission('files', 'read')) {
            items = items.filter((item) => item.id !== 'files');
        }
        // Extension-contributed tab-group tabs (#43) keep the host group's
        // sidebar item lit on extension-owned tab routes (group id == sidebar
        // item id) — the core matchPrefixes only cover the group's own tabs.
        const tabPrefixes = {};
        for (const t of (pluginTabs || [])) {
            if (!t || !t.group || !t.to) continue;
            (tabPrefixes[t.group] = tabPrefixes[t.group] || []).push(t.to);
        }
        items = items.map((item) => (
            tabPrefixes[item.id]
                ? { ...item, matchPrefixes: [...(item.matchPrefixes || []), ...tabPrefixes[item.id]] }
                : item
        ));
        // Apply workspace-level nav permissions if an active workspace is set
        // and it defines a nav map. This lets a workspace restrict which sidebar
        // items its members see based on their effective workspace role.
        const activeWorkspaceRaw = localStorage.getItem('active_workspace');
        let activeWorkspace = null;
        if (activeWorkspaceRaw) {
            try {
                activeWorkspace = JSON.parse(activeWorkspaceRaw);
            } catch {
                activeWorkspace = null;
            }
        }
        return applyWorkspaceNavPermissions(items, activeWorkspace, user);
    }, [user?.sidebar_config, pluginNav, pluginTabs, wpInstalled, gpuAvailable, wordpressEnabled, devMode, user, hasPermission]);

    // Group visible items by category
    const groupedItems = useMemo(() => {
        const groups = {};
        for (const cat of SIDEBAR_CATEGORIES) {
            const items = visibleItems.filter(item => item.category === cat);
            if (items.length > 0) {
                groups[cat] = items;
            }
        }
        return groups;
    }, [visibleItems]);

    // Auto-expand the active parent (or parent of active sub-item), auto-close others
    useEffect(() => {
        const path = location.pathname;
        let activeParent = null;
        for (const item of visibleItems) {
            if (!item.subItems?.length) continue;
            // Expand if on the parent route itself or any sub-item route
            if (path === item.route || path.startsWith(item.route + '/') ||
                item.subItems.some(sub => path === sub.route || path.startsWith(sub.route + '/'))) {
                activeParent = item.id;
                break;
            }
        }
        setAutoExpanded(activeParent);
        setManualExpanded({});
    }, [location.pathname, visibleItems]);

    const renderNavItem = (item) => {
        const hasChildren = item.subItems && item.subItems.length > 0;
        // Show expanded if manually toggled OR auto-expanded by active route
        const isExpanded = manualExpanded[item.id] ?? (autoExpanded === item.id);
        const visibleSubs = hasChildren
            ? item.subItems.filter(sub => !sub.requiresCondition || conditions[sub.requiresCondition])
            : [];
        // Items can claim extra active paths (e.g. Servers stays lit across its
        // Agent Fleet / Fleet Monitor / Cloud / Config Templates tabs) so the
        // highlight doesn't drop when a sub-tab lives on its own route.
        const groupActive = item.matchPrefixes?.some(
            (p) => location.pathname === p || location.pathname.startsWith(p + '/')
        );

        return (
            <React.Fragment key={item.id}>
                <div className={`nav-item-row ${hasChildren ? 'has-children' : ''}`}>
                    <NavLink
                        to={item.route}
                        className={({ isActive }) => `nav-item ${isActive || groupActive ? 'active' : ''}`}
                        end={item.end || hasChildren}
                    >
                        <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            aria-hidden="true" focusable="false"
                            dangerouslySetInnerHTML={{ __html: sanitizeSvgInner(item.icon) }}
                        />
                        {item.label}
                    </NavLink>
                    {visibleSubs.length > 0 && (
                        <button
                            type="button"
                            className={`nav-expand-btn ${isExpanded ? 'expanded' : ''}`}
                            aria-expanded={isExpanded}
                            aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${item.label}`}
                            onClick={(e) => { e.stopPropagation(); toggleExpand(item.id); }}
                        >
                            <ChevronRight size={14} aria-hidden="true" />
                        </button>
                    )}
                </div>
                {isExpanded && visibleSubs.map(sub => (
                    <NavLink
                        key={sub.id}
                        to={sub.route}
                        className={({ isActive }) => `nav-item nav-sub-item ${isActive ? 'active' : ''}`}
                    >
                        <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            aria-hidden="true" focusable="false"
                            dangerouslySetInnerHTML={{ __html: sanitizeSvgInner(sub.icon) }}
                        />
                        {sub.label}
                    </NavLink>
                ))}
            </React.Fragment>
        );
    };

    return (
        <aside
            ref={sidebarRef}
            id="primary-navigation"
            className={`sidebar${mobileOpen ? ' sidebar--mobile-open' : ''}`}
            aria-label="Main navigation"
        >
            {isMobile && (
                <button
                    type="button"
                    className="sidebar__close"
                    aria-label="Close navigation menu"
                    onClick={onMobileClose}
                >
                    <X size={20} aria-hidden="true" />
                </button>
            )}
            {whiteLabel.enabled ? (
                <div className="brand-section brand-section--custom">
                    {whiteLabel.mode === 'image_full' ? (
                        <div className="brand-custom-banner">
                            {whiteLabel.logoData ? (
                                <img src={whiteLabel.logoData} alt={whiteLabel.brandName || 'Brand'} />
                            ) : (
                                <Layers size={32} />
                            )}
                        </div>
                    ) : whiteLabel.mode === 'text_only' ? (
                        <span className="brand-custom-text">
                            {whiteLabel.brandName || 'Brand'}
                        </span>
                    ) : (
                        <>
                            <div className="brand-custom-logo">
                                {whiteLabel.logoData ? (
                                    <img src={whiteLabel.logoData} alt={whiteLabel.brandName || 'Brand'} />
                                ) : (
                                    <Layers size={20} />
                                )}
                            </div>
                            <span className="brand-custom-text">
                                {whiteLabel.brandName || 'Brand'}
                            </span>
                        </>
                    )}
                </div>
            ) : (
                <div className="brand-section">
                    <div className="brand-logo">
                        <Server size={19} strokeWidth={2} aria-hidden="true" />
                    </div>
                    <span className="brand-text">ServerKit</span>
                    <a
                        href="https://github.com/jhd3197/ServerKit"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="brand-star"
                        aria-label="Star ServerKit on GitHub"
                        title="Star on GitHub"
                    >
                        <Star size={14} aria-hidden="true" />
                    </a>
                </div>
            )}

            <WorkspaceSwitcher />

            <div className="nav-scroll">
                {SIDEBAR_CATEGORIES.map(cat => {
                    const items = groupedItems[cat];
                    if (!items) return null;
                    return (
                        <React.Fragment key={cat}>
                            <div className="nav-category">{CATEGORY_LABELS[cat]}</div>
                            <nav className="nav">
                                {items.map(renderNavItem)}
                            </nav>
                        </React.Fragment>
                    );
                })}
            </div>

            {import.meta.env.DEV && (
                <>
                    <div className="nav-category nav-category--dev">Dev Tools</div>
                    <nav className="nav">
                        <NavLink
                            to="/app-map"
                            className={({ isActive }) => `nav-item nav-item--dev ${isActive ? 'active' : ''}`}
                        >
                            <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/>
                                <line x1="8" y1="2" x2="8" y2="18"/>
                                <line x1="16" y1="6" x2="16" y2="22"/>
                            </svg>
                            App Map
                        </NavLink>
                        <NavLink
                            to="/documentation"
                            className={({ isActive }) => `nav-item nav-item--dev ${isActive ? 'active' : ''}`}
                        >
                            <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
                            </svg>
                            Documentation
                        </NavLink>
                        <NavLink
                            to="/style-guide"
                            className={({ isActive }) => `nav-item nav-item--dev ${isActive ? 'active' : ''}`}
                        >
                            <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                <circle cx="13.5" cy="6.5" r="2.5"/><path d="M17 2H7a5 5 0 0 0-5 5v10a5 5 0 0 0 5 5h10a5 5 0 0 0 5-5V7a5 5 0 0 0-5-5z"/><path d="M9.5 14.5l-3 3"/><path d="M14.5 9.5l3-3"/>
                            </svg>
                            Style Guide
                        </NavLink>
                    </nav>
                </>
            )}

            <div className="sidebar-footer" ref={menuRef}>
                {menuOpen && (
                    <div className="user-context-menu" id="user-context-menu" aria-label="Account and preferences">
                        <div className="context-menu-section">
                            <div className="context-menu-label" id="theme-switcher-label">Theme</div>
                            <div className="theme-switcher" role="group" aria-labelledby="theme-switcher-label">
                                <button
                                    type="button"
                                    className={`theme-btn ${theme === 'dark' ? 'active' : ''}`}
                                    onClick={() => setTheme('dark')}
                                    aria-label="Dark theme"
                                    aria-pressed={theme === 'dark'}
                                    title="Dark"
                                >
                                    <Moon size={14} aria-hidden="true" />
                                </button>
                                <button
                                    type="button"
                                    className={`theme-btn ${theme === 'light' ? 'active' : ''}`}
                                    onClick={() => setTheme('light')}
                                    aria-label="Light theme"
                                    aria-pressed={theme === 'light'}
                                    title="Light"
                                >
                                    <Sun size={14} aria-hidden="true" />
                                </button>
                                <button
                                    type="button"
                                    className={`theme-btn ${theme === 'system' ? 'active' : ''}`}
                                    onClick={() => setTheme('system')}
                                    aria-label="System theme"
                                    aria-pressed={theme === 'system'}
                                    title="System"
                                >
                                    <Monitor size={14} aria-hidden="true" />
                                </button>
                            </div>
                        </div>
                        <div className="context-menu-section">
                            <div className="context-menu-label" id="layout-switcher-label">Layout</div>
                            <div className="theme-switcher" role="group" aria-labelledby="layout-switcher-label">
                                <button
                                    type="button"
                                    className={`theme-btn ${layout === 'sidebar' ? 'active' : ''}`}
                                    onClick={() => setLayout('sidebar')}
                                    aria-label="Sidebar layout"
                                    aria-pressed={layout === 'sidebar'}
                                    title="Sidebar"
                                >
                                    <PanelLeft size={14} aria-hidden="true" />
                                </button>
                                <button
                                    type="button"
                                    className={`theme-btn ${layout === 'rail' ? 'active' : ''}`}
                                    onClick={() => setLayout('rail')}
                                    aria-label="Compact rail layout"
                                    aria-pressed={layout === 'rail'}
                                    title="Compact"
                                >
                                    <PanelLeftClose size={14} aria-hidden="true" />
                                </button>
                                <button
                                    type="button"
                                    className={`theme-btn ${layout === 'topbar' ? 'active' : ''}`}
                                    onClick={() => setLayout('topbar')}
                                    aria-label="Top bar layout"
                                    aria-pressed={layout === 'topbar'}
                                    title="Top bar"
                                >
                                    <PanelTop size={14} aria-hidden="true" />
                                </button>
                            </div>
                        </div>
                        <div className="context-menu-section">
                            <div className="context-menu-label" id="sidebar-view-label">Sidebar View</div>
                            <div className="view-switcher" role="group" aria-labelledby="sidebar-view-label">
                                {Object.entries(SIDEBAR_PRESETS).map(([key, preset]) => (
                                    <button
                                        key={key}
                                        type="button"
                                        className={`view-btn ${currentPreset === key ? 'active' : ''}`}
                                        onClick={() => handlePresetSwitch(key)}
                                        aria-pressed={currentPreset === key}
                                        title={preset.description}
                                    >
                                        {preset.label}
                                        {currentPreset === key && <Check size={10} aria-hidden="true" />}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div className="context-menu-divider" />
                        <button
                            type="button"
                            className="context-menu-item"
                            onClick={() => { navigate('/settings/appearance'); setMenuOpen(false); }}
                        >
                            <Palette size={15} aria-hidden="true" />
                            Appearance
                            <ChevronRight size={14} className="context-menu-arrow" aria-hidden="true" />
                        </button>
                        <button
                            type="button"
                            className="context-menu-item"
                            onClick={() => { navigate('/settings/sidebar'); setMenuOpen(false); }}
                        >
                            <PanelLeft size={15} aria-hidden="true" />
                            Customize Sidebar
                            <ChevronRight size={14} className="context-menu-arrow" aria-hidden="true" />
                        </button>
                        <button
                            type="button"
                            className="context-menu-item"
                            onClick={() => { navigate('/settings'); setMenuOpen(false); }}
                        >
                            <Settings size={15} aria-hidden="true" />
                            All Settings
                            <ChevronRight size={14} className="context-menu-arrow" aria-hidden="true" />
                        </button>
                        <div className="context-menu-divider" />
                        <button type="button" className="context-menu-item danger" onClick={logout}>
                            <LogOut size={15} aria-hidden="true" />
                            Log out
                        </button>
                    </div>
                )}
                <div className="sidebar-footer__row">
                    <button
                        type="button"
                        className="user-mini"
                        onClick={() => setMenuOpen(!menuOpen)}
                        aria-haspopup="true"
                        aria-expanded={menuOpen}
                        aria-controls="user-context-menu"
                    >
                        <span className="user-avatar" aria-hidden="true">
                            {user?.username?.charAt(0).toUpperCase() || 'U'}
                        </span>
                        <span className="user-meta">
                            <span className="user-handle">{user?.username || 'User'}</span>
                            <span className="user-status">Online</span>
                        </span>
                        <ChevronUp size={14} className={`user-menu-arrow ${menuOpen ? 'open' : ''}`} aria-hidden="true" />
                    </button>
                    <QuickCreate />
                    <NotificationBell />
                </div>
            </div>
        </aside>
    );
};

export default Sidebar;
