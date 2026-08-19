import { useCallback, useEffect, useRef } from 'react';

import { createPollScheduler, DEFAULT_INTERVAL_MS } from '@/utils/pollScheduler';

// One convention for "keep this fresh while the user is looking at it".
//
//   usePolling(loadStatus, 5000);
//   usePolling(loadLogs, 3000, { enabled: autoRefresh });
//
// Replaces the `useEffect(() => { const t = setInterval(load, 5000); return
// () => clearInterval(t); })` block, which this codebase had ~47 of and which
// gets two things wrong every time:
//
//   * it starts a new request every 5s whether or not the last one came back,
//     so a slow endpoint turns into a growing pile of concurrent requests;
//   * it keeps polling a tab nobody is looking at.
//
// The scheduling itself lives in utils/pollScheduler.js so it can be tested
// without a DOM; this is the React binding.
//
// `callback` is held in a ref, so an inline arrow re-created every render does
// NOT restart the timer — the usual reason a hand-rolled poller silently polls
// far faster than its stated interval.
//
// Returns a stable `refresh()` for "reload now" buttons, which goes through the
// same in-flight guard.
export function usePolling(callback, intervalMs = DEFAULT_INTERVAL_MS, options = {}) {
    const {
        enabled = true,
        immediate = true,
        pauseWhenHidden = true,
        onError,
    } = options;

    const callbackRef = useRef(callback);
    const onErrorRef = useRef(onError);
    callbackRef.current = callback;
    onErrorRef.current = onError;

    const schedulerRef = useRef(null);

    useEffect(() => {
        if (!enabled || !intervalMs) return undefined;

        const scheduler = createPollScheduler({
            run: () => callbackRef.current?.(),
            intervalMs,
            setTimer: (fn, ms) => window.setTimeout(fn, ms),
            clearTimer: (handle) => window.clearTimeout(handle),
            isHidden: () => (
                pauseWhenHidden
                && typeof document !== 'undefined'
                && document.visibilityState === 'hidden'
            ),
            onError: (error) => onErrorRef.current?.(error),
        });
        schedulerRef.current = scheduler;
        scheduler.start({ runNow: immediate });

        let onVisibility;
        if (pauseWhenHidden && typeof document !== 'undefined') {
            onVisibility = () => scheduler.setHidden(document.visibilityState === 'hidden');
            document.addEventListener('visibilitychange', onVisibility);
        }

        return () => {
            if (onVisibility) document.removeEventListener('visibilitychange', onVisibility);
            scheduler.stop();
            schedulerRef.current = null;
        };
    }, [enabled, intervalMs, immediate, pauseWhenHidden]);

    return useCallback(() => {
        const scheduler = schedulerRef.current;
        if (scheduler) {
            scheduler.refresh();
            return;
        }
        // Disabled or unmounted: a manual refresh should still do the work.
        callbackRef.current?.();
    }, []);
}

export default usePolling;
