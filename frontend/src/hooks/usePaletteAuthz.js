import { useMemo } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { SIDEBAR_ITEMS } from '../components/sidebarItems';

// Sidebar items that can never be hidden (Dashboard, Marketplace) — the palette
// mirrors the sidebar's `alwaysVisible` so a workspace nav map can't hide them.
const ALWAYS_VISIBLE = new Set(
    SIDEBAR_ITEMS.filter((i) => i.alwaysVisible).map((i) => i.id),
);

/**
 * The palette's authz gate (plan 41, Phase 1 #3). Mirrors exactly what the
 * sidebar shows so a member's palette can't surface admin surface:
 *   - `adminOnly` items require an admin.
 *   - Items tied to a sidebar `navId` respect the active workspace's per-role
 *     nav-permission map (same source as applyWorkspaceNavPermissions), which
 *     only ever NARROWS a member's view.
 *
 * Note: this intentionally does NOT apply personal sidebar-preset hiding — a page
 * you hid from your sidebar for tidiness stays reachable via the palette.
 */
export default function usePaletteAuthz() {
    const { isAdmin, hasPermission } = useAuth();

    return useMemo(() => {
        let navMap = null;
        let role = 'member';
        try {
            const raw = localStorage.getItem('active_workspace');
            const ws = raw ? JSON.parse(raw) : null;
            navMap = ws?.settings?.nav || null;
            role = ws?.my_effective_role || ws?.my_role || 'member';
        } catch {
            navMap = null;
        }

        const allowNav = (navId) => {
            if (!navId) return true;
            if (isAdmin) return true;
            if (ALWAYS_VISIBLE.has(navId)) return true;
            // Per-user feature permissions: files.read=false 403s every files
            // endpoint, so don't offer the File Manager in the palette either.
            if (navId === 'files' && !hasPermission('files', 'read')) return false;
            if (!navMap) return true;
            const allowed = navMap[role];
            if (!Array.isArray(allowed) || allowed.length === 0) return true;
            return allowed.includes(navId);
        };

        const allowItem = (item) => {
            if (item.adminOnly && !isAdmin) return false;
            return allowNav(item.navId);
        };

        return { isAdmin, allowNav, allowItem };
        // Recomputes on login/role change (isAdmin flips); the workspace nav map
        // is read from localStorage at build time and isn't otherwise reactive.
    }, [isAdmin, hasPermission]);
}
