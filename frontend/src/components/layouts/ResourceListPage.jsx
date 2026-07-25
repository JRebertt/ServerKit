import { useState } from 'react';
import { Search, Rows3, LayoutGrid } from 'lucide-react';
import { cn } from '@/lib/utils';
import { SegControl } from '@/components/ds';
import { Button } from '@/components/ui/button';
import EmptyState from '../EmptyState';
import DataTable from '@/components/ds/DataTable';

// Shared chrome for resource list pages (Services, Servers, …): the status
// filter + search toolbar, the bulk-actions bar, and the DataTable, plus the
// loading / empty / filtered-empty states. Pages become thin: they own data +
// columns + handlers and pass them in. Markup mirrors the established `.wp-list`
// design so existing SCSS applies unchanged.
//
//   <ResourceListPage
//     className="services-page"
//     loading={loading}
//     totalCount={apps.length}          // distinguishes "no items at all" from "filtered empty"
//     items={filteredApps}               // already-filtered rows for the table
//     columns={columns} keyField="id"
//     onRowClick={app => navigate(...)} rowClassName={rowClassName}
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
    sortable = false,
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

    const changeView = (next) => {
        setView(next);
        if (!viewStorageKey) return;
        try {
            window.localStorage.setItem(viewStorageKey, next);
        } catch {
            /* private mode / quota — the choice just doesn't persist */
        }
    };

    if (loading) {
        return <EmptyState loading title={loadingTitle} />;
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
                    <div className="wp-list__toolbar">
                        {filters && (
                            <SegControl
                                value={activeFilter}
                                onChange={onFilterChange}
                                options={filters}
                            />
                        )}
                        {onSearchChange && (
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
                    </div>

                    {selectedCount > 0 && (
                        <div className="wp-list__bulkbar">
                            <span className="wp-list__bulkcount">{selectedCount} selected</span>
                            <div className="wp-list__bulkactions">
                                {bulkActions}
                                {onClearSelection && (
                                    <Button variant="ghost" size="sm" onClick={onClearSelection}>
                                        Clear
                                    </Button>
                                )}
                            </div>
                        </div>
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
                                columns={columns}
                                data={items}
                                keyField={keyField}
                                sortable={sortable}
                                onRowClick={onRowClick}
                                rowClassName={rowClassName}
                            />
                        </div>
                    )}
                </div>
            )}
            {children}
        </div>
    );
}
