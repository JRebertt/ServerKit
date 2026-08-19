"""Probe-honesty integration tests across install environments (plan 75 §D).

Plan 74 fixed the production outage class where the panel's systemd unit PATH
has no sbin dir, so bare-name exec of ufw/nginx raised FileNotFoundError and
the panel reported a dishonest "No Firewall Installed". That fix was verified
on exactly one box (Ubuntu 22.04, root). These tests exist for the three
environment shapes that fix says nothing about:

1. **non-root install** — ``_needs_sudo()`` is True and commands resolve
   through sudo's secure_path; the sbin bug cannot reproduce there, so a fix
   verified only as root proves nothing about it.
2. **RHEL/Rocky** — different binary paths and package names (firewalld,
   rpm/dnf instead of ufw, dpkg/apt).
3. **capability-restricted** (unprivileged LXC shape; docker's default cap set
   already drops CAP_NET_ADMIN) — the firewall binary EXISTS and is on PATH,
   and the status probe still fails. Path resolution does nothing here; this
   is exactly the failure shape that produced a false "not installed".

They run WITHOUT mocks against the real binaries inside distro containers
(see scripts/test/probe-matrix.sh) and auto-detect which environment they
landed in (euid, PATH contents, which firewall binaries exist, effective
capabilities), skipping with explicit reasons when an invariant does not
hold. Skipped on Windows/macOS.

Scope is probe-layer smoke only: detect/status paths, no provisioning.
"""

import os
import platform
import subprocess
import sys

import pytest

# Skip entire module on non-Linux
pytestmark = pytest.mark.skipif(
    platform.system() != 'Linux',
    reason='Integration tests require Linux',
)

# Direct import (same technique as test_utils_system_integration.py) to load
# app/utils/system.py and app/services/firewall_service.py WITHOUT Flask deps.
# firewall_service.py imports only stdlib + app.utils.system, so registering
# the app/app.utils/app.services package skeleton in sys.modules first is
# enough for `from app.utils.system import ...` to resolve.
#
# Two shapes, deliberately:
# * Full backend suite (Flask installed): import the REAL modules. Registering
#   a second copy under 'app.services.firewall_service' here would replace the
#   sys.modules entry at collection time, and @patch('app.services.
#   firewall_service.*') in later tests would then land on THIS copy while the
#   test modules imported the real one during collection — mocks silently not
#   firing (the full-suite firewall red this module once caused).
# * Container legs (no Flask deps): shim, but load firewall_service under a
#   NON-COLLIDING name so a later real import can never find two copies.
import importlib
import types

_backend = os.path.join(os.path.dirname(__file__), os.pardir)


def _load_module(modname, *relpath):
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_backend, *relpath))
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


try:
    from app.utils import system as _system
    from app.services import firewall_service as _firewall
except ImportError:
    for _pkg in ('app', 'app.utils', 'app.services'):
        if _pkg not in sys.modules:
            sys.modules[_pkg] = types.ModuleType(_pkg)
    _system = _load_module('app.utils.system', 'app', 'utils', 'system.py')
    sys.modules['app'].utils = sys.modules['app.utils']
    sys.modules['app.utils'].system = _system
    _firewall = _load_module('_probe_env_firewall_service',
                             'app', 'services', 'firewall_service.py')

PackageManager = _system.PackageManager
resolve_command = _system.resolve_command
is_command_available = _system.is_command_available
run_privileged = _system.run_privileged
privileged_cmd = _system.privileged_cmd
_needs_sudo = _system._needs_sudo
FirewallService = _firewall.FirewallService


# Note on the suite-wide runtime sbin guard (conftest, plan 75 §B2): it stays
# ACTIVE for this module. These tests drive probes through run_privileged /
# privileged_cmd — the one-door helpers the guard trusts, since they absolutize
# argv[0] exactly when $PATH cannot. A raw subprocess call added here would
# still be judged by the guard, which is as it should be.


# ---------------------------------------------------------------------------
# Environment auto-detection
# ---------------------------------------------------------------------------

def _is_root():
    return getattr(os, 'geteuid', lambda: 0)() == 0


def _has_cap_net_admin():
    """True/False from /proc/self/status CapEff bit 12; None if unreadable.

    CAP_NET_ADMIN is what iptables/nft need to touch the ruleset. Docker's
    default capability set drops it, so a plain container is already the
    unprivileged-LXC shape: the ufw binary exists, resolves, and `ufw status`
    still fails.
    """
    try:
        with open('/proc/self/status') as fh:
            for line in fh:
                if line.startswith('CapEff:'):
                    return bool(int(line.split(':', 1)[1].strip(), 16) & 0x1000)
    except (OSError, ValueError):
        pass
    return None


