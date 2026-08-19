// The scheduling rules behind usePolling, as a plain object so they can be
// tested without a DOM.
//
// Two rules, both of which every hand-rolled `setInterval(load, 5000)` in this
// codebase got wrong:
//
// 1. NEVER let a tick start while the previous one is still in flight. A poller
//    on a 5s interval against a request that has started taking 30s does not
//    slow down — it stacks, and each new request makes the server slower, which
//    makes the next request more likely to overlap. That is the stampede: the
//    page gets slower the longer you leave it open, and the server sees a load
//    it never sees in a fresh session.
//
// 2. Do not poll a tab nobody is looking at. A background tab polling every 5s
//    is pure cost, and browsers throttle its timers unevenly anyway, so it is
//    not even a reliable refresh. Catch up ONCE when it comes back instead —
//    which is also what makes the data fresh at the moment someone looks.
//
// A skipped tick is not a dropped update: the next one takes its place, and the
// in-flight request that caused the skip is delivering the same data.

export const DEFAULT_INTERVAL_MS = 5000;

/**
 * @param {object} config
 * @param {() => (Promise<any>|any)} config.run   the work to repeat
 * @param {number} config.intervalMs              delay BETWEEN runs
 * @param {(fn: Function, ms: number) => any} config.setTimer
 * @param {(handle: any) => void} config.clearTimer
 * @param {() => boolean} [config.isHidden]       document.hidden, injected
 * @param {(error: any) => void} [config.onError]
 */
export function createPollScheduler({
    run,
    intervalMs = DEFAULT_INTERVAL_MS,
    setTimer,
    clearTimer,
    isHidden = () => false,
    onError,
}) {
    let handle = null;
    let inFlight = false;
    let stopped = true;
    let skipped = 0;

    const clear = () => {
        if (handle !== null) {
            clearTimer(handle);
            handle = null;
        }
    };

    // A timeout chained after each run, not setInterval: with setInterval the
    // delay is measured from tick to tick regardless of how long the work took,
    // so slow work silently turns a 5s gap into no gap at all.
    const schedule = () => {
        clear();
        if (stopped || isHidden()) return;
        handle = setTimer(tick, intervalMs);
    };

    function tick() {
        handle = null;
        if (stopped) return;
        if (inFlight) {
            // Rule 1. Do not queue behind it; the next tick will do.
            skipped += 1;
            schedule();
            return;
        }
        if (isHidden()) return;          // rule 2; onVisible() resumes

        let result;
        inFlight = true;
        try {
            result = run();
        } catch (error) {
            inFlight = false;
            onError?.(error);
            schedule();
            return;
        }

        if (!result || typeof result.then !== 'function') {
            inFlight = false;
            schedule();
            return;
        }

        result.then(
            () => { inFlight = false; schedule(); },
            (error) => { inFlight = false; onError?.(error); schedule(); },
        );
    }

    return {
        /** Begin polling. `runNow` performs the first run immediately. */
        start({ runNow = true } = {}) {
            stopped = false;
            if (runNow) tick();
            else schedule();
        },
        stop() {
            stopped = true;
            clear();
        },
        /** Visibility changed. Coming back runs once immediately to catch up. */
        setHidden(hidden) {
            if (stopped) return;
            if (hidden) clear();
            else tick();
        },
        /** Run now, outside the schedule, honouring the in-flight guard. */
        refresh() {
            if (stopped) {
                stopped = false;
            }
            tick();
        },
        /** Test/diagnostic surface. */
        get isRunning() { return !stopped; },
        get isInFlight() { return inFlight; },
        get skippedTicks() { return skipped; },
    };
}

export default createPollScheduler;
