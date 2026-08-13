import { useCallback, useEffect, useState } from 'react';

// Multi-column sort state for DataTable, datatables.net style.
//
// `sorts` is an ORDERED array — sorts[0] is the primary key, later entries
// break ties. Interaction model:
//
//   click header            -> make that column the only sort (asc -> desc -> none)
//   shift+click header      -> add/toggle an additional sort level
//   SortMenu rows           -> same upsert, plus explicit removal and "clear all"
//
// A column-level `sortValue(row)` accessor is honored, values compare as
// numbers when both are numeric, otherwise localeCompare; nulls always last.
//
//   const { sorts, toggleSort, clearSorts } = useTableSort({
//     defaultSorts: [{ key: 'name', direction: 'asc' }],
//     storageKey: 'serverkit-sort-servers',   // optional localStorage persistence
//   });

export function applyTableSorts(data, sorts, columns) {
    if (!sorts?.length) return data;
    const active = sorts
        .map((sort) => {
            const column = columns.find((c) => c.key === sort.key);
            if (!column) return null;
            return {
                direction: sort.direction === 'desc' ? -1 : 1,
                getValue: column.sortValue || ((row) => row[column.key]),
            };
        })
        .filter(Boolean);
    if (!active.length) return data;

    return [...data].sort((a, b) => {
        for (const { getValue, direction } of active) {
            const av = getValue(a);
            const bv = getValue(b);
            if (av == null && bv == null) continue;
            if (av == null) return direction;
            if (bv == null) return -direction;
            let cmp;
            if (typeof av === 'number' && typeof bv === 'number') {
                cmp = av - bv;
            } else {
                cmp = String(av).localeCompare(String(bv));
            }
            if (cmp !== 0) return cmp * direction;
        }
        return 0;
    });
}

function readStoredSorts(storageKey) {
    if (!storageKey) return null;
    try {
        const raw = window.localStorage.getItem(storageKey);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) && parsed.every((s) => s && typeof s.key === 'string')
            ? parsed
            : null;
    } catch {
        return null;
    }
}

export function useTableSort({ defaultSorts = [], storageKey } = {}) {
    const [sorts, setSorts] = useState(() => readStoredSorts(storageKey) ?? defaultSorts);

    useEffect(() => {
        if (!storageKey) return;
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(sorts));
        } catch {
            /* private mode / quota — the choice just doesn't persist */
        }
    }, [sorts, storageKey]);

    // Upsert-toggle a sort level. additive=false replaces the whole array
    // (plain header click); additive=true stacks a level (shift+click).
    const toggleSort = useCallback((key, additive = false) => {
        setSorts((prev) => {
            const index = prev.findIndex((s) => s.key === key);
            if (index === -1) {
                const next = { key, direction: 'asc' };
                return additive ? [...prev, next] : [next];
            }
            const current = prev[index];
            if (current.direction === 'asc') {
                const next = [...prev];
                next[index] = { key, direction: 'desc' };
                return additive ? next : [next[index]];
            }
            // desc -> remove the level entirely
            return prev.filter((s) => s.key !== key);
        });
    }, []);

    const clearSorts = useCallback(() => setSorts([]), []);

    return { sorts, setSorts, toggleSort, clearSorts };
}

// Same upsert-toggle as the hook's toggleSort, exported so controlled-mode
// hosts can compute the next sorts array without duplicating the logic.
export function nextSorts(prev, key, additive = false) {
    const index = prev.findIndex((s) => s.key === key);
    if (index === -1) {
        return additive ? [...prev, { key, direction: 'asc' }] : [{ key, direction: 'asc' }];
    }
    if (prev[index].direction === 'asc') {
        const next = [...prev];
        next[index] = { key, direction: 'desc' };
        return additive ? next : [next[index]];
    }
    return prev.filter((s) => s.key !== key);
}

export default useTableSort;
