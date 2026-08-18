"""Runtime layer of the sbin guard (plan 75 §B2).

The static scan in ``test_sbin_command_guard.py`` only sees literal argv lists —
164 of the 288 raw ``subprocess.*`` sites in ``backend/app``. The other 43%
(variables, f-strings, concatenation) are opaque to AST, and they are where a
bare-name exec of an sbin-resident binary can still hide.

This module closes that gap at runtime, during tests. ``GuardedPopen`` wraps
``subprocess.Popen`` — the one primitive ``run``/``call``/``check_output``/
``check_call`` all funnel through — and inspects the *actual* argv at call
time. A bare-name head that resolves under the current ``$PATH`` but NOT under
a ``$PATH`` with the sbin dirs removed fails loudly:

    works in dev (PATH has sbin), dies under the panel's systemd unit
    (PATH has none) — plan 74's outage class, caught before it ships.

Its coverage is exactly "whatever the suite exercises" — honest, measurable,
and improving for free as tests are added. A call the suite never makes is a
call no test can vouch for either way; this guard makes no claim about it.

Deliberate non-failures:

* a head that resolves under NEITHER PATH is simply absent on this machine.
  The real ``Popen`` will raise ``FileNotFoundError`` — the honest result, and
  one probe-honesty suites exercise deliberately. The guard does not turn a
  missing-on-this-box binary into a guard violation.
* string-form argv (``shell=True``) and heads containing a path separator are
  not PATH searches and are left alone.
"""

import os
import shutil
import subprocess
import traceback


class SbinPathError(BaseException):
    """A bare-name exec that only resolves through an sbin dir.

    ``BaseException`` on purpose: the bug class this catches ships BECAUSE a
    blanket ``except Exception`` converts ``FileNotFoundError`` into a false
    fact ("No Firewall Installed"). A plain ``AssertionError`` raised here
    would be swallowed by exactly the handlers it exists to catch.
    """


def sanitized_path(env=None):
    """The current ``$PATH`` with every sbin dir removed — the shape of the
    panel unit's ``Environment="PATH=..."`` that caused the plan 74 outage."""
    env = os.environ if env is None else env
    parts = env.get('PATH', '').split(os.pathsep)
    kept = [p for p in parts
            if p and os.path.basename(p.rstrip('/\\')) not in ('sbin',)]
    return os.pathsep.join(kept)


def offending_head(argv, env=None):
    """argv[0] if this argv is a bare-name exec that only resolves through an
    sbin dir, else ``None``. Pure and env-injectable so it can be tested
    without spawning anything."""
    if os.name != 'posix' or isinstance(argv, (str, bytes)) or not argv:
        return None
    head = argv[0]
    if not isinstance(head, str) or os.path.sep in head:
        return None  # absolute, or explicitly relative — not a PATH search
    if shutil.which(head, path=sanitized_path(env)):
        return None  # resolves without sbin: equally safe under the unit
    if not shutil.which(head):
        return None  # absent on this machine — FileNotFoundError is honest
    return head


def _callsite():
    """First stack frame outside this module and subprocess internals."""
    for frame in reversed(traceback.extract_stack()):
        base = os.path.basename(frame.filename)
        if base != 'popen_guard.py' and base != 'subprocess.py':
            return f'{frame.filename}:{frame.lineno}'
    return '<unknown>'


def _routed_through_helper():
    """True when the exec came through the one-door helper module.

    ``run_privileged``/``run_unprivileged`` absolutize argv[0] exactly when
    $PATH cannot — under the panel unit's sbin-less PATH the very call this
    guard is looking at resolves to an absolute path. Firing on their
    pass-through in an sbin-ful environment (every real-exec integration
    test) would condemn the door itself; the guard hunts *bypasses* of it.
    """
    for frame in traceback.extract_stack():
        if frame.filename.replace('\\', '/').endswith('app/utils/system.py'):
            return True
    return False


def guard_argv(argv):
    """Raise :class:`SbinPathError` when *argv* is a bare-name sbin-only exec.

    One door for the check itself. ``GuardedPopen`` calls it before a real
    exec; ``tests/subprocess_stub.py`` calls it before returning a *scripted*
    result, so stubbing subprocess does not punch a hole in this guard — a
    test that fakes ``subprocess.run`` still cannot smuggle a bare-name
    ``ufw`` past it. That matters more than it sounds: 44 of the suite's
    subprocess stubs mean 44 execs the runtime guard never sees.
    """
    head = offending_head(argv)
    if head is None or _routed_through_helper():
        return
    raise SbinPathError(
        f'{head!r} is exec\'d by bare name but only resolves through '
        f'an sbin dir. The panel\'s systemd unit ships a PATH with no '
        f'sbin, so this call raises FileNotFoundError in production '
        f'while passing every dev run — plan 74\'s outage class.\n'
        f'  called from: {_callsite()}\n'
        f'Use run_privileged() (or run_unprivileged() when no root is '
        f'needed); both resolve argv[0] to an absolute path when '
        f'$PATH cannot.'
    )


class GuardedPopen(subprocess.Popen):
    """``subprocess.Popen`` that refuses bare-name sbin-only execs (test-time)."""

    def __init__(self, args, *a, **kw):
        guard_argv(args)
        super().__init__(args, *a, **kw)
