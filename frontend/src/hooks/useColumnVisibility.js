import { useCallback, useEffect, useState } from 'react';

// Column-visibility state for DataTable, paired with ds/ColumnsMenu.
// `hiddenKeys` is a string[] of column keys currently hidden. Columns opt out
// of hiding with `hideable: false` (e.g. a primary name column or an actions
// column) — those never appear in the menu and can never be hidden.
//
//   const { hiddenKeys, toggleColumn, showAllColumns } = useColumnVisibility({
//     storageKey: 'serverkit-cols-servers',   // optional localStorage persistence
//   });

function readStored(storageKey) {
    if (!storageKey) return null;
    try {
        const raw = window.localStorage.getItem(storageKey);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed.filter((k) => typeof k === 'string') : null;
    } catch {
        return null;
    }
}

export function useColumnVisibility({ defaultHidden = [], storageKey } = {}) {
    const [hiddenKeys, setHiddenKeys] = useState(() => readStored(storageKey) ?? defaultHidden);

    useEffect(() => {
        if (!storageKey) return;
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(hiddenKeys));
        } catch {
            /* private mode / quota — the choice just doesn't persist */
        }
    }, [hiddenKeys, storageKey]);

    const toggleColumn = useCallback((key) => {
        setHiddenKeys((prev) => (
            prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
        ));
    }, []);

    const showAllColumns = useCallback(() => setHiddenKeys([]), []);

    return { hiddenKeys, setHiddenKeys, toggleColumn, showAllColumns };
}

export default useColumnVisibility;
