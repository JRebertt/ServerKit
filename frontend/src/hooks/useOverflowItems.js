import { useState, useRef, useEffect, useCallback } from 'react';

function arraysEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
}

/**
 * Measure overflow items at their natural width without leaving collapsed
 * items visible. CSS-hidden consumers (for example PageTopbar's `is-hidden`
 * class) and inline-hidden consumers both need an explicit display override;
 * clearing only the inline declaration does not override a stylesheet rule.
 *
 * DOM writes are applied before any width reads to avoid a layout flush for
 * every item in the strip.
 */
export function measureNaturalWidths(items) {
    const elements = Array.isArray(items) ? items : [];
    const restore = [];

    for (const element of elements) {
        if (!element || getComputedStyle(element).display !== 'none') continue;
        restore.push([element, element.style.display]);
        element.style.display = 'inline-flex';
    }

    let widths;
    try {
        widths = elements.map((element) => element?.offsetWidth || 0);
    } finally {
        for (const [element, display] of restore) {
            element.style.display = display;
        }
    }

    return widths;
}

/**
 * Keep overflow state safe while a shared tab layout switches to a shorter
 * item list. Effects recompute after render, so consumers must not receive
 * indexes that were valid for the previous route but are invalid now.
 */
export function sanitizeOverflowIndices(indices, count) {
    if (!Array.isArray(indices) || !Number.isInteger(count) || count <= 0) return [];

    const safe = [];
    const seen = new Set();
    for (const index of indices) {
        if (!Number.isInteger(index) || index < 0 || index >= count || seen.has(index)) continue;
        seen.add(index);
        safe.push(index);
    }
    return safe;
}

/**
 * Tracks which child items overflow a container and should be collapsed into a
 * "More" menu. Items are greedily fit left-to-right; the active item is always
 * kept visible by rebuilding the visible set around it.
 *
 * @param {Object} options
 * @param {number} options.count - Number of items to measure.
 * @param {React.MutableRefObject<(HTMLElement|null)[]>} [options.itemRefs] - Optional external ref array for the items. Useful when the caller needs to read from the refs (e.g. to detect active state).
 * @param {number} [options.gap=8] - Gap between items in pixels.
 * @param {number} [options.moreWidth=36] - Estimated width of the "More" trigger.
 * @param {() => number} [options.getActiveIndex=() => -1] - Returns the index of the item that must stay visible.
 * @param {React.DependencyList} [options.deps=[]] - Additional dependencies that should trigger a recompute.
 *
 * @returns {{
 *   containerRef: React.RefObject<HTMLElement>,
 *   itemRefs: React.MutableRefObject<(HTMLElement|null)[]>,
 *   moreBtnRef: React.RefObject<HTMLElement>,
 *   hiddenIndices: number[],
 *   hiddenSet: Set<number>,
 *   recompute: () => void
 * }}
 */
export function useOverflowItems({ count, itemRefs: externalItemRefs, gap = 8, moreWidth = 36, getActiveIndex = () => -1, deps = [] }) {
    const containerRef = useRef(null);
    const internalItemRefs = useRef([]);
    const moreBtnRef = useRef(null);
    const [hiddenIndices, setHiddenIndices] = useState([]);

    const itemRefs = externalItemRefs || internalItemRefs;
    itemRefs.current.length = count;

    const recompute = useCallback(() => {
        const container = containerRef.current;
        if (!container) return;
        const containerWidth = container.clientWidth;
        if (containerWidth === 0) return;

        // Measure each item's natural width (briefly un-hiding collapsed ones).
        const widths = measureNaturalWidths(itemRefs.current);

        const activeIndex = getActiveIndex();
        const actualMoreWidth = moreBtnRef.current?.offsetWidth || moreWidth;

        // All fit?
        const total = widths.reduce((s, w, i) => s + w + (i > 0 ? gap : 0), 0);
        if (total <= containerWidth) {
            setHiddenIndices((prev) => (prev.length === 0 ? prev : []));
            return;
        }

        // Reserve space for the More button, then greedily fit left-to-right.
        const budget = Math.max(0, containerWidth - actualMoreWidth - gap);
        const visible = [];
        let used = 0;
        for (let i = 0; i < widths.length; i++) {
            const cost = widths[i] + (visible.length > 0 ? gap : 0);
            if (used + cost <= budget) {
                visible.push(i);
                used += cost;
            } else {
                break;
            }
        }

        // The active item must stay visible — rebuild the visible set around it.
        let visibleSet = visible;
        if (activeIndex !== -1 && !visible.includes(activeIndex)) {
            const others = [];
            let othersUsed = widths[activeIndex];
            for (let i = 0; i < widths.length; i++) {
                if (i === activeIndex) continue;
                const cost = widths[i] + (others.length === 0 ? gap : gap);
                if (othersUsed + cost <= budget) {
                    others.push(i);
                    othersUsed += cost;
                }
            }
            visibleSet = [...others, activeIndex].sort((a, b) => a - b);
        }

        const visibleSetObj = new Set(visibleSet);
        const hidden = [];
        for (let i = 0; i < widths.length; i++) {
            if (!visibleSetObj.has(i)) hidden.push(i);
        }
        setHiddenIndices((prev) => (arraysEqual(prev, hidden) ? prev : hidden));
    }, [count, gap, moreWidth, getActiveIndex, ...deps]);

    // Initial measurement after first paint.
    useEffect(() => {
        recompute();
    }, [recompute, count]);

    // Re-fit on container resize.
    useEffect(() => {
        const container = containerRef.current;
        if (!container || typeof ResizeObserver === 'undefined') return undefined;
        const ro = new ResizeObserver(() => recompute());
        ro.observe(container);
        return () => ro.disconnect();
    }, [recompute]);

    // A route change can reduce `count` before the measurement effect updates
    // state. Clamp synchronously so this render can never dereference a stale
    // item index (most visible with wider translated labels).
    const safeHiddenIndices = sanitizeOverflowIndices(hiddenIndices, count);
    const hiddenSet = new Set(safeHiddenIndices);

    return {
        containerRef,
        itemRefs,
        moreBtnRef,
        hiddenIndices: safeHiddenIndices,
        hiddenSet,
        recompute,
    };
}

export default useOverflowItems;
