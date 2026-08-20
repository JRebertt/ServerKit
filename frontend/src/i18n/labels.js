import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * Resolve a declaratively-keyed label from a data object (plan 79 §E).
 *
 * Data tables — sidebar items, tab tables, column definitions, wizard steps —
 * carry the pair
 *
 *     { labelKey: 'nav.dashboard', label: 'Dashboard' }
 *
 * rather than a `t()` call, because a `t()` in a module-level table resolves
 * ONCE at import and then never follows a locale switch. The extractor reads
 * the pair at its declaration site; this resolves it at render.
 *
 * An item with no key (an extension-contributed nav entry, for instance) falls
 * back to its raw label rather than rendering blank.
 */
export function translateLabel(t, item, field = 'label') {
    if (!item) return '';
    const fallback = item[field];
    const key = item[`${field}Key`];
    if (!key) return fallback ?? '';
    return t(key, { defaultValue: fallback ?? '' });
}

/** Hook form — re-renders with the active locale. */
export default function useLabel() {
    const { t } = useTranslation();
    return useCallback(
        (item, field = 'label') => translateLabel(t, item, field),
        [t],
    );
}
