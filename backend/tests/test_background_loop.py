"""Plan 77 E5 — BackgroundLoop: Event-stopped, idempotent, error-proof."""
import threading
import time

from app.utils.background_loop import BackgroundLoop


def test_ticks_and_stops_promptly():
    ticks = []
    loop = BackgroundLoop('t', 0.01, lambda: ticks.append(1))
    assert loop.start() is True
    time.sleep(0.15)
    assert ticks, 'loop never ticked'
    loop.stop(join_timeout=1)
    assert not loop.running
    n = len(ticks)
    time.sleep(0.05)
    assert len(ticks) == n, 'loop kept ticking after stop()'


def test_start_is_idempotent():
    started = threading.Event()
    loop = BackgroundLoop('t2', 0.01, started.set)
    assert loop.start() is True
    assert loop.start() is False  # already running
    started.wait(1)
    loop.stop(join_timeout=1)


def test_tick_errors_do_not_kill_the_loop():
    ticks = []

    def tick():
        ticks.append(1)
        raise RuntimeError('boom')

    loop = BackgroundLoop('t3', 0.01, tick)
    loop.start()
    time.sleep(0.1)
    loop.stop(join_timeout=1)
    assert len(ticks) >= 2, 'loop died on first tick error'


def test_run_while_predicate_ends_loop():
    alive = {'v': True}
    ticks = []
    loop = BackgroundLoop('t4', 0.01, lambda: ticks.append(1),
                          run_while=lambda: alive['v'])
    loop.start()
    time.sleep(0.05)
    alive['v'] = False
    time.sleep(0.1)
    assert not loop.running
    loop.stop()


def test_restart_after_natural_exit():
    """A loop whose run_while ended can be started again (the sockets
    broadcaster pattern: last subscriber leaves, a new one arrives)."""
    gate = {'v': True}
    ticks = []
    loop = BackgroundLoop('t5', 0.01, lambda: ticks.append(1),
                          run_while=lambda: gate['v'])
    loop.start()
    time.sleep(0.05)
    gate['v'] = False
    time.sleep(0.1)
    assert not loop.running
    gate['v'] = True
    assert loop.start() is True
    time.sleep(0.05)
    assert loop.running
    loop.stop(join_timeout=1)
