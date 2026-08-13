import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useOutletContext } from 'react-router-dom';

// Publish a page's top-bar actions into the enclosing TabGroupLayout header.
// Pages in a tab group render no PageTopbar of their own, so the shared layout
// shows their actions instead.
//
// Pass a RENDER THUNK that returns the action node — `() => (<Button…/>)` — not
// the node itself. The thunk is invoked inside the effect (after render), so it
// can safely reference handlers declared anywhere in the component without
// hitting the temporal dead zone. (A raw node is still accepted for
// convenience.) `deps` are the reactive values the node reads (e.g.
// [loading, isAdmin]); the node/thunk itself is intentionally not a dependency.
// No-op when rendered outside a tab group (e.g. a page reused as a plain route).
export function useTopbarActions(actions, deps = []) {
    const ctx = useOutletContext();
    const setTopbarActions = ctx?.setTopbarActions;

    useEffect(() => {
        if (!setTopbarActions) return undefined;
        setTopbarActions(typeof actions === 'function' ? actions() : actions);
        return () => setTopbarActions(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [setTopbarActions, ...deps]);
}

// The SECOND top-bar slot: a table's own chrome — search, the filter button and
// the "⋮". It is separate from useTopbarActions because the two are published
// by different owners at different times. A page's actions ("Add domain") are
// the page's; the chrome belongs to whichever table is on it, which may be a
// shared wrapper like ResourceListPage that has no business overwriting what
// the page put in the actions slot. One `setTopbarActions(node)` call per page
// meant the wrapper and the page could only fight over it.
//
// Layout order in the bar is fixed so the search box never moves when a page
// adds an action: [page actions] [search] [filter] [⋮].
//
// This PORTALS into a slot the layout renders, rather than handing the node up
// through the layout's state the way useTopbarActions does. That is not a style
// preference — publishing a node upward means an effect whose dependency list
// has to describe everything the node closes over, and the chrome closes over
// `chrome.toolsProps`, which useTableChrome rebuilds on every render. The effect
// then fired every render, set state on the layout, and re-rendered the child:
// "Maximum update depth exceeded", a hung tab group, and a request storm behind
// it. A portal has no such dependency — the child renders its own node, into
// someone else's DOM.
//
// Returns { hosted, portal }. `hosted` is false when there is no tab group above
// (a page reused as a plain route) or when `enabled` is false — which is how an
// inner table opts out: the route's top bar belongs to the page around it, so a
// tab's table would be hijacking someone else's bar. Render `portal` anywhere
// (it lands in the top bar regardless) and fall back to inline when not hosted:
//
//   const chrome = <><SearchField…/><GridFilterButton…/><GridToolsMenu…/></>;
//   const { hosted, portal } = useTopbarChrome(chrome, { enabled: !inner });
//   return <>{portal}<GridViewPicker … actions={hosted ? null : chrome} /></>;
export function useTopbarChrome(chrome, { enabled = true } = {}) {
    const ctx = useOutletContext();
    // `hasTopbarChrome` is a constant in the context, known on the FIRST render;
    // the slot element only exists after the layout has committed. Deciding
    // `hosted` from the constant keeps a page from rendering its chrome inline
    // for one frame and then yanking it into the bar.
    const hosted = !!ctx?.hasTopbarChrome && enabled;
    const slot = ctx?.topbarChromeSlot;
    const node = typeof chrome === 'function' ? chrome() : chrome;

    return {
        hosted,
        portal: hosted && slot ? createPortal(node, slot) : null,
        // Pass straight to GridViewPicker's `actions`. Deriving it here rather
        // than leaving each caller to write `hosted ? null : node` is the point:
        // every one of the eight pages that hoists its chrome destructured only
        // `portal` and forgot the fallback, so outside a tab group the filter
        // button and "⋮" would not have gone inline — they would have gone
        // nowhere. Null when the top bar took it, and null when `enabled` is
        // false, which means "this table is not on screen, render nothing".
        actions: hosted || !enabled ? null : node,
    };
}

export default useTopbarActions;
