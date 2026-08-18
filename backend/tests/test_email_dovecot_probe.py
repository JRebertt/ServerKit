"""DovecotService.get_status() must never turn a failed probe into a 500.

``ServiceControl.is_active`` deliberately raises ``FileNotFoundError`` when
systemctl is absent (see the docstring in ``app/utils/system.py``: a host
without systemd is "could not check", not "not running"). ``get_status`` called
it unguarded, so ``GET /api/v1/email/status`` crashed on every non-systemd host
-- and the page's catch renders that as "Mail server not installed" with an
Install button, on a box already running Dovecot.

Both wrappers also carry ``timeout=PROBE_TIMEOUT``, so a systemd that stops
answering raises ``subprocess.TimeoutExpired`` straight through. That is the
same failure with a different exception type, which is why the guard catches
``subprocess.SubprocessError`` too rather than just the missing binary.

The unknown case reports ``None`` -- neither True nor False -- because
fabricating ``running=False`` here is exactly the probe dishonesty the plan-75
round removed from the firewall and SSL services.
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

_DOVECOT = (Path(__file__).resolve().parent.parent
            / 'app' / 'plugins' / 'serverkit-email' / 'dovecot_service.py')


def _load():
    """Import the extension's dovecot_service by path.

    The plugin directory is hyphenated, so it is not importable as a package
    name; the loader the panel uses does the same thing at runtime.
    """
    if not _DOVECOT.exists():  # pragma: no cover - live copy is gitignored
        pytest.skip('serverkit-email live copy not materialised')
    spec = importlib.util.spec_from_file_location('_sk_dovecot_probe', _DOVECOT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Raiser:
    """Stand-in ServiceControl whose probes raise *exc*."""

    def __init__(self, exc):
        self._exc = exc

    def is_active(self, service):
        raise self._exc

    def is_enabled(self, service):
        raise self._exc


@pytest.fixture
def dovecot(monkeypatch):
    module = _load()
    # Installed, so get_status reaches the probes at all.
    monkeypatch.setattr(module, 'is_command_available', lambda cmd: True)
    return module


@pytest.mark.parametrize('exc', [
    FileNotFoundError('systemctl'),
    subprocess.TimeoutExpired(cmd=['systemctl', 'is-active', 'dovecot'], timeout=30),
])
def test_unavailable_probe_reports_unknown_not_stopped(dovecot, monkeypatch, exc):
    monkeypatch.setattr(dovecot, 'ServiceControl', _Raiser(exc))

    status = dovecot.DovecotService.get_status()

    assert status['installed'] is True
    # None, not False: the probe could not run, so "stopped" would be a lie.
    assert status['running'] is None
    assert status['enabled'] is None


def test_enabled_probe_failure_alone_is_also_survivable(dovecot, monkeypatch):
    """is_enabled swallows FileNotFoundError itself but not TimeoutExpired.

    Guarding only the is_active line -- the literal review comment -- would
    leave this second escape route open on the very next statement.
    """
    class _EnabledTimesOut:
        def is_active(self, service):
            return True

        def is_enabled(self, service):
            raise subprocess.TimeoutExpired(cmd=['systemctl'], timeout=30)

    monkeypatch.setattr(dovecot, 'ServiceControl', _EnabledTimesOut())

    status = dovecot.DovecotService.get_status()

    assert status['running'] is None
    assert status['enabled'] is None


def test_working_probe_still_reports_booleans(dovecot, monkeypatch):
    """The guard must not blur the healthy path into the unknown one."""
    class _Healthy:
        def is_active(self, service):
            return True

        def is_enabled(self, service):
            return False

    monkeypatch.setattr(dovecot, 'ServiceControl', _Healthy())

    status = dovecot.DovecotService.get_status()

    assert status['running'] is True
    assert status['enabled'] is False
