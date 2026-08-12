import { useCallback, useMemo, useState } from 'react';
import useGridViews from './useGridViews';
import { cfgToEnvelope, envelopeToCfg } from './viewState';
import { emptyValueFor, isFilterable, OPS, ruleId } from './fields';

// The whole of a grid's chrome is ONE serialisable object, so a saved view is
// just a snapshot of it and "dirty" is a deep-equal away:
//
//   {
//     cols:    ['name','site','ssl'],          // visible columns, IN ORDER
//     sort:    { key:'name', dir:'asc' },
//     group:   null,                            // column key or null
//     filters: { match:'all', rules:[…] },
//     density: 'cozy' | 'compact',
//     sub:     ['registrar'],                   // fields printed under the name cell
//   }
//
// Column ORDER lives in `cols` — that is what makes "move left / move right"
// in the header menu a one-line splice instead of a separate ordering system.

export const GRID_DEFAULTS = {
    cols: [],
    sort: { key: null, dir: 'asc' },
    group: null,
    filters: { match: 'all', rules: [] },
    density: 'cozy',
    sub: [],
};

export function makeGridConfig(partial = {}) {
    return {
        ...GRID_DEFAULTS,
        ...partial,
        sort: { ...GRID_DEFAULTS.sort, ...(partial.sort || {}) },
        filters: { ...GRID_DEFAULTS.filters, ...(partial.filters || {}) },
        cols: [...(partial.cols || GRID_DEFAULTS.cols)],
        sub: [...(partial.sub || GRID_DEFAULTS.sub)],
    };
}

const clone = (o) => JSON.parse(JSON.stringify(o));

/**
 * Grid chrome state + saved views for one list page.
 *
 *   const grid = useGridConfig({
 *     page: 'domains',                 // server-side saved-view bucket
 *     columns: domainColumns,
 *     initial: { cols: ['name','ssl'], sort: { key:'name', dir:'asc' } },
 *     builtinViews: [{ name:'SSL expiring', state: {…} }],
 *   });
 */
