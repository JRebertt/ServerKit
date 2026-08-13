import { useMemo, useRef, useState } from 'react';
import { ArrowUp, ArrowDown, Check, ChevronDown, ChevronRight, Filter, Minus } from 'lucide-react';
import { cn } from '@/lib/utils';
import ColumnMenu from './ColumnMenu';
import { byKey, columnLabel, fieldValue, isSortable } from './fields';

// The grid itself: a CSS-grid table (NOT a <table>) whose header and rows share
// one `--sk-grid-tpl` track list, so a column's width is declared once next to
// the column and every row obeys it. That is what makes per-column reordering
// and show/hide a pure data change — there is no <colgroup> to keep in sync.
//
// Everything user-facing hangs off the header cell: the label is the sort
// toggle, and the "⋮" opens <ColumnMenu> (sort · group · filter · move · hide).
export function DataGrid({
    columns,
    groups,            // from useGridRows — [[groupLabel|null, rows], …]
    allRows,           // unfiltered, for the column menu's option counts
    cfg,
    grid,              // the useGridConfig api
    keyField = 'id',
    selectable = false,
    selectedKeys = [],
    onToggleRow,
    onToggleAll,
    onRowClick,
    onRowContextMenu,
    rowActions,
    rowLeading,        // (row) => JSX rendered as the name-cell avatar/chip
    empty,
    footer,
    className,
}) {
    const [openMenu, setOpenMenu] = useState(null);
    const [collapsed, setCollapsed] = useState(() => new Set());
    const lastIndex = useRef(null);

    const map = useMemo(() => byKey(columns), [columns]);
    const visible = useMemo(
        () => cfg.cols.map((key) => map.get(key)).filter(Boolean),
        [cfg.cols, map],
    );
    const lockedCount = useMemo(
        () => visible.findIndex((c) => !c.locked) === -1 ? visible.length : visible.findIndex((c) => !c.locked),
        [visible],
    );

    // "38px <col tracks> 44px" — checkbox gutter, the columns, row-end actions.
    const tpl = useMemo(() => [
        selectable ? '38px' : null,
        ...visible.map((c) => c.width || 'minmax(120px,1fr)'),
        rowActions ? '44px' : null,
    ].filter(Boolean).join(' '), [visible, selectable, rowActions]);

    const keyOf = (row) => (typeof keyField === 'function' ? keyField(row) : row[keyField]);
    const flat = useMemo(
        () => groups.flatMap(([label, rows]) => (collapsed.has(label) ? [] : rows)),
        [groups, collapsed],
    );
    const picked = useMemo(() => new Set(selectedKeys), [selectedKeys]);
    const allOn = flat.length > 0 && flat.every((r) => picked.has(keyOf(r)));
    const someOn = !allOn && flat.some((r) => picked.has(keyOf(r)));

    const toggleGroupOpen = (label) => setCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(label)) next.delete(label); else next.add(label);
        return next;
    });

    // Shift-click extends the selection from the last row you touched — the
    // behaviour every file manager has trained people to expect.
    const handleRowCheck = (row, index, event) => {
        const key = keyOf(row);
        if (event.shiftKey && lastIndex.current != null) {
            const [a, b] = [lastIndex.current, index].sort((x, y) => x - y);
            onToggleAll?.(true, flat.slice(a, b + 1).map(keyOf));
        } else {
            onToggleRow?.(key, !picked.has(key));
        }
        lastIndex.current = index;
    };

    const headerSort = (column) => {
        if (!isSortable(column)) return;
        const active = cfg.sort.key === column.key;
        grid.setSort(column.key, active && cfg.sort.dir === 'asc' ? 'desc' : 'asc');
    };

    return (
        <div
            className={cn('sk-grid', cfg.density === 'compact' && 'sk-grid--compact', className)}
            style={{ '--sk-grid-tpl': tpl }}
        >
            <div className="sk-grid__head" role="row">
                {selectable && (
                    <div
                        className="sk-grid__th sk-grid__check"
                        role="columnheader"
                        onClick={() => onToggleAll?.(!allOn, flat.map(keyOf))}
                    >
                        <span className={cn('sk-grid__box', allOn && 'is-on', someOn && 'is-part')}>
                            {allOn ? <Check size={11} /> : someOn ? <Minus size={11} /> : null}
                        </span>
                    </div>
                )}

                {visible.map((column, index) => {
                    const filtered = cfg.filters.rules.some((r) => r.field === column.key);
                    const sorted = cfg.sort.key === column.key;
                    return (
                        <div
                            key={column.key}
                            role="columnheader"
                            aria-sort={sorted ? (cfg.sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                            className={cn(
                                'sk-grid__th',
                                filtered && 'is-filtered',
                                sorted && 'is-sorted',
                                column.align === 'right' && 'is-num',
                                isSortable(column) && 'is-sortable',
                            )}
                            onClick={() => headerSort(column)}
                        >
                            <span className="sk-grid__thlabel">{columnLabel(column)}</span>
                            {filtered && <Filter size={11} />}
                            {sorted && (
                                <span className="sk-grid__tharrow">
                                    {cfg.sort.dir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />}
                                </span>
                            )}
                            <ColumnMenu
                                column={column}
                                rows={allRows}
                                sortDir={sorted ? cfg.sort.dir : null}
                                grouped={cfg.group === column.key}
                                rule={cfg.filters.rules.find((r) => r.field === column.key) || null}
                                canMoveLeft={index > lockedCount}
                                canMoveRight={index < visible.length - 1}
                                onSort={grid.setSort}
                                onToggleGroup={grid.toggleGroup}
                                onPutRule={grid.putColumnRule}
                                onMove={(key, delta) => grid.moveColumn(key, delta, lockedCount)}
                                onHide={grid.hideColumn}
                                open={openMenu === column.key}
                                onOpenChange={(open) => setOpenMenu(open ? column.key : null)}
                            />
                        </div>
                    );
                })}

                {rowActions && <div className="sk-grid__th" role="columnheader" />}
            </div>

            {flat.length === 0 && groups.every(([, rows]) => rows.length === 0)
                ? <div className="sk-grid__empty">{empty}</div>
                : groups.map(([label, rows]) => (
                    <div key={label ?? '__all__'} className="sk-grid__group-wrap">
                        {label != null && (
                            <button
                                type="button"
                                className="sk-grid__group"
                                onClick={() => toggleGroupOpen(label)}
                                aria-expanded={!collapsed.has(label)}
                            >
                                {collapsed.has(label) ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                                {label}
                                <i />
                                <span className="sk-grid__groupcount">{rows.length}</span>
                            </button>
                        )}
                        {(label != null && collapsed.has(label) ? [] : rows).map((row) => {
                            const key = keyOf(row);
                            const index = flat.indexOf(row);
                            const on = picked.has(key);
                            return (
                                <div
                                    key={key}
                                    role="row"
                                    className={cn('sk-grid__row', on && 'is-picked', onRowClick && 'is-clickable')}
                                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                                    onContextMenu={onRowContextMenu
                                        ? (e) => { e.preventDefault(); onRowContextMenu(row, e); }
                                        : undefined}
                                >
                                    {selectable && (
                                        <div
                                            className="sk-grid__td sk-grid__check"
                                            onClick={(e) => { e.stopPropagation(); handleRowCheck(row, index, e); }}
                                        >
                                            <span className={cn('sk-grid__box', on && 'is-on')}>
                                                {on ? <Check size={11} /> : null}
                                            </span>
                                        </div>
                                    )}
                                    {visible.map((column, ci) => (
                                        <div
                                            key={column.key}
                                            role="cell"
                                            className={cn(
                                                'sk-grid__td',
                                                column.align === 'right' && 'is-num',
                                                column.cellClassName,
                                            )}
                                        >
                                            {ci === 0 && (rowLeading || cfg.sub.length)
                                                ? (
                                                    <div className="sk-grid__name">
                                                        {rowLeading && <span className="sk-grid__avatar">{rowLeading(row)}</span>}
                                                        <div className="sk-grid__nameinner">
                                                            <div className="sk-grid__nm">
                                                                {column.render ? column.render(row) : fieldValue(column, row)}
                                                            </div>
                                                            {!!cfg.sub.length && (
                                                                <div className="sk-grid__sub">
                                                                    {cfg.sub.map((sk, si) => {
                                                                        const sc = map.get(sk);
                                                                        if (!sc) return null;
                                                                        const v = fieldValue(sc, row);
                                                                        return (
                                                                            <span key={sk} className="sk-grid__subitem">
                                                                                {si > 0 && <i />}
                                                                                <b>{columnLabel(sc)}</b>
                                                                                {sc.type === 'bool' ? (v ? 'on' : 'off') : String(v ?? '—')}
                                                                            </span>
                                                                        );
                                                                    })}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                )
                                                : (column.render ? column.render(row) : fieldValue(column, row))}
                                        </div>
                                    ))}
                                    {rowActions && (
                                        <div className="sk-grid__td sk-grid__rowend" onClick={(e) => e.stopPropagation()}>
                                            {rowActions(row)}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ))}

            {footer}
        </div>
    );
}

export default DataGrid;