#: The panel unit's PATH shape (plan 74): every sbin dir stripped.
SBINLESS_PATH = '/usr/local/bin:/usr/bin:/bin'

#: (display name, binary, status-probe argv, FirewallService check method)
FIREWALLS = [
    ('ufw', 'ufw', ['ufw', 'status'], '_check_ufw'),
    ('firewalld', 'firewall-cmd', ['firewall-cmd', '--state'], '_check_firewalld'),
]


def _firewall_or_skip(name, binary):
    """Skip with an explicit reason when this image lacks the firewall."""
    if resolve_command(binary) is None:
        pytest.skip(f'image has no {binary} — skipping {name} detection checks')


class TestEnvironmentReport:
    """Self-description: which environment invariants hold in THIS container."""

    def test_environment_facts(self):
        facts = {
            'euid': getattr(os, 'geteuid', lambda: '?')(),
            'is_root': _is_root(),
            'PATH': os.environ.get('PATH', ''),
            'path_has_sbin': any('sbin' in p for p in os.environ.get('PATH', '').split(':')),
            'CAP_NET_ADMIN': _has_cap_net_admin(),
            'ufw': resolve_command('ufw'),
            'firewall-cmd': resolve_command('firewall-cmd'),
            'nginx': resolve_command('nginx'),
            'sudo': resolve_command('sudo'),
            'needs_sudo': _needs_sudo(),
            'package_manager': PackageManager.detect(),
        }
        print('\n--- probe environment ---')
        for key, value in facts.items():
            print(f'  {key}: {value}')
        print('-------------------------')
        assert True


class TestSbinlessPathResolution:
    """The plan 74 shape: root (or not) with a PATH that has no sbin dir.

    Detection must never report "not installed" because $PATH lacked sbin,
    and status probes must never die with FileNotFoundError on a binary that
    exists under /usr/sbin.
    """

    def setup_method(self):
        PackageManager.reset_cache()

    @pytest.mark.parametrize('name,binary,probe,check', FIREWALLS)
    def test_resolve_command_finds_binary_without_sbin(self, monkeypatch,
                                                       name, binary, probe, check):
        _firewall_or_skip(name, binary)
        monkeypatch.setenv('PATH', SBINLESS_PATH)
        import shutil
        resolved = resolve_command(binary)
        assert resolved is not None and os.path.isabs(resolved), (
            f'{binary} exists on this image but resolve_command() could not '
            f'find it once $PATH lost its sbin dirs — the plan 74 outage class')
        assert os.path.exists(resolved)
        if shutil.which(binary) is None:
            # sbin-resident binary (ufw, nginx on Debian): the sbin fallback
            # in resolve_command is what saved this exec — the plan 74 shape.
            assert 'sbin' in resolved, (
                f'{binary} is unreachable via $PATH but resolve_command '
                f'returned non-sbin path {resolved!r} — unexpected')
        else:
            # usrmerge distro (Rocky ships firewall-cmd in /usr/bin): the
            # binary never needed the fallback; resolution must still agree
            # with $PATH rather than invent a different location.
            print(f'\n{binary} resolves under {SBINLESS_PATH} directly '
                  f'({resolved}) — sbin fallback not needed on this image')

    @pytest.mark.parametrize('name,binary,probe,check', FIREWALLS)
    def test_detection_reports_installed_with_sbinless_path(self, monkeypatch,
                                                            name, binary, probe, check):
        _firewall_or_skip(name, binary)
        monkeypatch.setenv('PATH', SBINLESS_PATH)
        status = getattr(FirewallService, check)()
        assert status['installed'] is True, (
            f'{name} IS installed on this image ({binary} at '
            f'{resolve_command(binary)}) but FirewallService.{check}() '
            f'reported installed=False under an sbin-less PATH — the exact '
            f'"No Firewall Installed" lie from plan 74')

    @pytest.mark.parametrize('name,binary,probe,check', FIREWALLS)
    def test_status_probe_exec_never_raises_filenotfound(self, monkeypatch,
                                                         name, binary, probe, check):
        """A failed probe (rc != 0) is fine; FileNotFoundError is not."""
        _firewall_or_skip(name, binary)
        monkeypatch.setenv('PATH', SBINLESS_PATH)
        try:
            result = run_privileged(probe)
        except FileNotFoundError as exc:
            pytest.fail(
                f'{probe[0]!r} exists on this image but exec raised '
                f'FileNotFoundError under an sbin-less PATH: {exc}')
        print(f'\n{name} probe rc={result.returncode} '
              f'(non-zero is acceptable here — only FileNotFoundError is a bug)')


