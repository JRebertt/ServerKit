import { useState, useMemo } from 'react';
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
import EmptyState from '../EmptyState';

/**
 * Declarative data table built on top of the shadcn/ui Table primitives.
 *
 * Supports sorting, empty states, loading states, clickable rows, and custom
 * cell rendering. Styling uses the existing `.ui-table` / `.sk-dtable` specs.
 *
 * Example:
 *   <DataTable
 *     columns={[
 *       { key: 'name', header: 'Server', sortable: true, render: s => <ServerCell server={s} /> },
 *       { key: 'status', header: 'Status', render: s => <Pill kind={s.status}>{s.status}</Pill> },
 *       { key: 'actions', header: '', className: 'text-right', render: s => <Actions server={s} /> },
 *     ]}
 *     data={servers}
 *     keyField="id"
 *     emptyTitle="No servers"
 *     emptyMessage="Add your first server to start monitoring."
 *   />
 */
export function DataTable({
    columns,
    data,
    keyField = 'id',
    sortable = true,
    defaultSort = null,
    emptyState,
    emptyTitle = 'No results',
    emptyMessage = 'Nothing to show yet.',
    loading = false,
    onRowClick,
    renderRow,
    className,
    rowClassName,
    tableClassName,
}) {
    const [sort, setSort] = useState(defaultSort);

    const sortedData = useMemo(() => {
        if (!sort || !sortable) return data;
        const column = columns.find((c) => c.key === sort.key);
        if (!column) return data;

        const direction = sort.direction === 'desc' ? -1 : 1;
        const getValue = column.sortValue || ((row) => row[column.key]);

        return [...data].sort((a, b) => {
            const av = getValue(a);
            const bv = getValue(b);
            if (av == null && bv == null) return 0;
            if (av == null) return direction;
            if (bv == null) return -direction;
            if (typeof av === 'number' && typeof bv === 'number') {
                return (av - bv) * direction;
            }
            return String(av).localeCompare(String(bv)) * direction;
        });
    }, [data, sort, sortable, columns]);

    const handleHeaderClick = (column) => {
        if (!sortable || !column.sortable) return;
        setSort((prev) => {
            if (prev?.key === column.key) {
                if (prev.direction === 'asc') return { key: column.key, direction: 'desc' };
                return null;
            }
            return { key: column.key, direction: 'asc' };
        });
    };

    if (loading) {
        return <EmptyState loading loadingVariant="table" title="Loading" />;
    }

    if (!loading && data.length === 0) {
        if (emptyState) return emptyState;
        return <EmptyState title={emptyTitle} message={emptyMessage} />;
    }

    return (
        <div className={cn('sk-dtable-wrap', className)}>
            <Table className={cn('sk-dtable', tableClassName)}>
                <TableHeader>
                    <TableRow>
                        {columns.map((column) => {
                            const isSorted = sort?.key === column.key;
                            const canSort = sortable && column.sortable;
                            return (
                                <TableHead
                                    key={column.key}
                                    className={cn(
                                        column.className,
                                        canSort && 'is-sortable'
                                    )}
                                    style={column.width ? { width: column.width } : undefined}
                                    onClick={() => handleHeaderClick(column)}
                                    aria-sort={
                                        isSorted
                                            ? sort.direction === 'asc'
                                                ? 'ascending'
                                                : 'descending'
                                            : 'none'
                                    }
                                >
                                    <span className="sk-dtable__head-inner">
                                        {column.header}
                                        {canSort && (
                                            <span className="sk-dtable__sort">
                                                {isSorted && sort.direction === 'asc' ? (
                                                    <ChevronUp size={14} />
                                                ) : isSorted && sort.direction === 'desc' ? (
                                                    <ChevronDown size={14} />
                                                ) : (
                                                    <ChevronUp size={14} className="sk-dtable__sort-placeholder" />
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
                                {columns.map((column) => (
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
        </div>
    );
}

export default DataTable;