export function useGridConfig({ page, columns, initial, builtinViews = [] }) {
    const base = useMemo(
        () => makeGridConfig({
            cols: columns.filter((c) => c.defaultVisible !== false).map((c) => c.key),
            ...initial,
        }),
        // Recomputing on every columns identity change would stomp user edits;
        // the initial config is a mount-time concern only.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [],
    );

    const [cfg, setCfg] = useState(base);

    // `cfg` is DataGrid's own representation and stays that way — it is what
    // makes "move column left" a one-line splice. Saved views, though, are the
    // SHARED envelope, so a Domains view is the same JSON as a Cron view and
    // one shareable-link format covers both. The two are bridged here, in the
    // one place, rather than by teaching either side about the other.
    const allKeys = useMemo(() => columns.map((c) => c.key), [columns]);

    const capture = useCallback(() => cfgToEnvelope(cfg, allKeys), [cfg, allKeys]);
    const apply = useCallback(
        (state) => setCfg(makeGridConfig(envelopeToCfg(state, allKeys))),
        [allKeys],
    );

    // Saving a view with "start from current" cleared means the page's natural
    // config, not the active view's — so this resets to `base`, not through
    // `resetToView` below (which re-applies the active view, and would also be
    // a dependency cycle: it needs `views`, which needs this).
    const resetToBase = useCallback(() => setCfg(clone(base)), [base]);

    const { views, copyLink, createView } = useGridViews({
        page,
        builtinViews,
        capture,
        apply,
        resetToView: resetToBase,
    });

    // ---- narrow setters the menus talk to ------------------------------
    const patch = useCallback((next) => setCfg((prev) => ({ ...prev, ...next })), []);

    const setSort = useCallback((key, dir) => patch({ sort: { key, dir } }), [patch]);

    const toggleGroup = useCallback((key) => {
        setCfg((prev) => ({ ...prev, group: prev.group === key ? null : key }));
    }, []);

    const setRules = useCallback((rules) => {
        setCfg((prev) => ({ ...prev, filters: { ...prev.filters, rules } }));
    }, []);

    const setMatch = useCallback((match) => {
        setCfg((prev) => ({ ...prev, filters: { ...prev.filters, match } }));
    }, []);

    // One rule per column from the header menu (the drawer can stack more).
    const putColumnRule = useCallback((key, rule) => {
        setCfg((prev) => ({
            ...prev,
            filters: {
                ...prev.filters,
                rules: [...prev.filters.rules.filter((r) => r.field !== key), ...(rule ? [rule] : [])],
            },
        }));
    }, []);

    const addRule = useCallback((columnList) => {
        const first = columnList.find(isFilterable);
        if (!first) return;
        setCfg((prev) => ({
            ...prev,
            filters: {
                ...prev.filters,
                rules: [...prev.filters.rules, {
                    id: ruleId(),
                    field: first.key,
                    op: OPS[first.type][0][0],
                    value: emptyValueFor(first.type),
                }],
            },
        }));
    }, []);

    const removeRule = useCallback((id) => {
        setCfg((prev) => ({
            ...prev,
            filters: { ...prev.filters, rules: prev.filters.rules.filter((r) => r.id !== id) },
        }));
    }, []);

    const clearRules = useCallback(() => {
        setCfg((prev) => ({ ...prev, filters: { ...prev.filters, rules: [] } }));
    }, []);

    // Move a column within the visible order. `locked` columns hold slot 0, so
    // nothing may be moved in front of them.
    const moveColumn = useCallback((key, delta, lockedCount) => {
        setCfg((prev) => {
            const cols = [...prev.cols];
            const from = cols.indexOf(key);
            const to = from + delta;
            if (from < 0 || to < lockedCount || to >= cols.length) return prev;
            cols.splice(to, 0, ...cols.splice(from, 1));
            return { ...prev, cols };
        });
    }, []);

    const hideColumn = useCallback((key) => {
        setCfg((prev) => ({
            ...prev,
            cols: prev.cols.filter((c) => c !== key),
            group: prev.group === key ? null : prev.group,
            filters: { ...prev.filters, rules: prev.filters.rules.filter((r) => r.field !== key) },
        }));
    }, []);

    const toggleColumn = useCallback((key, allKeys) => {
        setCfg((prev) => {
            if (prev.cols.includes(key)) {
                return {
                    ...prev,
                    cols: prev.cols.filter((c) => c !== key),
                    group: prev.group === key ? null : prev.group,
                    filters: { ...prev.filters, rules: prev.filters.rules.filter((r) => r.field !== key) },
                };
            }
            // Re-inserting restores the column's natural position rather than
            // dumping it on the end, so toggling twice is a no-op.
            const wanted = allKeys.indexOf(key);
            const at = prev.cols.findIndex((c) => allKeys.indexOf(c) > wanted);
            const cols = [...prev.cols];
            cols.splice(at === -1 ? cols.length : at, 0, key);
            return { ...prev, cols };
        });
    }, []);

    const setColumnOrder = useCallback((cols) => patch({ cols }), [patch]);
    const setDensity = useCallback((density) => patch({ density }), [patch]);
    const setSub = useCallback((sub) => patch({ sub }), [patch]);

    const resetToView = useCallback(() => {
        if (views.activeView) views.applyView(views.activeView);
        else setCfg(clone(base));
    }, [views, base]);

    return {
        cfg,
        setCfg,
        views,
        copyLink,
        createView,
        base,
        setSort,
        toggleGroup,
        setRules,
        setMatch,
        putColumnRule,
        addRule,
        removeRule,
        clearRules,
        moveColumn,
        hideColumn,
        toggleColumn,
        setColumnOrder,
        setDensity,
        setSub,
        resetToView,
    };
}

export default useGridConfig;
