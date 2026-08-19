"""BackgroundLoop — the one shape for process-lifetime polling loops (plan 77 E5).

The 13 LIFECYCLE_PROCESS_LOOP threads each hand-rolled the same dance: a
bool flag (or Event), a daemon Thread, a try/except around the tick (some
reporting errors via ``print()`` — unreadable in prod), a sleep. This helper
owns that dance once:

- ``threading.Event`` stop — ``stop()`` interrupts the wait immediately
  instead of finishing a sleep;
- idempotent ``start()``/``stop()`` guarded by a lock (safe under
  async_mode='threading' where two subscribers race to start a broadcaster);
- optional Flask app context per tick;
- errors go to a real logger and never kill the loop;
- ``run_while`` predicate for loops that should end when their audience
  leaves (e.g. "while there are subscribers").

The single ``threading.Thread`` call site below is registered in
``app/jobs/thread_ownership.py`` — loops built on this helper are covered by
that one entry instead of one registry row per loop.
"""

import logging
import threading

logger = logging.getLogger(__name__)


class BackgroundLoop:
    def __init__(self, name, interval_s, tick, *, app=None, run_while=None):
        """
        Args:
            name: human-readable loop name (thread name + log prefix).
            interval_s: seconds between ticks (waited on the stop Event, so
                stop() is immediate).
            tick: zero-arg callable executed each cycle.
            app: optional Flask app; when given, each tick runs inside
                ``app.app_context()``.
            run_while: optional zero-arg predicate; the loop exits when it
                returns falsy (checked before each tick).
        """
        self.name = name
        self.interval_s = interval_s
        self._tick = tick
        self._app = app
        self._run_while = run_while
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, app=None):
        """Start the loop thread. Idempotent — a live loop is left alone.
        Returns True when a new thread was started."""
        with self._lock:
            if self.running:
                return False
            if app is not None:
                self._app = app
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name=f'loop:{self.name}', daemon=True)
            self._thread.start()
            return True

    def stop(self, join_timeout=None):
        """Signal the loop to exit. Idempotent. Optionally join."""
        self._stop.set()
        thread = self._thread
        if join_timeout is not None and thread is not None:
            thread.join(timeout=join_timeout)

    def _run(self):
        while not self._stop.is_set():
            if self._run_while is not None:
                try:
                    if not self._run_while():
                        break
                except Exception:
                    logger.exception('[%s] run_while predicate raised; stopping loop', self.name)
                    break
            try:
                if self._app is not None:
                    with self._app.app_context():
                        self._tick()
                else:
                    self._tick()
            except Exception:
                logger.exception('[%s] tick failed; continuing', self.name)
            # Event-based wait: stop() interrupts immediately.
            self._stop.wait(self.interval_s)
