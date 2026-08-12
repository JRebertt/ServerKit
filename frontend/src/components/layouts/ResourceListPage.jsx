import { useCallback, useMemo, useState } from 'react';
import { Search, Rows3, LayoutGrid, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { SegControl, DataTableFooter, ListToolbar } from '@/components/ds';
import {
    GridViewPicker, GridChips, GridFilterButton, GridToolsMenu, GridFilterDrawer,
    useTableChrome,
} from '@/components/ds/grid';
import EmptyState from '../EmptyState';
import DataTable from '@/components/ds/DataTable';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';

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
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({
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

    // The chrome — view picker, chip bar, filter drawer, tools menu, shareable
    // links — comes from the shared hook rather than being adapted again here.
    // This wrapper used to carry its own copy of that adapter, which is how it
    // ended up the one chrome host with no `useViewLink`: every list page built
    // on it silently had no shareable links at all.
    //
    // `page` is the envelope's per-page bag (see grid/viewState.js). The status
    // filter, the search box and the page size are this wrapper's own state —
    // everything else is captured identically to every other list page.
    const pageState = useMemo(
        () => ({ filter: activeFilter, search: searchTerm, pageSize }),
        [activeFilter, searchTerm, pageSize],
    );

    const applyPage = useCallback((saved) => {
        if (saved.filter !== undefined) onFilterChange?.(saved.filter);
        if (saved.search !== undefined) onSearchChange?.(saved.search);
        if (saved.pageSize !== undefined) changePageSize(saved.pageSize);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [onFilterChange, onSearchChange]);

    const chrome = useTableChrome({
        columns,
        rows: items,
        viewPageKey,
        builtinViews,
        noun,
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        groupBy,
        setGroupBy: changeGroupBy,
        pageState,
        applyPage,
    });

    const orderedColumns = chrome.columns;
    const tableViews = chrome.views;

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
                            onCreate={chrome.createView}
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
                                            count={chrome.filterCount}
                                            onClick={() => chrome.setDrawerOpen(true)}
                                        />
                                        <GridToolsMenu
                                            {...chrome.toolsProps}
                                            selectedRows={selectable && selectedIds
                                                ? items.filter((i) => selectedIds.has(i[keyField]))
                                                : []}
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

                    {view === 'list' && <GridChips {...chrome.chipProps} />}

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
                                {...chrome.tableProps}
                                columns={orderedColumns}
                                data={pagedItems}
                                keyField={keyField}
                                sortable={sortable}
                                sorts={sorts}
                                onSortsChange={setSorts}
                                groupBy={groupBy}
                                onGroupByChange={changeGroupBy}
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
            <GridFilterDrawer {...chrome.drawerProps} />

            {children}
        </div>
    );
}
