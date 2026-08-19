"""Firewall detection: an installed firewall must not report as absent.

Measured on a live panel: `ufw` was installed and `dpkg -l` said `ii`, the
install notification said "UFW installed successfully", and /security/firewall
still rendered "No Firewall Installed". fail2ban worked perfectly on the same
box, which is the clue — `fail2ban-client` lives in /usr/bin, `ufw` in
/usr/sbin, and the panel's systemd unit ships:

    Environment="PATH=/opt/serverkit/venv/bin:/usr/local/bin:/usr/bin:/bin"

So subprocess could not exec `ufw` by bare name and raised FileNotFoundError.
The service had already computed installed=True correctly; a single try/except
around the whole body then threw that away and returned installed=False.

Two independent defects, two independent guards:
  1. a command outside $PATH must still be runnable (resolve_command)
  2. a failed status probe must never unsay "installed"
"""

import subprocess
from unittest.mock import patch

import pytest

from app.services.firewall_service import FirewallService
from app.utils.system import is_command_available, privileged_cmd, resolve_command


# --------------------------------------------------------------------------- #
# 1. Commands outside $PATH
# --------------------------------------------------------------------------- #

class TestResolveCommand:

    @patch('app.utils.system.shutil.which', return_value='/usr/bin/nginx')
    def test_path_hit_is_used_as_is(self, _which):
        assert resolve_command('nginx') == '/usr/bin/nginx'

    @patch('app.utils.system.os.path.exists')
    @patch('app.utils.system.shutil.which', return_value=None)
    def test_sbin_is_searched_when_path_misses(self, _which, exists):
        """The exact live failure: ufw in /usr/sbin, not on the unit's PATH."""
        exists.side_effect = lambda p: p == '/usr/sbin/ufw'

        assert resolve_command('ufw') == '/usr/sbin/ufw'
        assert is_command_available('ufw') is True

    @patch('app.utils.system.os.path.exists', return_value=False)
    @patch('app.utils.system.shutil.which', return_value=None)
    def test_genuinely_absent_command_resolves_to_none(self, _which, _exists):
        assert resolve_command('nonexistent') is None
        assert is_command_available('nonexistent') is False

    @patch('app.utils.system.os.path.exists', return_value=False)
    def test_absolute_path_that_does_not_exist_is_not_invented(self, _exists):
        assert resolve_command('/opt/nope/tool') is None


class TestPrivilegedCmdResolution:

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    @patch('app.utils.system.os.path.exists')
    @patch('app.utils.system.shutil.which', return_value=None)
    def test_unresolvable_command_is_given_an_absolute_path(self, _which, exists,
                                                            _euid):
        """Without this, subprocess raises FileNotFoundError on argv[0]."""
        exists.side_effect = lambda p: p == '/usr/sbin/ufw'

        assert privileged_cmd(['ufw', 'status']) == ['/usr/sbin/ufw', 'status']

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/systemctl')
    def test_resolvable_command_is_passed_through_untouched(self, _which, _euid):
        """A working PATH must not have its argv rewritten underneath callers."""
        assert privileged_cmd(['systemctl', 'restart', 'nginx']) == [
            'systemctl', 'restart', 'nginx'
        ]

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    @patch('app.utils.system.os.path.exists', return_value=False)
    @patch('app.utils.system.shutil.which', return_value=None)
    def test_unfindable_command_is_left_alone(self, _which, _exists, _euid):
        """Nothing to resolve to — do not fabricate a path."""
        assert privileged_cmd(['ghost', '--x']) == ['ghost', '--x']

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    @patch('app.utils.system.os.path.exists')
    @patch('app.utils.system.shutil.which')
    def test_resolution_composes_with_sudo(self, which, exists, _euid):
        # sudo itself must stay resolvable, or _needs_sudo() short-circuits and
        # the test would pass for the wrong reason.
        which.side_effect = lambda c: '/usr/bin/sudo' if c == 'sudo' else None
        exists.side_effect = lambda p: p == '/usr/sbin/ufw'

        assert privileged_cmd(['ufw', 'status']) == [
            'sudo', '-n', '/usr/sbin/ufw', 'status'
        ]


# --------------------------------------------------------------------------- #
# 2. A failed probe must not unsay "installed"
# --------------------------------------------------------------------------- #

