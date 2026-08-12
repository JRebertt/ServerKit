import { useCallback, useMemo, useState } from 'react';
import { Search, Rows3, LayoutGrid, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { SegControl, DataTableFooter, ListToolbar } from '@/components/ds';
import {
    GridViewPicker, GridChips, GridFilterButton, GridToolsMenu, GridFilterDrawer,
    withInferredTypes,
} from '@/components/ds/grid';
import EmptyState from '../EmptyState';
import DataTable from '@/components/ds/DataTable';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { useTableViews } from '@/hooks/useTableViews';

const NO_FILTERS = { match: 'all', rules: [] };

// Shared chrome for resource list pages (Services, Servers, …): the status
// filter + search toolbar, sort & column menus, the DataTable with a standard
// footer, and the loading / empty / filtered-empty states. Pages become thin:
// they own data + columns + handlers and pass them in. Markup mirrors the
// established `.wp-list` design so existing SCSS applies unchanged.
//
//   <ResourceListPage
//     className="services-page"
//     loading={loading}
//     totalCount={apps.length}          // distinguishes "no items at all" from "filtered empty"
//     items={filteredApps}               // already-filtered rows for the table
//     columns={columns} keyField="id"    // columns opt into sorting with `sortable: true`
//     onRowClick={app => navigate(...)} rowClassName={rowClassName}
//     storageKey="serverkit-list-services"   // optional: persist sort/columns/page-size
//     filters={[{ value, label, count }]} activeFilter={statusFilter} onFilterChange={setStatusFilter}
//     searchTerm={searchTerm} onSearchChange={setSearchTerm} searchPlaceholder="Search services…"
//     selectedCount={selectedIds.size} onClearSelection={clear} bulkActions={<>…</>}
//     emptyIcon={Layers} emptyTitle="…" emptyDescription="…" emptyAction={<Button…/>}
//     filteredEmptyTitle="…" filteredEmptyDescription="…"
//   >
//     {/* page-specific extras, e.g. a dialog */}
//   </ResourceListPage>
export default function ResourceListPage({
    className,
    loading = false,
    loadingTitle = 'Loading…',
    totalCount,
    items = [],
    columns,
    keyField = 'id',
    onRowClick,
    rowClassName,
    // Global sorting toggle — individual columns still need `sortable: true`.
    sortable = true,
    // Optional localStorage namespace for sort / column / page-size choices.
    storageKey,
    // Saved views: pass the page's view key (e.g. 'services') plus any built-in
    // views to grow a Views menu in the toolbar. A view state is
    // { filter, search, sorts, hiddenKeys, pageSize } — all keys optional.
    viewPageKey,
    builtinViews = [],
    // Plural label used by the view picker, footer and export filename.
    noun = 'rows',
    // optional content rendered inside the wrapper, above the toolbar/empty
    // state (e.g. a one-time credentials banner)
    header,
    // toolbar
    filters,
    activeFilter,
    onFilterChange,
    searchTerm,
    onSearchChange,
    searchPlaceholder = 'Search…',
    // Placement rule: on tab-group pages the search input belongs in the shared
    // topbar (the page publishes a SearchField there itself); set this flag so
    // the in-page search slot stays empty. Extensions outside a tab group leave
    // it off and keep the in-page input.
    searchInTopbar = false,
    toolbarExtra,
    // bulk actions
    selectedCount = 0,
    onClearSelection,
    bulkActions,
    // empty (no items at all)
    emptyIcon,
    emptyTitle = 'No results',
    emptyDescription = '',
    emptyAction = null,
    // filtered empty (items exist but none match the filter/search)
    filteredEmptyIcon,
    filteredEmptyTitle = 'No results found',
    filteredEmptyDescription = 'Try adjusting your search or filter.',
    // Opt-in card view: pass a renderer and the toolbar grows a list/cards
    // switch. Pages that omit it are table-only exactly as before.
    renderCard,
    viewStorageKey,
    // Row selection: pass selectedIds (Set) + handlers to get a native
    // checkbox column and the floating bulk bar (replaces the hand-rolled
    // __select column pattern).
    selectable = false,
    selectedIds,
    onToggleSelect,
    onSelectAll,
    // j/k/Enter/x row cursor (defaults on for list pages; keys are ignored
    // while typing or while a dialog is open).
    keyboardNav = true,
    children,
}) {
    const resolvedTotal = totalCount ?? items.length;
    const [view, setView] = useState(() => {
        if (!renderCard) return 'list';
        try {
            return window.localStorage.getItem(viewStorageKey) === 'cards' ? 'cards' : 'list';
        } catch {
            return 'list';
        }
    });

    const { sorts, setSorts } = useTableSort({
        storageKey: storageKey ? `${storageKey}-sort` : undefined,
    });
    const { hiddenKeys, setHiddenKeys, toggleColumn, showAllColumns } = useColumnVisibility({
        storageKey: storageKey ? `${storageKey}-cols` : undefined,
    });
    const [groupBy, setGroupBy] = useState(() => {
        if (!storageKey) return null;
        try {
            return window.localStorage.getItem(`${storageKey}-group`) || null;
        } catch {
            return null;
        }
    });

    const changeGroupBy = (next) => {
        setGroupBy(next);
        if (!storageKey) return;
        try {
            if (next) window.localStorage.setItem(`${storageKey}-group`, next);
            else window.localStorage.removeItem(`${storageKey}-group`);
        } catch {
            /* private mode / quota — the choice just doesn't persist */
        }
    };
    const [pageSize, setPageSize] = useState(() => {
        if (!storageKey) return 'all';
        try {
            const raw = window.localStorage.getItem(`${storageKey}-pagesize`);
            return raw ? (raw === 'all' ? 'all' : Number(raw)) : 'all';
        } catch {
            return 'all';
        }
    });

    const changePageSize = (next) => {
        setPageSize(next);
        if (!storageKey) return;
        try {
            window.localStorage.setItem(`${storageKey}-pagesize`, String(next));
        } catch {
            /* private mode / quota — the choice just doesn't persist */
        }
    };

    // Per-column filter rules + column order, owned here rather than by
    // DataTable, so they can be captured into a saved view and mirrored in the
    // chip bar and the drawer. DataTable stays the renderer.
    const [columnFilters, setColumnFilters] = useState(NO_FILTERS);
    const [columnOrder, setColumnOrder] = useState(null);
    const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);

    const putColumnRule = useCallback((key, rule) => {
        setColumnFilters((prev) => ({
            ...prev,
            rules: [...prev.rules.filter((r) => r.field !== key), ...(rule ? [rule] : [])],
        }));
    }, []);
    const removeRule = useCallback(
        (id) => setColumnFilters((prev) => ({ ...prev, rules: prev.rules.filter((r) => r.id !== id) })),
        [],
    );
    const clearRules = useCallback(() => setColumnFilters((prev) => ({ ...prev, rules: [] })), []);
    const setMatch = useCallback((match) => setColumnFilters((prev) => ({ ...prev, match })), []);

    const changeView = (next) => {
        setView(next);
        if (!viewStorageKey) return;
        try {
            window.localStorage.setItem(viewStorageKey, next);
        } catch {
            /* private mode / quota — the choice just doesn't persist */
        }
    };

    const pagedItems = useMemo(
        () => (pageSize === 'all' ? items : items.slice(0, pageSize)),
        [items, pageSize],
    );

    // ---- adapter: present this page's state as a DataGrid cfg/api pair ------
    // The grid chrome (view picker, chip bar, filter drawer, tools menu) is
    // written against ONE serialisable cfg. This page predates that and keeps
    // sorts[]/hiddenKeys/groupBy instead. Rather than fork the chrome — which
    // is exactly the per-page duplication this layout exists to stop — adapt
    // the state here, once, and every list page built on this wrapper gets the
    // same chrome for free.
    // Types are inferred HERE, once, so the chip bar, the drawer and the table
    // all reason about the same column list. Inferring separately inside
    // DataTable would leave the drawer looking up OPS[undefined] for a rule the
    // header menu had just created.
    const typedColumns = useMemo(() => withInferredTypes(columns, items), [columns, items]);

    const orderedColumns = useMemo(() => {
        if (!columnOrder?.length) return typedColumns;
        const byKey = new Map(typedColumns.map((c) => [c.key, c]));
        const moved = columnOrder.map((k) => byKey.get(k)).filter(Boolean);
        return [...moved, ...typedColumns.filter((c) => !columnOrder.includes(c.key))];
    }, [typedColumns, columnOrder]);

    const gridCfg = useMemo(() => ({
        cols: orderedColumns.filter((c) => !hiddenKeys.includes(c.key)).map((c) => c.key),
        sort: sorts[0] ? { key: sorts[0].key, dir: sorts[0].direction } : { key: null, dir: 'asc' },
        group: groupBy,
        filters: columnFilters,
        // DataTable auto-sizes its columns and has no sub-detail line, so the
        // drawer's density / row-detail panes are switched off below rather
        // than shown as controls that do nothing.
        density: 'cozy',
        sub: [],
    }), [orderedColumns, hiddenKeys, sorts, groupBy, columnFilters]);

    const gridApi = useMemo(() => ({
        setRules: (rules) => setColumnFilters((prev) => ({ ...prev, rules })),
        setMatch,
        addRule: (cols) => {
            const first = cols.find((c) => c.type && c.filterable !== false);
            if (!first) return;
            setColumnFilters((prev) => ({
                ...prev,
                rules: [...prev.rules, {
                    id: `r${prev.rules.length}${Math.random().toString(36).slice(2, 6)}`,
                    field: first.key,
                    op: first.type === 'enum' ? 'any' : first.type === 'bool' ? 'is' : first.type === 'num' ? 'lt' : 'contains',
                    value: first.type === 'enum' ? [] : first.type === 'bool' ? true : '',
                }],
            }));
        },
        removeRule,
        setColumnOrder,
        toggleColumn: (key) => toggleColumn(key),
        setSub: () => {},
        setDensity: () => {},
        resetToView: () => { clearRules(); showAllColumns(); setColumnOrder(null); },
    }), [setMatch, removeRule, toggleColumn, clearRules, showAllColumns]);

    // Saved views: capture/apply the full table chrome state (status filter,
    // search, sort levels, hidden columns, page size). The filter and search
    // values themselves are owned by the page — apply() routes through its
    // setters so a view can drive them.
    const captureView = useCallback(() => ({
        filter: activeFilter,
        search: searchTerm,
        sorts,
        hiddenKeys,
        pageSize,
        groupBy,
        // `columnFilters`, not `filters`: `filters` is already this component's
        // prop name for the SegControl options, and other pages capture a
        // `filters` key of their own with a different shape.
        columnFilters,
        columnOrder,
    }), [activeFilter, searchTerm, sorts, hiddenKeys, pageSize, groupBy, columnFilters, columnOrder]);

    const applyView = useCallback((state) => {
        if (state.filter !== undefined) onFilterChange?.(state.filter);
        if (state.search !== undefined) onSearchChange?.(state.search);
        if (Array.isArray(state.sorts)) setSorts(state.sorts);
        if (Array.isArray(state.hiddenKeys)) setHiddenKeys(state.hiddenKeys);
        if (state.pageSize !== undefined) changePageSize(state.pageSize);
        if (state.groupBy !== undefined) changeGroupBy(state.groupBy);
        // A preset that sets no rules must CLEAR the live ones, or switching
        // views leaves the previous view's filters silently applied.
        setColumnFilters(state.columnFilters ?? NO_FILTERS);
        setColumnOrder(state.columnOrder ?? null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [onFilterChange, onSearchChange, setSorts, setHiddenKeys]);

    const tableViews = useTableViews({
        page: viewPageKey,
        builtinViews,
        capture: captureView,
        apply: applyView,
    });

    if (loading) {
        // Same wrapper as the loaded state below. A skeleton that renders
        // outside the page's padded container occupies a different box than the
        // content it predicts — it spans edge to edge, then everything jumps
        // inward on arrival, which is precisely the flash a skeleton exists to
        // prevent.
        //
        // The variant tracks the real shape: a resource list is a table, or a
        // card grid when the page opted into one.
        return (
            <div className={cn('sk-tabgroup__inner', className)}>
                <EmptyState
                    loading
                    loadingVariant={renderCard && view === 'cards' ? 'cards' : 'table'}
                    title={loadingTitle}
                />
            </div>
        );
    }

    return (
        <div className={cn('sk-tabgroup__inner', className)}>
            {header}
            {resolvedTotal === 0 ? (
                <EmptyState
                    size="lg"
                    icon={emptyIcon}
                    title={emptyTitle}
                    description={emptyDescription}
                    action={emptyAction}
                />
            ) : (
                <div className="wp-list">
                    {/* The saved view names what you are looking at, so it is the
                        page's heading rather than another toolbar button. Sort,
                        Group and Columns are gone from the toolbar entirely —
                        they live in each column's own "⋮" now, next to the
                        column they act on. */}
                    {viewPageKey && view === 'list' && (
                        <GridViewPicker
                            views={tableViews}
                            label={noun}
                            total={`${items.length} of ${resolvedTotal} ${noun}`}
                            onCreate={(name, fromCurrent) => {
                                if (!fromCurrent) gridApi.resetToView();
                                tableViews.saveView(name);
                            }}
                        />
                    )}
                    <ListToolbar
                        filters={filters && (
                            <SegControl
                                value={activeFilter}
                                onChange={onFilterChange}
                                options={filters}
                            />
                        )}
                        tools={(
                            <>
                                {view === 'list' && (
                                    <>
                                        <GridFilterButton
                                            count={columnFilters.rules.length}
                                            onClick={() => setFilterDrawerOpen(true)}
                                        />
                                        <GridToolsMenu
                                            cfg={gridCfg}
                                            columns={orderedColumns}
                                            rows={items}
                                            selectedRows={selectable && selectedIds
                                                ? items.filter((i) => selectedIds.has(i[keyField]))
                                                : []}
                                            viewName={tableViews.activeView?.name || noun}
                                            noun={noun}
                                            onReset={gridApi.resetToView}
                                            showDensity={false}
                                        />
                                    </>
                                )}
                                {renderCard && (
                                    <div className="wp-list__viewswitch" role="group" aria-label="Layout">
                                        {[['list', Rows3, 'List'], ['cards', LayoutGrid, 'Cards']].map(([key, Icon, label]) => (
                                            <button
                                                type="button"
                                                key={key}
                                                className={view === key ? 'is-active' : ''}
                                                onClick={() => changeView(key)}
                                                title={label}
                                                aria-label={label}
                                                aria-pressed={view === key}
                                            >
                                                <Icon size={15} />
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </>
                        )}
                    >
                        {onSearchChange && !searchInTopbar && (
                            <div className="wp-list__search">
                                <Search size={15} aria-hidden="true" />
                                <input
                                    type="text"
                                    value={searchTerm}
                                    onChange={(e) => onSearchChange(e.target.value)}
                                    placeholder={searchPlaceholder}
                                    aria-label={searchPlaceholder}
                                />
                            </div>
                        )}
                        {toolbarExtra}
                    </ListToolbar>

                    {view === 'list' && (
                        <GridChips
                            cfg={gridCfg}
                            columns={orderedColumns}
                            onRemove={removeRule}
                            onClear={clearRules}
                            onMatchChange={setMatch}
                        />
                    )}

                    {items.length === 0 ? (
                        <EmptyState
                            icon={filteredEmptyIcon || emptyIcon}
                            title={filteredEmptyTitle}
                            description={filteredEmptyDescription}
                        />
                    ) : view === 'cards' && renderCard ? (
                        <div className="wp-list__cards">
                            {items.map((item) => (
                                <div
                                    key={item[keyField]}
                                    className={cn('wp-list__cardtile', rowClassName?.(item))}
                                    onClick={() => onRowClick?.(item)}
                                >
                                    {renderCard(item)}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="wp-list__card">
                            <DataTable
                                columns={orderedColumns}
                                data={pagedItems}
                                keyField={keyField}
                                sortable={sortable}
                                sorts={sorts}
                                onSortsChange={setSorts}
                                hiddenKeys={hiddenKeys}
                                onHiddenKeysChange={setHiddenKeys}
                                groupBy={groupBy}
                                onGroupByChange={changeGroupBy}
                                filters={columnFilters}
                                onFiltersChange={setColumnFilters}
                                columnOrder={columnOrder}
                                onColumnOrderChange={setColumnOrder}
                                selectable={selectable}
                                selectedKeys={selectable && selectedIds ? [...selectedIds] : undefined}
                                onToggleRow={selectable ? onToggleSelect : undefined}
                                onToggleAll={selectable ? onSelectAll : undefined}
                                keyboardNav={keyboardNav}
                                onRowClick={onRowClick}
                                rowClassName={rowClassName}
                                footer={(
                                    <DataTableFooter
                                        shown={pagedItems.length}
                                        total={items.length}
                                        noun={noun.replace(/s$/, '')}
                                        pageSize={pageSize}
                                        onPageSizeChange={changePageSize}
                                    />
                                )}
                            />
                        </div>
                    )}
                </div>
            )}

            {/* Floating bulk-actions pill: appears only while a selection is
                active, instead of a permanent bar reserving toolbar space. */}
            {selectedCount > 0 && (
                <div className="sk-bulkbar" role="status">
                    <span className="sk-bulkbar__count">{selectedCount} selected</span>
                    <div className="sk-bulkbar__actions">{bulkActions}</div>
                    {onClearSelection && (
                        <button
                            type="button"
                            className="sk-bulkbar__clear"
                            onClick={onClearSelection}
                            aria-label="Clear selection"
                        >
                            <X size={14} />
                        </button>
                    )}
                </div>
            )}
            <GridFilterDrawer
                open={filterDrawerOpen}
                onOpenChange={setFilterDrawerOpen}
                columns={orderedColumns}
                rows={items}
                cfg={gridCfg}
                grid={gridApi}
                noun={noun}
                showRowDetail={false}
                showDensity={false}
            />

            {children}
        </div>
    );
}
