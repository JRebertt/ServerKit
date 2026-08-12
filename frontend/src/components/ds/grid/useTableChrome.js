import { useCallback, useMemo, useState } from 'react';
import useTableViews from '@/hooks/useTableViews';
import useViewLink from './useViewLink';
import { OPS, emptyValueFor, isFilterable, ruleId, withInferredTypes } from './fields';

const NO_FILTERS = { match: 'all', rules: [] };

/**
 * The grid chrome (view picker · chip bar · filter drawer · tools menu) for a
 * page that renders <DataTable> with the legacy state model — sorts[] +
 * hiddenKeys + groupBy — rather than DataGrid's single cfg object.
 *
 * Written once here so every list page gets the SAME chrome instead of each
 * one growing its own toolbar. Give it the page's existing state and setters;
 * it returns `cfg` + `api` (what the chrome components expect), the extra
 * DataTable props, and the wired-up `views`.
 *
 *   const chrome = useTableChrome({
 *       columns, rows: filtered, viewPageKey: 'cron', builtinViews: BUILTIN_VIEWS,
 *       sorts, setSorts, hiddenKeys, setHiddenKeys, groupBy, setGroupBy,
 *       extraState: { filter, search },              // page-owned view state
 *       applyExtra: (s) => { setFilter(s.filter); setSearch(s.search); },
 *   });
 *
 *   <GridViewPicker views={chrome.views} … />
 *   <GridChips {...chrome.chipProps} />
 *   <DataTable {…chrome.tableProps} columns={chrome.columns} … />
 *   <GridFilterDrawer {...chrome.drawerProps} />
 */
export function useTableChrome({
    columns,
    rows = [],
    viewPageKey,
    builtinViews = [],
    noun = 'rows',
    sorts = [],
    setSorts,
    hiddenKeys = [],
    setHiddenKeys,
    groupBy = null,
    setGroupBy,
    extraState,
    applyExtra,
}) {
    const [filters, setFilters] = useState(NO_FILTERS);
    const [columnOrder, setColumnOrder] = useState(null);
    const [drawerOpen, setDrawerOpen] = useState(false);

    // Infer types HERE, once, and hand the same typed list to the chip bar, the
    // drawer and <DataTable>. DataTable can infer them itself, but then the
    // chrome would be reasoning about untyped columns while the table reasoned
    // about typed ones — and the drawer's rule editor would look up
    // OPS[undefined] for any rule the header menu had just created.
    const typedColumns = useMemo(() => withInferredTypes(columns, rows), [columns, rows]);

    const orderedColumns = useMemo(() => {
        if (!columnOrder?.length) return typedColumns;
        const byKey = new Map(typedColumns.map((c) => [c.key, c]));
        return [
            ...columnOrder.map((k) => byKey.get(k)).filter(Boolean),
            ...typedColumns.filter((c) => !columnOrder.includes(c.key)),
        ];
    }, [typedColumns, columnOrder]);

    const cfg = useMemo(() => ({
        cols: orderedColumns.filter((c) => !hiddenKeys.includes(c.key)).map((c) => c.key),
        sort: sorts[0] ? { key: sorts[0].key, dir: sorts[0].direction } : { key: null, dir: 'asc' },
        group: groupBy,
        filters,
        density: 'cozy',
        sub: [],
    }), [orderedColumns, hiddenKeys, sorts, groupBy, filters]);

    const removeRule = useCallback(
        (id) => setFilters((p) => ({ ...p, rules: p.rules.filter((r) => r.id !== id) })),
        [],
    );
    const clearRules = useCallback(() => setFilters((p) => ({ ...p, rules: [] })), []);
    const setMatch = useCallback((match) => setFilters((p) => ({ ...p, match })), []);

    const api = useMemo(() => ({
        setRules: (rules) => setFilters((p) => ({ ...p, rules })),
        setMatch,
        addRule: (cols) => {
            const first = cols.find(isFilterable);
            if (!first) return;
            setFilters((p) => ({
                ...p,
                rules: [...p.rules, {
                    id: ruleId(),
                    field: first.key,
                    op: OPS[first.type][0][0],
                    value: emptyValueFor(first.type),
                }],
            }));
        },
        removeRule,
        setColumnOrder,
        toggleColumn: (key) => setHiddenKeys?.(
            hiddenKeys.includes(key) ? hiddenKeys.filter((k) => k !== key) : [...hiddenKeys, key],
        ),
        setSub: () => {},
        setDensity: () => {},
        resetToView: () => { clearRules(); setHiddenKeys?.([]); setColumnOrder(null); },
    }), [setMatch, removeRule, clearRules, hiddenKeys, setHiddenKeys]);

    // The saved-view key is `columnFilters`, NOT `filters`: several pages
    // (Jobs, Monitors) already capture a `filters` key of their own, and it is
    // the FilterDrawer's {status, kind} pair — a different thing entirely.
    // Sharing the name would have made their presets silently cross-wire.
    const capture = useCallback(() => ({
        ...(extraState || {}),
        sorts,
        hiddenKeys,
        groupBy,
        columnFilters: filters,
        columnOrder,
    }), [extraState, sorts, hiddenKeys, groupBy, filters, columnOrder]);

    const apply = useCallback((state) => {
        applyExtra?.(state);
        if (Array.isArray(state.sorts)) setSorts?.(state.sorts);
        if (Array.isArray(state.hiddenKeys)) setHiddenKeys?.(state.hiddenKeys);
        if (state.groupBy !== undefined) setGroupBy?.(state.groupBy);
        // A preset with no rules must CLEAR the live ones, or switching views
        // leaves the previous view's filters silently applied.
        setFilters(state.columnFilters ?? NO_FILTERS);
        setColumnOrder(state.columnOrder ?? null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [applyExtra, setSorts, setHiddenKeys, setGroupBy]);

    const views = useTableViews({ page: viewPageKey, builtinViews, capture, apply });

    // ?view=<slug> / ?v=<encoded> <-> the active view, both directions. Applying
    // a link goes through the SAME `apply` the picker uses, so a shared link and
    // a click can never drift apart.
    const { copyLink } = useViewLink({ views, apply, capture, enabled: !!viewPageKey });

    const createView = useCallback((name, fromCurrent) => {
        if (!fromCurrent) api.resetToView();
        return views.saveView(name);
    }, [api, views]);

    return {
        cfg,
        api,
        views,
        columns: orderedColumns,
        noun,
        filterCount: filters.rules.length,
        drawerOpen,
        setDrawerOpen,
        createView,
        copyLink,

        // spread straight onto the matching components
        tableProps: {
            filters,
            onFiltersChange: setFilters,
            columnOrder,
            onColumnOrderChange: setColumnOrder,
            hiddenKeys,
            onHiddenKeysChange: setHiddenKeys,
        },
        chipProps: {
            cfg,
            columns: orderedColumns,
            onRemove: removeRule,
            onClear: clearRules,
            onMatchChange: setMatch,
        },
        drawerProps: {
            open: drawerOpen,
            onOpenChange: setDrawerOpen,
            columns: orderedColumns,
            rows,
            cfg,
            grid: api,
            noun,
            showRowDetail: false,
            showDensity: false,
        },
        toolsProps: {
            cfg,
            columns: orderedColumns,
            rows,
            viewName: views.activeView?.name || noun,
            noun,
            onReset: api.resetToView,
            onCopyLink: copyLink,
            showDensity: false,
        },
    };
}

export default useTableChrome;