class TestProbeFailureIsolation:

    @patch('app.services.firewall_service.run_privileged')
    @patch('app.services.firewall_service.is_command_available', return_value=True)
    @patch('app.services.firewall_service.PackageManager.is_installed', return_value=True)
    def test_status_probe_raising_does_not_hide_the_install(self, _pkg, _avail, run):
        """The live bug, reproduced exactly."""
        run.side_effect = FileNotFoundError(2, 'No such file or directory', 'ufw')

        ufw = FirewallService._check_ufw()

        assert ufw['installed'] is True     # was False — the whole bug
        assert ufw['active'] is None        # genuinely unknown, reported as unknown
        assert ufw['error']                 # ...with the failure carried alongside

    @patch('app.services.firewall_service.run_privileged')
    @patch('app.services.firewall_service.is_command_available')
    @patch('app.services.firewall_service.PackageManager.is_installed')
    def test_page_would_render_the_firewall_not_the_empty_state(self, pkg, avail, run):
        """`any_installed` is what FirewallTab.jsx gates the empty state on.

        Only ufw is present here — the live box has no firewalld, and saying
        "everything is installed" would let the assertion pass for free.
        """
        pkg.side_effect = lambda name: name == 'ufw'
        avail.side_effect = lambda name: name == 'ufw'
        run.side_effect = FileNotFoundError(2, 'No such file or directory', 'ufw')

        status = FirewallService.get_status()

        assert status['any_installed'] is True
        assert status['active_firewall'] == 'ufw'
        assert status['firewalld']['installed'] is False

    @patch('app.services.firewall_service.run_privileged')
    @patch('app.services.firewall_service.is_command_available', return_value=True)
    @patch('app.services.firewall_service.PackageManager.is_installed', return_value=True)
    def test_installed_but_inactive_is_reported_faithfully(self, _pkg, _avail, run):
        """builditdesign's real state: installed, `Status: inactive`."""
        run.return_value = subprocess.CompletedProcess([], 0, stdout='Status: inactive\n',
                                                       stderr='')

        status = FirewallService.get_status()

        assert status['any_installed'] is True
        assert status['any_active'] is False
        assert status['ufw'] == {'installed': True, 'active': False, 'error': None}

    @patch('app.services.firewall_service.run_privileged')
    @patch('app.services.firewall_service.is_command_available', return_value=True)
    @patch('app.services.firewall_service.PackageManager.is_installed', return_value=True)
    def test_active_firewall_is_detected(self, _pkg, _avail, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout='Status: active\n',
                                                       stderr='')

        status = FirewallService.get_status()

        assert status['any_active'] is True
        assert status['ufw']['active'] is True

    @patch('app.services.firewall_service.is_command_available', return_value=False)
    @patch('app.services.firewall_service.PackageManager.is_installed', return_value=False)
    def test_genuinely_absent_firewall_still_reports_absent(self, _pkg, _avail):
        """The guard must not make everything look installed."""
        status = FirewallService.get_status()

        assert status['any_installed'] is False
        assert status['active_firewall'] is None

    @patch('app.services.firewall_service.run_privileged')
    @patch('app.services.firewall_service.is_command_available', return_value=True)
    @patch('app.services.firewall_service.PackageManager.is_installed', return_value=True)
    def test_firewalld_probe_failure_is_isolated_too(self, _pkg, _avail, run):
        run.side_effect = FileNotFoundError(2, 'No such file or directory', 'firewall-cmd')

        firewalld = FirewallService._check_firewalld()

        assert firewalld['installed'] is True
        assert firewalld['running'] is None   # could not check, never a fabricated "off"
        assert firewalld['default_zone'] is None
        assert firewalld['error']

    @pytest.mark.parametrize('failure', [
        subprocess.TimeoutExpired(cmd=['ufw', 'status'], timeout=30),
        PermissionError(13, 'Permission denied'),
        OSError(8, 'Exec format error'),
    ])
    @patch('app.services.firewall_service.run_privileged')
    @patch('app.services.firewall_service.is_command_available', return_value=True)
    @patch('app.services.firewall_service.PackageManager.is_installed', return_value=True)
    def test_any_probe_failure_keeps_installed_true(self, _pkg, _avail, run, failure):
        """A sudo timeout or permission denial is not evidence of absence."""
        run.side_effect = failure

        assert FirewallService._check_ufw()['installed'] is True
