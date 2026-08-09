import { useCallback, useEffect, useRef, useState } from 'react';
import api from '@/services/api';

// Saved table views (CRM-style) for one list page. Combines the page's
// BUILT-IN views (shipped in code, e.g. "Expiring soon") with the current
// user's saved views from /api/v1/views, and applies a view by handing its
// state to the page's `apply` adapter.
//
//   const views = useTableViews({
//     page: 'domains',
//     builtinViews: [{ name: 'Expiring soon', state: { sorts: [{ key: 'expires', direction: 'asc' }] } }],
//     capture: () => ({ status, search, sorts, hiddenKeys }),   // read current table state
//     apply: (state) => { …setters… },                           // push a view's state back
//   });
//   <ViewMenu {...views.menuProps} />
//
// On first load the user's DEFAULT view (if any) is applied automatically.
export function useTableViews({ page, builtinViews = [], capture, apply }) {
    const [userViews, setUserViews] = useState([]);
    const [activeKey, setActiveKey] = useState(null);
    const [loading, setLoading] = useState(true);
    const appliedInitial = useRef(false);

    const keyOf = (view) => (view.builtin ? `builtin:${view.name}` : `user:${view.id}`);
    const allViews = [
        ...builtinViews.map((v) => ({ ...v, builtin: true })),
        ...userViews,
    ];
    const activeView = allViews.find((v) => keyOf(v) === activeKey) || null;

    // Dirty tracking: is the live table state different from the active view's
    // saved state? Key-order-agnostic, and hiddenKeys compares as a set (its
    // order is meaningless). Sorts stay order-sensitive — order IS priority.
    const normalize = (state) => {
        if (!state || typeof state !== 'object') return {};
        const out = {};
        for (const key of Object.keys(state).sort()) {
            const value = state[key];
            if (value === undefined) continue;
            out[key] = key === 'hiddenKeys' && Array.isArray(value) ? [...value].sort() : value;
        }
        return out;
    };
    const isDirty = !!activeView && (
        JSON.stringify(normalize(capture())) !== JSON.stringify(normalize(activeView.state))
    );

    useEffect(() => {
        if (!page) { setLoading(false); return undefined; }
        let cancelled = false;
        setLoading(true);
        api.getViews(page)
            .then((resp) => {
                if (cancelled) return;
                const views = resp?.views || [];
                setUserViews(views);
                // Auto-apply the user's default view once per mount.
                if (!appliedInitial.current) {
                    appliedInitial.current = true;
                    const defaultView = views.find((v) => v.is_default);
                    if (defaultView) {
                        apply(defaultView.state || {});
                        setActiveKey(keyOf(defaultView));
                    }
                }
            })
            .catch(() => { /* views are an enhancement — the page works without them */ })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page]);

    const applyView = useCallback((view) => {
        apply(view.state || {});
        setActiveKey(keyOf(view));
    }, [apply]);

    const saveView = useCallback(async (name, { setDefault = false } = {}) => {
        const created = await api.createView({
            page,
            name,
            state: capture(),
            is_default: setDefault,
        });
        setUserViews((prev) => [
            ...(setDefault ? prev.map((v) => ({ ...v, is_default: false })) : prev),
            created,
        ]);
        setActiveKey(keyOf(created));
        return created;
    }, [page, capture]);

    // Update the active saved view's state from the current table state.
    const updateActiveView = useCallback(async () => {
        if (!activeView || activeView.builtin) return null;
        const updated = await api.updateView(activeView.id, { state: capture() });
        setUserViews((prev) => prev.map((v) => (v.id === updated.id ? updated : v)));
        return updated;
    }, [activeView, capture]);

    const toggleDefault = useCallback(async (view) => {
        if (view.builtin) return;
        const next = !view.is_default;
        const updated = await api.updateView(view.id, { is_default: next });
        setUserViews((prev) => prev.map((v) => ({
            ...v,
            is_default: v.id === updated.id ? updated.is_default : (next ? false : v.is_default),
        })));
    }, []);

    const removeView = useCallback(async (view) => {
        if (view.builtin) return;
        await api.deleteView(view.id);
        setUserViews((prev) => prev.filter((v) => v.id !== view.id));
        if (activeKey === keyOf(view)) setActiveKey(null);
    }, [activeKey]);

    // Re-apply the active view's saved state (discards live tweaks).
    const resetView = useCallback(() => {
        if (activeView) applyView(activeView);
    }, [activeView, applyView]);

    return {
        builtinViews: allViews.filter((v) => v.builtin),
        userViews,
        activeView,
        isDirty,
        loading,
        applyView,
        saveView,
        updateActiveView,
        toggleDefault,
        removeView,
        resetView,
    };
}

export default useTableViews;