class TestNonRootSudoRouting:
    """The non-root install shape: _needs_sudo() is True and every probe
    routes through sudo (whose secure_path resolves sbin on its own)."""

    @pytest.mark.skipif(_is_root(), reason='running as root — nothing routes through sudo')
    def test_needs_sudo_true(self):
        if resolve_command('sudo') is None:
            pytest.skip('sudo not installed on this image — _needs_sudo() is False by design')
        assert _needs_sudo() is True

    @pytest.mark.skipif(_is_root(), reason='running as root — nothing routes through sudo')
    def test_privileged_cmd_prepends_sudo(self):
        if not _needs_sudo():
            pytest.skip('_needs_sudo() is False (no sudo installed)')
        cmd = privileged_cmd(['id', '-u'])
        assert cmd[:2] == ['sudo', '-n'], (
            f'non-root probes must route through sudo -n, got {cmd!r}')

    @pytest.mark.skipif(_is_root(), reason='running as root — nothing routes through sudo')
    def test_run_privileged_actually_escalates(self):
        if not _needs_sudo():
            pytest.skip('_needs_sudo() is False (no sudo installed)')
        probe = subprocess.run(['sudo', '-n', 'true'], capture_output=True)
        if probe.returncode != 0:
            pytest.skip('sudo -n requires a password here — '
                        'skipping live escalation check')
        result = run_privileged(['id', '-u'])
        assert result.returncode == 0
        assert result.stdout.strip() == '0', (
            'run_privileged([id -u]) must reach uid 0 through sudo')

    @pytest.mark.skipif(_is_root(), reason='running as root — nothing routes through sudo')
    @pytest.mark.parametrize('name,binary,probe,check', FIREWALLS)
    def test_detection_paths_do_not_raise(self, name, binary, probe, check):
        _firewall_or_skip(name, binary)
        status = getattr(FirewallService, check)()  # must not raise
        assert status['installed'] is True


class TestCapabilityRestricted:
    """The unprivileged-LXC shape: ufw EXISTS and resolves, but the status
    probe fails on dropped CAP_NET_ADMIN. Path resolution does nothing here —
    this is where "failed probe" must not become "not installed", and must
    not become a fabricated "inactive" either."""

    def _skip_unless_restricted_ufw(self):
        _firewall_or_skip('ufw', 'ufw')
        cap = _has_cap_net_admin()
        if cap is True:
            pytest.skip('CAP_NET_ADMIN present — '
                        'not a capability-restricted environment')

    def test_ufw_status_probe_fails_without_net_admin(self):
        """Establish the precondition: the status probe genuinely fails."""
        self._skip_unless_restricted_ufw()
        result = run_privileged(['ufw', 'status'])
        if result.returncode == 0:
            pytest.skip('ufw status succeeded — environment is not '
                        'capability-restricted in practice')
        print(f'\nufw status rc={result.returncode} '
              f'stderr={(result.stderr or "").strip()[:120]}')

    def test_failed_probe_is_not_silent_not_installed(self):
        """installed reflects binary presence, never probe success."""
        self._skip_unless_restricted_ufw()
        status = FirewallService._check_ufw()
        assert status['installed'] is True, (
            'ufw is installed on this image but a failed status probe '
            'unsaid it — the false "No Firewall Installed" shape')

    def test_failed_probe_is_not_fabricated_inactive(self):
        """A failed status probe must surface as an explicit error/unknown
        signal — NOT a fabricated active=False indistinguishable from a
        cleanly inactive firewall."""
        self._skip_unless_restricted_ufw()
        result = run_privileged(['ufw', 'status'])
        if result.returncode == 0:
            pytest.skip('ufw status succeeded — environment is not '
                        'capability-restricted in practice')
        status = FirewallService._check_ufw()
        honest = status.get('error') is not None or status.get('active') is None
        assert honest, (
            f'DISHONEST PROBE (plan 75 §D): `ufw status` failed '
            f'(rc={result.returncode}, dropped CAP_NET_ADMIN) but '
            f'FirewallService._check_ufw() returned {status!r} — active=False '
            f'with no error signal is a fabricated "inactive". The caller '
            f'cannot distinguish "probe failed" from "firewall off". '
            f'See backend/app/services/firewall_service.py _check_ufw().')
