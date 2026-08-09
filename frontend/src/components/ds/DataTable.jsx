import { useMemo } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { applyTableSorts, nextSorts, useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import EmptyState from '../EmptyState';

/**
 * Declarative data table built on top of the shadcn/ui Table primitives.
 *
 * Multi-column sorting (datatables.net style): a plain header click makes that
 * column the only sort (asc -> desc -> none); shift+click stacks additional
 * sort levels. Sort state is uncontrolled by default; pass `sorts` +
 * `onSortsChange` to control it (e.g. to pair with <SortMenu> in a toolbar).
 * Column visibility works the same way via `hiddenKeys` + `onHiddenKeysChange`
 * and ds/ColumnsMenu. `storageKey` persists both to localStorage.
 *
 * Example:
 *   <DataTable
 *     columns={[
 *       { key: 'name', header: 'Server', sortable: true, hideable: false,
 *         render: s => <ServerCell server={s} /> },
 *       { key: 'status', header: 'Status', sortable: true,
 *         render: s => <Pill kind={s.status}>{s.status}</Pill> },
 *       { key: 'actions', header: '', className: 'text-right', sortable: false,
 *         hideable: false, render: s => <Actions server={s} /> },
 *     ]}
 *     data={servers}
 *     keyField="id"
 *     storageKey="serverkit-table-servers"
 *     footer={<DataTableFooter shown={rows.length} total={rows.length} />}
 *     emptyTitle="No servers"
 *     emptyMessage="Add your first server to start monitoring."
 *   />
 */
export function DataTable({
    columns,
    data,
    keyField = 'id',
    sortable = true,
    // Legacy single-sort default; prefer defaultSorts.
    defaultSort = null,
    defaultSorts,
    // Controlled sort state (optional).
    sorts: controlledSorts,
    onSortsChange,
    // Controlled column visibility (optional).
    hiddenKeys: controlledHiddenKeys,
    storageKey,
    emptyState,
    emptyTitle = 'No results',
    emptyMessage = 'Nothing to show yet.',
    loading = false,
    onRowClick,
    renderRow,
    footer,
    className,
    rowClassName,
    tableClassName,
}) {
    const internal = useTableSort({
        defaultSorts: defaultSorts ?? (defaultSort ? [defaultSort] : []),
        storageKey: storageKey ? `${storageKey}-sort` : undefined,
    });
    const sorts = controlledSorts ?? internal.sorts;
    const toggleSort = useMemo(() => (
        onSortsChange
            ? (key, additive) => onSortsChange(nextSorts(sorts, key, additive))
            : internal.toggleSort
    ), [onSortsChange, sorts, internal.toggleSort]);

    const internalCols = useColumnVisibility({
        storageKey: storageKey ? `${storageKey}-cols` : undefined,
    });
    const hiddenKeys = controlledHiddenKeys ?? internalCols.hiddenKeys;

    const visibleColumns = useMemo(
        () => columns.filter((c) => !hiddenKeys.includes(c.key)),
        [columns, hiddenKeys],
    );

    const sortedData = useMemo(
        () => (sortable ? applyTableSorts(data, sorts, columns) : data),
        [data, sorts, sortable, columns],
    );

    const handleHeaderClick = (event, column) => {
        if (!sortable || !column.sortable) return;
        toggleSort(column.key, event.shiftKey);
    };

    if (loading) {
        return <EmptyState loading loadingVariant="table" title="Loading" />;
    }

    if (!loading && data.length === 0) {
        if (emptyState) return emptyState;
        return <EmptyState title={emptyTitle} description={emptyMessage} />;
    }

    const multiSort = sorts.length > 1;

    return (
        <div className={cn('sk-dtable-wrap', className)}>
            <Table className={cn('sk-dtable', tableClassName)}>
                <TableHeader>
                    <TableRow>
                        {visibleColumns.map((column) => {
                            const sortIndex = sorts.findIndex((s) => s.key === column.key);
                            const isSorted = sortIndex !== -1;
                            const canSort = sortable && column.sortable;
                            return (
                                <TableHead
                                    key={column.key}
                                    className={cn(
                                        column.className,
                                        canSort && 'is-sortable',
                                        isSorted && 'is-sorted',
                                    )}
                                    style={column.width ? { width: column.width } : undefined}
                                    onClick={(event) => handleHeaderClick(event, column)}
                                    title={canSort ? 'Click to sort · Shift+click to add a sort level' : undefined}
                                    aria-sort={
                                        isSorted
                                            ? sorts[sortIndex].direction === 'asc'
                                                ? 'ascending'
                                                : 'descending'
                                            : 'none'
                                    }
                                >
                                    <span className="sk-dtable__head-inner">
                                        {column.header}
                                        {canSort && (
                                            <span className="sk-dtable__sort">
                                                {isSorted && sorts[sortIndex].direction === 'asc' ? (
                                                    <ChevronUp size={14} />
                                                ) : isSorted ? (
                                                    <ChevronDown size={14} />
                                                ) : (
                                                    <ChevronUp size={14} className="sk-dtable__sort-placeholder" />
                                                )}
                                                {isSorted && multiSort && (
                                                    <span className="sk-dtable__sort-priority">{sortIndex + 1}</span>
                                                )}
                                            </span>
                                        )}
                                    </span>
                                </TableHead>
                            );
                        })}
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {sortedData.map((row) => {
                        const key = typeof keyField === 'function' ? keyField(row) : row[keyField];
                        const computedRowClass = typeof rowClassName === 'function'
                            ? rowClassName(row)
                            : rowClassName;

                        if (renderRow) {
                            return renderRow(row, { key, className: computedRowClass });
                        }

                        return (
                            <TableRow
                                key={key}
                                className={cn(
                                    computedRowClass,
                                    onRowClick && 'is-clickable'
                                )}
                                onClick={onRowClick ? () => onRowClick(row) : undefined}
                            >
                                {visibleColumns.map((column) => (
                                    <TableCell
                                        key={`${key}-${column.key}`}
                                        className={column.cellClassName}
                                    >
                                        {column.render
                                            ? column.render(row)
                                            : row[column.key]}
                                    </TableCell>
                                ))}
                            </TableRow>
                        );
                    })}
                </TableBody>
            </Table>
            {footer}
        </div>
    );
}

export default DataTable;
