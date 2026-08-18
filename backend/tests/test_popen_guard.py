"""The runtime sbin guard must actually fire (plan 75 §B2).

`popen_guard.GuardedPopen` is installed autouse by conftest; these tests are
its mutation check — the fixture existing is not the same as the trap working.
They prove: the wrapper is live during tests, a bare-name sbin-only exec is
refused loudly (loudly = ``BaseException``, so a blanket ``except Exception``
— the exact handler this bug class hides behind — cannot swallow it), and
everything that is NOT the bug class passes through untouched.
"""

import os
import subprocess
from unittest.mock import patch

import pytest

import popen_guard
from popen_guard import GuardedPopen, SbinPathError, offending_head

pytestmark = pytest.mark.skipif(os.name != 'posix',
                                reason='sbin semantics are POSIX-only')

#: A PATH shaped like the panel unit's: no sbin anywhere.
NO_SBIN_ENV = {'PATH': '/usr/local/bin:/usr/bin:/bin'}


def _which_only_in_sbin(head, path=None):
    """``shutil.which`` where *head* exists, but only under an sbin dir."""
    if path is not None and 'sbin' not in path:
        return None  # sanitized PATH: not found
    return f'/usr/sbin/{head}'


# --------------------------------------------------------------------------- #
# The fixture is live
# --------------------------------------------------------------------------- #

def test_the_guard_is_installed_for_the_whole_suite():
    """Autouse is the point — a guard a test must remember to request is a
    guard that protects nothing."""
    assert subprocess.Popen is GuardedPopen


# --------------------------------------------------------------------------- #
# offending_head: precisely the bug class, nothing else
# --------------------------------------------------------------------------- #

def test_bare_name_resolving_only_through_sbin_offends():
    with patch('popen_guard.shutil.which', side_effect=_which_only_in_sbin):
        assert offending_head(['ufw', 'status'], env=NO_SBIN_ENV) == 'ufw'


def test_bare_name_resolving_without_sbin_is_fine():
    with patch('popen_guard.shutil.which', return_value='/usr/bin/git'):
        assert offending_head(['git', 'status'], env=NO_SBIN_ENV) is None


def test_a_binary_absent_on_this_machine_is_not_a_guard_violation():
    """Missing here means FileNotFoundError here — the honest failure suites
    already exercise. The guard judges PATH shape, not machine contents."""
    with patch('popen_guard.shutil.which', return_value=None):
        assert offending_head(['definitely-not-installed', '-t'],
                              env=NO_SBIN_ENV) is None


def test_absolute_paths_are_not_path_searches():
    with patch('popen_guard.shutil.which', side_effect=AssertionError(
            'which() must not even be consulted for an absolute path')):
        assert offending_head(['/usr/sbin/ufw', 'status']) is None


def test_explicit_relative_paths_are_not_path_searches():
    assert offending_head(['./sbin/ufw', 'status']) is None


def test_string_form_argv_is_left_alone():
    """shell=True is a deliberate, separate decision (one site, a user hook)."""
    assert offending_head('ufw status') is None


def test_empty_argv_is_left_alone():
    assert offending_head([]) is None


def test_sanitized_path_drops_every_sbin_dir():
    env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'}
    assert popen_guard.sanitized_path(env) == '/usr/local/bin:/usr/bin:/bin'


# --------------------------------------------------------------------------- #
# The trap fires through the real subprocess entry points
# --------------------------------------------------------------------------- #

def test_guarded_popen_refuses_a_bare_sbin_only_exec():
    with patch('popen_guard.shutil.which', side_effect=_which_only_in_sbin):
        with pytest.raises(SbinPathError) as excinfo:
            GuardedPopen(['ufw', 'status'])
    message = str(excinfo.value)
    assert 'ufw' in message
    assert 'run_privileged' in message
    assert __file__ in message  # the callsite is named


def test_subprocess_run_funnels_through_the_guard():
    """run/call/check_output/check_call all land on Popen — patch the module
    attribute once and every entry point is covered."""
    with patch('popen_guard.shutil.which', side_effect=_which_only_in_sbin):
        with pytest.raises(SbinPathError):
            subprocess.run(['nginx', '-t'])
        with pytest.raises(SbinPathError):
            subprocess.check_output(['iptables', '-L'])


def test_the_refusal_survives_a_blanket_except():
    """The failure mode this guard exists for: `except Exception` turning an
    exec failure into a false fact. SbinPathError is a BaseException so the
    trap cannot be eaten by the handlers it hunts."""
    caught = None
    with patch('popen_guard.shutil.which', side_effect=_which_only_in_sbin):
        try:
            subprocess.run(['ufw', 'status'])
        except Exception as exc:  # noqa: BLE001 — the dishonest handler shape
            caught = exc
        except SbinPathError:
            caught = 'guard'
    assert caught == 'guard'


# --------------------------------------------------------------------------- #
# Passthrough: real execs that are not the bug class still work
# --------------------------------------------------------------------------- #

def test_a_real_resolvable_exec_still_runs():
    """The guard wraps, it does not block: /bin/sh resolves without sbin and
    must exec for real."""
    proc = subprocess.run(['sh', '-c', 'exit 0'])
    assert proc.returncode == 0


def test_a_real_missing_binary_still_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        subprocess.run(['definitely-not-installed-anywhere-75', '-t'])
