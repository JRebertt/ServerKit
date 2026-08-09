import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronUp, ChevronDown, ChevronRight } from 'lucide-react';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { Checkbox } from '@/components/ui/checkbox';
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
 * Grouping: pass `groupBy` (a column key) — rows collapse under sticky group
 * headers with counts. Columns opt in with `groupable: true` and may define
 * `groupValue(row)` / `groupLabel(value, rows)`. Pair with ds/GroupMenu.
 *
 * Selection: `selectable` + controlled `selectedKeys` / `onToggleRow` /
 * `onToggleAll` renders a real checkbox column (header box goes
 * indeterminate when partially selected).
 *
 * Keyboard nav: `keyboardNav` adds a row cursor — j/k (or arrows) move,
 * Enter triggers onRowClick, x toggles the cursor row's selection. Keys are
 * ignored while typing in a field or while a dialog holds focus.
 *
 * Example:
 *   <DataTable
 *     columns={[
 *       { key: 'name', header: 'Server', sortable: true, hideable: false,
 *         render: s => <ServerCell server={s} /> },
 *       { key: 'status', header: 'Status', sortable: true, groupable: true,
 *         render: s => <Pill kind={s.status}>{s.status}</Pill> },
 *       { key: 'actions', header: '', className: 'text-right', sortable: false,
 *         hideable: false, render: s => <Actions server={s} /> },
 *     ]}
 *     data={servers}
 *     keyField="id"
 *     storageKey="serverkit-table-servers"
 *     keyboardNav
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
    // Grouping (optional; controlled via groupBy + onGroupByChange).
    groupBy: controlledGroupBy,
    onGroupByChange,
    // Selection (optional, controlled).
    selectable = false,
    selectedKeys,
    onToggleRow,
    onToggleAll,
    // j/k/Enter/x row cursor.
    keyboardNav = false,
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

    const [internalGroupBy, setInternalGroupBy] = useState(null);
    const groupBy = controlledGroupBy !== undefined ? controlledGroupBy : internalGroupBy;

    const visibleColumns = useMemo(
        () => columns.filter((c) => !hiddenKeys.includes(c.key)),
        [columns, hiddenKeys],
    );

    const sortedData = useMemo(
        () => (sortable ? applyTableSorts(data, sorts, columns) : data),
        [data, sorts, sortable, columns],
    );

    // ---- grouping ----------------------------------------------------------
    const groupColumn = useMemo(
        () => columns.find((c) => c.key === groupBy && c.groupable),
        [columns, groupBy],
    );
    const groups = useMemo(() => {
        if (!groupColumn) return null;
        const getValue = groupColumn.groupValue || ((row) => row[groupColumn.key]);
        const byKey = new Map();
        for (const row of sortedData) {
            const value = getValue(row);
            const key = value == null || value === '' ? '__none__' : String(value);
            if (!byKey.has(key)) byKey.set(key, { key, value, rows: [] });
            byKey.get(key).rows.push(row);
        }
        // Group order follows the sorted data (first appearance), so the active
        // sort decides which group leads; the "no value" group always trails.
        const ordered = [...byKey.values()];
        ordered.sort((a, b) => (a.key === '__none__') - (b.key === '__none__'));
        return ordered;
    }, [sortedData, groupColumn]);
    const [collapsedGroups, setCollapsedGroups] = useState(() => new Set());
    const toggleGroup = (key) => setCollapsedGroups((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
    });

    // Rows in display order (groups expanded) — the cursor space for keyboardNav.
    const flatRows = useMemo(() => {
        if (!groups) return sortedData;
        return groups.flatMap((g) => (collapsedGroups.has(g.key) ? [] : g.rows));
    }, [groups, sortedData, collapsedGroups]);
    const rowIndexByKey = useMemo(() => {
        const map = new Map();
        flatRows.forEach((row, index) => {
            const key = typeof keyField === 'function' ? keyField(row) : row[keyField];
            map.set(key, index);
        });
        return map;
    }, [flatRows, keyField]);

    // ---- keyboard navigation ----------------------------------------------
    const [cursor, setCursor] = useState(-1);
    const wrapRef = useRef(null);

    useEffect(() => {
        if (!keyboardNav) return undefined;
        const onKey = (event) => {
            const target = event.target;
            if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"], [role="dialog"]')) {
                return;
            }
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            const rowCount = flatRows.length;
            if (!rowCount) return;
            if (event.key === 'j' || event.key === 'ArrowDown') {
                event.preventDefault();
                setCursor((c) => Math.min(c + 1, rowCount - 1));
            } else if (event.key === 'k' || event.key === 'ArrowUp') {
                event.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
            } else if (event.key === 'Enter' && cursor >= 0 && onRowClick) {
                event.preventDefault();
                onRowClick(flatRows[cursor]);
            } else if (event.key === 'x' && selectable && cursor >= 0) {
                event.preventDefault();
                const row = flatRows[cursor];
                const key = typeof keyField === 'function' ? keyField(row) : row[keyField];
                onToggleRow?.(key, !selectedKeys?.includes(key));
            }
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [keyboardNav, flatRows, cursor, onRowClick, selectable, selectedKeys, onToggleRow, keyField]);

    // Keep the cursor row on screen.
    useEffect(() => {
        if (cursor < 0 || !wrapRef.current) return;
        wrapRef.current.querySelector('tr.is-cursor')?.scrollIntoView({ block: 'nearest' });
    }, [cursor]);

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
    const columnCount = visibleColumns.length + (selectable ? 1 : 0);

    const allSelected = selectable && flatRows.length > 0 && flatRows.every((row) => {
        const key = typeof keyField === 'function' ? keyField(row) : row[keyField];
        return selectedKeys?.includes(key);
    });
    const someSelected = selectable && !allSelected && flatRows.some((row) => {
        const key = typeof keyField === 'function' ? keyField(row) : row[keyField];
        return selectedKeys?.includes(key);
    });

    const renderDataRow = (row) => {
        const key = typeof keyField === 'function' ? keyField(row) : row[keyField];
        const computedRowClass = typeof rowClassName === 'function'
            ? rowClassName(row)
            : rowClassName;
        const rowIndex = rowIndexByKey.get(key) ?? -1;
        const isSelected = selectable && selectedKeys?.includes(key);

        if (renderRow) {
            return renderRow(row, { key, className: computedRowClass });
        }

        return (
            <TableRow
                key={key}
                className={cn(
                    computedRowClass,
                    onRowClick && 'is-clickable',
                    isSelected && 'is-selected',
                    keyboardNav && rowIndex === cursor && 'is-cursor',
                )}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
                {selectable && (
                    <TableCell className="sk-dtable__check" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                            checked={isSelected}
                            onCheckedChange={(checked) => onToggleRow?.(key, !!checked)}
                            aria-label="Select row"
                        />
                    </TableCell>
                )}
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
    };

    return (
        <div className={cn('sk-dtable-wrap', className)} ref={wrapRef}>
            <Table className={cn('sk-dtable', tableClassName)}>
                <TableHeader>
                    <TableRow>
                        {selectable && (
                            <TableHead className="sk-dtable__check">
                                <Checkbox
                                    checked={allSelected ? true : someSelected ? 'indeterminate' : false}
                                    onCheckedChange={(checked) => onToggleAll?.(!!checked)}
                                    aria-label="Select all rows"
                                />
                            </TableHead>
                        )}
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
                    {groups
                        ? groups.map((group) => {
                            const isCollapsed = collapsedGroups.has(group.key);
                            const label = groupColumn.groupLabel
                                ? groupColumn.groupLabel(group.value, group.rows)
                                : (group.value ?? 'None');
                            return [
                                <TableRow
                                    key={`group-${group.key}`}
                                    className={cn('sk-dtable__group', isCollapsed && 'is-collapsed')}
                                    onClick={() => toggleGroup(group.key)}
                                >
                                    <TableCell colSpan={columnCount}>
                                        <span className="sk-dtable__group-inner">
                                            <ChevronRight size={14} className="sk-dtable__group-chev" />
                                            <span className="sk-dtable__group-label">{label}</span>
                                            <span className="sk-dtable__group-count">{group.rows.length}</span>
                                        </span>
                                    </TableCell>
                                </TableRow>,
                                ...(isCollapsed ? [] : group.rows.map(renderDataRow)),
                            ];
                        })
                        : sortedData.map(renderDataRow)}
                </TableBody>
            </Table>
            {footer}
        </div>
    );
}

export default DataTable;
