import { useCallback, useMemo, useRef } from 'react';
import useTableViews from './useTableViews';
import useViewLink from './useViewLink';
import { emptyViewState, sameViewState, toEnvelope } from './viewState';

/**
 * The ONE place saved views are wired up.
 *
 * Both chrome hosts go through it — `useTableChrome` (the <DataTable> pages)
 * and `useGridConfig` (the <DataGrid> pages) — so the three things that used to
 * be per-page are now structural:
 *
 *   · every view is captured in the same envelope (see `viewState.js`)
 *   · every page gets shareable `?view=` links, not just the ones someone
 *     remembered to wire `useViewLink` into
 *   · a guard or control added to the chrome lands here once
 *
 *   const views = useGridViews({
 *     page: 'cronjobs', builtinViews, capture, apply,
 *     rename: { filters: 'serverFilters' },   // legacy top-level key -> page bag
 *   });
 *
 * `capture` returns the page's live state and `apply` pushes one back; both are
 * normalised to the envelope here, so a page never has to think about the
 * shape a previous release happened to persist.
 */
export function useGridViews({ page, builtinViews = [], capture, apply, rename, resetToView }) {
    // `rename` is almost always an inline literal. Freeze the first one rather
    // than rebuilding every callback below on each render — the map is a
    // per-page constant, and a changing identity here would reach `apply`,
    // which several pages put in an effect dependency array.
    const renameRef = useRef(rename);
    const renameMap = renameRef.current;

    // Presets authored before the envelope are migrated on the way in, so a
    // page can adopt it without rewriting its built-ins in the same commit.
    // Keyed on names for the same reason useTableViews is: an inline
    // `builtinViews={[…]}` literal is a new array identity every render.
    const builtinKey = builtinViews.map((v) => v.name).join(' ');
    const migratedBuiltins = useMemo(
        () => builtinViews.map((v) => ({ ...v, state: toEnvelope(v.state, { rename: renameMap }) })),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [builtinKey, renameMap],
    );

    const captureEnvelope = useCallback(
        () => toEnvelope(capture?.() ?? {}, { rename: renameMap }),
        [capture, renameMap],
    );

    const applyEnvelope = useCallback(
        (state) => apply?.(toEnvelope(state, { rename: renameMap })),
        [apply, renameMap],
    );

    const isSame = useCallback(
        (a, b) => sameViewState(a, b, { rename: renameMap }),
        [renameMap],
    );

    const views = useTableViews({
        page,
        builtinViews: migratedBuiltins,
        capture: captureEnvelope,
        apply: applyEnvelope,
        isSame,
    });

    // ?view=<slug> / ?v=<encoded> <-> the active view, both directions.
    // Applying a link goes through the SAME `apply` the picker uses, so a
    // shared link and a click can never drift apart.
    const { copyLink } = useViewLink({
        views,
        apply: applyEnvelope,
        capture: captureEnvelope,
        enabled: !!page,
    });

    // "Save current view…" with the checkbox cleared means a CLEAN view, not
    // "this view minus its name". Reset the live grid, but persist an explicit
    // empty envelope rather than re-reading state — the reset has not landed
    // yet, so capture() would still return what the checkbox said to discard.
    const createView = useCallback((name, fromCurrent) => {
        if (fromCurrent) return views.saveView(name);
        resetToView?.();
        return views.saveView(name, { state: emptyViewState() });
    }, [views, resetToView]);

    return { views, copyLink, createView, captureEnvelope, applyEnvelope };
}

export default useGridViews;
