import { useCallback, useEffect, useRef } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import {
    copyableLink, handleFor, readViewParams, resolveView, withViewParam,
} from './viewLinks';
import { copyToClipboard } from '@/utils/clipboard';

/**
 * Keeps a list page's URL and its active view in sync, both ways.
 *
 *   inbound  — ?view=<slug> applies that saved/built-in view once the views
 *              have loaded; ?v=<encoded> applies a self-contained state.
 *   outbound — switching views rewrites ?view=; the address bar is then a
 *              shareable link with no extra step.
 *
 *   const { copyLink } = useViewLink({ views, apply, capture });
 *
 * `apply` is the same adapter the view picker uses, so a link and a click go
 * through one code path.
 */
export function useViewLink({ views, apply, capture, enabled = true, scope = '' }) {
    const location = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const appliedFromUrl = useRef(false);
    const lastHandle = useRef(null);

    const activeView = views?.activeView || null;
    const loading = views?.loading;

    // ---- inbound ---------------------------------------------------------
    useEffect(() => {
        if (!enabled || appliedFromUrl.current) return;
        const request = readViewParams(location.search, scope);
        if (!request.kind) { appliedFromUrl.current = true; return; }

        if (request.kind === 'state') {
            apply(request.state);
            appliedFromUrl.current = true;
            return;
        }
        // A slug needs the saved views to have arrived before it can resolve;
        // wait rather than silently deciding the link is broken.
        if (loading) return;
        const match = resolveView(request, {
            builtinViews: views?.builtinViews || [],
            userViews: views?.userViews || [],
        });
        if (match) {
            // ?view=<slug> plus readable params means "that view, tweaked" —
            // apply the view first, then layer the overrides on top.
            views.applyView(match);
            if (request.overrides) {
                const merged = { ...(match.state || {}), ...request.overrides };
                setTimeout(() => apply(merged), 0);
            }
        }
        appliedFromUrl.current = true;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [enabled, loading, location.search]);

    // ---- outbound --------------------------------------------------------
    useEffect(() => {
        if (!enabled || !appliedFromUrl.current) return;
        const handle = handleFor(activeView);
        if (handle === lastHandle.current) return;
        lastHandle.current = handle;
        // replace, not push: flipping through views should not fill the back
        // button with table states.
        setSearchParams(withViewParam(location.search, handle, scope), { replace: true });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [enabled, activeView]);

    const copyLink = useCallback(async () => {
        const url = copyableLink({
            pathname: location.pathname,
            view: activeView,
            isDirty: views?.isDirty,
            state: capture ? capture() : {},
            scope,
        });
        const copied = await copyToClipboard(url);
        return { url, copied }; // clipboard blocked: hand back the URL
    }, [location.pathname, activeView, views?.isDirty, capture, scope]);

    return { copyLink, searchParams };
}

export default useViewLink;
