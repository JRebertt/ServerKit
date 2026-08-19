import assert from 'node:assert/strict';
import test from 'node:test';

import { createPollScheduler } from '../pollScheduler.js';

// A hand-driven clock. The scheduler only ever talks to timers through the
// injected pair, so a test can advance time deterministically.
function fakeClock() {
    let next = 1;
    const pending = new Map();
    return {
        setTimer(fn, ms) {
            const id = next++;
            pending.set(id, { fn, ms });
            return id;
        },
        clearTimer(id) { pending.delete(id); },
        /** Fire every timer currently scheduled (one round). */
        async fire() {
            const round = [...pending.entries()];
            round.forEach(([id]) => pending.delete(id));
            round.forEach(([, t]) => t.fn());
            await Promise.resolve();
            await Promise.resolve();
        },
        get scheduled() { return pending.size; },
    };
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
}


test('runs immediately on start, then on each tick', async () => {
    const clock = fakeClock();
    let runs = 0;
    const poller = createPollScheduler({
        run: () => { runs += 1; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
    });

    poller.start();
    assert.equal(runs, 1, 'start() should run once immediately');

    await clock.fire();
    assert.equal(runs, 2);
    await clock.fire();
    assert.equal(runs, 3);

    poller.stop();
});


test('start({runNow:false}) waits for the first interval', async () => {
    const clock = fakeClock();
    let runs = 0;
    const poller = createPollScheduler({
        run: () => { runs += 1; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
    });

    poller.start({ runNow: false });
    assert.equal(runs, 0);
    await clock.fire();
    assert.equal(runs, 1);
    poller.stop();
});


test('the schedule itself can never overlap a request', async () => {
    // The stampede this module exists to prevent. Note the schedule cannot
    // produce one *structurally*: the next timer is armed by the previous run
    // finishing, so while a request is in flight there is no timer at all.
    // That is the property worth pinning — a guard you can also delete without
    // any test noticing would be no guard.
    const clock = fakeClock();
    const first = deferred();
    let starts = 0;
    const poller = createPollScheduler({
        run: () => { starts += 1; return first.promise; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
    });

    poller.start();
    assert.equal(starts, 1);
    assert.equal(clock.scheduled, 0, 'no timer may be armed while a request is in flight');

    await clock.fire();
    await clock.fire();
    assert.equal(starts, 1, 'nothing to fire, so nothing stacked');

    first.resolve();
    await Promise.resolve();
    await Promise.resolve();

    await clock.fire();
    assert.equal(starts, 2, 'polling resumes once the request settles');
    poller.stop();
});


test('out-of-band runs are what the in-flight guard actually protects', async () => {
    // refresh() and the visibility catch-up bypass the schedule, so they are
    // the paths that CAN land on top of a request in flight.
    const clock = fakeClock();
    const pending = deferred();
    let starts = 0;
    const poller = createPollScheduler({
        run: () => { starts += 1; return pending.promise; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
        isHidden: () => false,
    });

    poller.start();
    assert.equal(starts, 1);

    poller.refresh();
    poller.refresh();
    poller.setHidden(false);       // a catch-up while the first is still open
    poller.start();                // and a redundant start

    assert.equal(starts, 1, 'none of these may stack a second request');
    assert.equal(poller.skippedTicks, 4);

    pending.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await clock.fire();
    assert.equal(starts, 2);
    poller.stop();
});


test('a skipped tick does not queue up a burst afterwards', async () => {
    // Skipping must mean "drop it", not "remember it". Otherwise the stampede
    // just arrives later, all at once.
    const clock = fakeClock();
    const slow = deferred();
    let starts = 0;
    const poller = createPollScheduler({
        run: () => { starts += 1; return starts === 1 ? slow.promise : Promise.resolve(); },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
    });

    poller.start();
    for (let i = 0; i < 5; i += 1) await clock.fire();
    assert.equal(starts, 1);

    slow.resolve();
    await Promise.resolve();
    await Promise.resolve();

    await clock.fire();
    assert.equal(starts, 2, 'exactly one run, not five');
    assert.equal(clock.scheduled, 1, 'and exactly one timer outstanding');
    poller.stop();
});


test('the gap is measured after the work finishes, not tick to tick', async () => {
    const clock = fakeClock();
    let starts = 0;
    let pendingRun = deferred();
    const poller = createPollScheduler({
        run: () => { starts += 1; return pendingRun.promise; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
    });

    poller.start();
    assert.equal(clock.scheduled, 0, 'nothing is scheduled while work is in flight');

    pendingRun.resolve();
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(clock.scheduled, 1, 'the next tick is scheduled only once work settled');

    pendingRun = deferred();
    await clock.fire();
    assert.equal(starts, 2);
    poller.stop();
});


test('stops polling while the tab is hidden and catches up when it returns', async () => {
    const clock = fakeClock();
    let hidden = false;
    let runs = 0;
    const poller = createPollScheduler({
        run: () => { runs += 1; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
        isHidden: () => hidden,
    });

    poller.start();
    assert.equal(runs, 1);

    hidden = true;
    poller.setHidden(true);
    assert.equal(clock.scheduled, 0, 'no timer should be armed for a hidden tab');
    await clock.fire();
    assert.equal(runs, 1, 'a hidden tab must not poll');

    hidden = false;
    poller.setHidden(false);
    assert.equal(runs, 2, 'coming back runs once immediately to catch up');

    await clock.fire();
    assert.equal(runs, 3, 'and resumes the schedule');
    poller.stop();
});


test('stop() cancels the outstanding timer', async () => {
    const clock = fakeClock();
    let runs = 0;
    const poller = createPollScheduler({
        run: () => { runs += 1; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
    });

    poller.start();
    poller.stop();
    assert.equal(clock.scheduled, 0);
    await clock.fire();
    assert.equal(runs, 1, 'no further runs after stop()');
    assert.equal(poller.isRunning, false);
});


test('a rejected run does not wedge the poller', async () => {
    // If a failed request left inFlight true, the poller would go silent
    // forever — the worst failure mode, because the page looks live.
    const clock = fakeClock();
    let starts = 0;
    const errors = [];
    const poller = createPollScheduler({
        run: () => { starts += 1; return Promise.reject(new Error('boom')); },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
        onError: (error) => errors.push(error.message),
    });

    poller.start();
    await Promise.resolve();
    await Promise.resolve();

    assert.deepEqual(errors, ['boom'], 'the failure is surfaced, not swallowed');

    await clock.fire();
    assert.equal(starts, 2, 'polling continues after a failure');
    assert.equal(poller.isInFlight, false);
    poller.stop();
});


test('a synchronously throwing run does not wedge the poller either', async () => {
    const clock = fakeClock();
    let starts = 0;
    const poller = createPollScheduler({
        run: () => { starts += 1; throw new Error('sync boom'); },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
        onError: () => {},
    });

    poller.start();
    assert.equal(poller.isInFlight, false);
    await clock.fire();
    assert.equal(starts, 2);
    poller.stop();
});


test('refresh() honours the in-flight guard', async () => {
    const clock = fakeClock();
    const pending = deferred();
    let starts = 0;
    const poller = createPollScheduler({
        run: () => { starts += 1; return pending.promise; },
        intervalMs: 1000,
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
    });

    poller.start();
    poller.refresh();
    poller.refresh();
    assert.equal(starts, 1, 'a manual refresh must not stack either');
    pending.resolve();
    poller.stop();
});
