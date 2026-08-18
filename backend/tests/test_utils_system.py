"""Tests for backend/app/utils/system.py.

Uses a direct import path so the test can run without Flask dependencies
(system.py itself has no Flask imports).
"""

import importlib
import os
import subprocess
import sys
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

# Import system.py directly to avoid triggering app/__init__.py (Flask deps).
# We register stub entries for 'app' and 'app.utils' so that
# unittest.mock.patch('app.utils.system.X') can resolve the path without
# importing the real app package (which needs Flask).
import types

_backend = os.path.join(os.path.dirname(__file__), os.pardir)
_mod_path = os.path.join(_backend, 'app', 'utils', 'system.py')
_spec = importlib.util.spec_from_file_location('app.utils.system', _mod_path)
_module = importlib.util.module_from_spec(_spec)

# Stub parent packages so patch() resolution never hits Flask imports.
if 'app' not in sys.modules:
    sys.modules['app'] = types.ModuleType('app')
if 'app.utils' not in sys.modules:
    _utils = types.ModuleType('app.utils')
    sys.modules['app.utils'] = _utils
    sys.modules['app'].utils = _utils  # type: ignore[attr-defined]

sys.modules['app.utils.system'] = _module
sys.modules['app.utils'].system = _module  # type: ignore[attr-defined]
_spec.loader.exec_module(_module)

run_privileged = _module.run_privileged
privileged_cmd = _module.privileged_cmd
is_command_available = _module.is_command_available
PackageManager = _module.PackageManager
ServiceControl = _module.ServiceControl
write_privileged_file = _module.write_privileged_file
unit_is_active = _module.unit_is_active
run_checked = _module.run_checked


# ---------------------------------------------------------------------------
# run_privileged
# ---------------------------------------------------------------------------
class TestRunPrivileged:
    """Tests for :func:`run_privileged`."""

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_prepends_sudo_when_not_root(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged(['systemctl', 'restart', 'nginx'])
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'restart', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_skips_sudo_when_root(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged(['systemctl', 'restart', 'nginx'])
        mock_run.assert_called_once_with(
            ['systemctl', 'restart', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_no_double_sudo(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        # An explicitly-sudo command is passed through untouched (no `sudo sudo`,
        # and no second-guessing a caller that built its own invocation).
        run_privileged(['sudo', 'systemctl', 'restart', 'nginx'])
        mock_run.assert_called_once_with(
            ['sudo', 'systemctl', 'restart', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_defaults_applied(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged(['ls'])
        _, kwargs = mock_run.call_args
        assert kwargs['capture_output'] is True
        assert kwargs['text'] is True

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_kwargs_passed_through(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged(['apt', 'install', '-y', 'foo'], timeout=120, check=True)
        _, kwargs = mock_run.call_args
        assert kwargs['timeout'] == 120
        assert kwargs['check'] is True

    # Output is captured and no terminal is attached, so a command that never
    # returns would hang its caller silently and forever. Every call gets a
    # ceiling unless one is named explicitly.
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_default_timeout_applied(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged(['systemctl', 'restart', 'nginx'])
        _, kwargs = mock_run.call_args
        assert kwargs['timeout'] == _module.DEFAULT_PRIVILEGED_TIMEOUT

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_timeout_can_be_disabled_explicitly(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged(['tail', '-f', '/var/log/syslog'], timeout=None)
        _, kwargs = mock_run.call_args
        assert kwargs['timeout'] is None

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_caller_can_override_defaults(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged(['ls'], capture_output=False)
        _, kwargs = mock_run.call_args
        assert kwargs['capture_output'] is False

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_string_command_gets_sudo(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged('systemctl restart nginx')
        args, _ = mock_run.call_args
        assert args[0] == 'sudo -n systemctl restart nginx'

    # Regression: bare `sudo` blocks forever on a password prompt when the panel
    # runs non-root with output captured — nothing can type the password and
    # nothing can see it. This hung backend startup (metadata guard iptables
    # probe). Every generated sudo invocation must be non-interactive.
    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_sudo_is_always_non_interactive(self, _euid, _which):
        as_list = privileged_cmd(['iptables', '-C', 'DOCKER-USER'])
        assert as_list[:2] == ['sudo', '-n']

        as_user = privileged_cmd(['whoami'], user='deploy')
        assert as_user[:4] == ['sudo', '-n', '-u', 'deploy']

        as_string = privileged_cmd('iptables -C DOCKER-USER')
        assert as_string.startswith('sudo -n ')

        as_user_string = privileged_cmd('whoami', user='deploy')
        assert as_user_string.startswith('sudo -n -u deploy ')

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_string_command_no_double_sudo(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        run_privileged('sudo systemctl restart nginx')
        args, _ = mock_run.call_args
        assert args[0] == 'sudo systemctl restart nginx'

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_returns_completed_process(self, _euid, mock_run):
        expected = subprocess.CompletedProcess([], 0, stdout='ok')
        mock_run.return_value = expected
        result = run_privileged(['echo', 'ok'])
        assert result is expected


# ---------------------------------------------------------------------------
# is_command_available
# ---------------------------------------------------------------------------
class TestIsCommandAvailable:
    """Tests for :func:`is_command_available`."""

    @patch('app.utils.system.shutil.which', return_value='/usr/bin/nginx')
    def test_found_in_path(self, _which):
        assert is_command_available('nginx') is True

    @patch('app.utils.system.os.path.exists', return_value=True)
    @patch('app.utils.system.shutil.which', return_value=None)
    def test_found_in_common_paths(self, _which, _exists):
        assert is_command_available('firewall-cmd') is True

    @patch('app.utils.system.os.path.exists', return_value=False)
    @patch('app.utils.system.shutil.which', return_value=None)
    def test_not_found(self, _which, _exists):
        assert is_command_available('nonexistent') is False


# ---------------------------------------------------------------------------
# PackageManager
# ---------------------------------------------------------------------------
class TestPackageManager:
    """Tests for :class:`PackageManager`."""

    def setup_method(self):
        PackageManager.reset_cache()

    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/apt' if c == 'apt' else None)
    def test_detect_apt(self, _which):
        assert PackageManager.detect() == 'apt'

    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/dnf' if c == 'dnf' else None)
    def test_detect_dnf(self, _which):
        assert PackageManager.detect() == 'dnf'

    @patch('app.utils.system.shutil.which', return_value=None)
    def test_detect_none(self, _which):
        assert PackageManager.detect() is None

    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/apt' if c == 'apt' else None)
    def test_is_available_true(self, _which):
        assert PackageManager.is_available() is True

    @patch('app.utils.system.shutil.which', return_value=None)
    def test_is_available_false(self, _which):
        assert PackageManager.is_available() is False

    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/apt' if c == 'apt' else None)
    def test_detect_caches(self, mock_which):
        PackageManager.detect()
        PackageManager.detect()
        # shutil.which should only be called during the first detect()
        assert mock_which.call_count <= 3  # at most apt/dnf/yum on first call

    # -- is_installed --

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/apt' if c == 'apt' else None)
    def test_is_installed_apt_true(self, _which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            [], 0, stdout='Status: install ok installed\n',
        )
        assert PackageManager.is_installed('nginx') is True
        mock_run.assert_called_once_with(
            ['dpkg', '-s', 'nginx'], capture_output=True, text=True, timeout=_module.PROBE_TIMEOUT,
        )

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/apt' if c == 'apt' else None)
    def test_is_installed_apt_false(self, _which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stdout='')
        assert PackageManager.is_installed('nginx') is False

    @patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError)
    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/apt' if c == 'apt' else None)
    def test_is_installed_apt_dpkg_missing(self, _which, _run):
        assert PackageManager.is_installed('nginx') is False

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/dnf' if c == 'dnf' else None)
    def test_is_installed_rpm_true(self, _which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='nginx-1.0\n')
        assert PackageManager.is_installed('nginx') is True

    @patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError)
    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/dnf' if c == 'dnf' else None)
    def test_is_installed_rpm_missing(self, _which, _run):
        assert PackageManager.is_installed('nginx') is False

    @patch('app.utils.system.shutil.which', return_value=None)
    def test_is_installed_no_manager(self, _which):
        assert PackageManager.is_installed('nginx') is False

    # -- install --

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/apt' if c == 'apt' else ('/usr/bin/sudo' if c == 'sudo' else None))
    def test_install_apt(self, _which, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        result = PackageManager.install(['nginx', 'curl'])
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'apt', 'install', '-y', 'nginx', 'curl'],
            capture_output=True, text=True, timeout=300,
        )

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    @patch('app.utils.system.shutil.which', side_effect=lambda c: '/usr/bin/dnf' if c == 'dnf' else ('/usr/bin/sudo' if c == 'sudo' else None))
    def test_install_dnf(self, _which, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        PackageManager.install('nginx')
        args = mock_run.call_args[0][0]
        assert args == ['sudo', '-n', 'dnf', 'install', '-y', 'nginx']

    @patch('app.utils.system.shutil.which', return_value=None)
    def test_install_no_manager_raises(self, _which):
        with pytest.raises(RuntimeError, match='No supported package manager'):
            PackageManager.install('nginx')


# ---------------------------------------------------------------------------
# ServiceControl
# ---------------------------------------------------------------------------
class TestServiceControl:
    """Tests for :class:`ServiceControl`."""

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_start(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.start('nginx')
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'start', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_stop(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.stop('nginx')
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'stop', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_restart(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.restart('nginx')
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'restart', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_reload(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.reload('nginx')
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'reload', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_enable(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.enable('nginx')
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'enable', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_disable(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.disable('nginx')
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'disable', 'nginx'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_daemon_reload(self, _euid, mock_run, _which):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.daemon_reload()
        mock_run.assert_called_once_with(
            ['sudo', '-n', 'systemctl', 'daemon-reload'],
            capture_output=True, text=True, timeout=_module.DEFAULT_PRIVILEGED_TIMEOUT,
        )

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_restart_with_kwargs(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        ServiceControl.restart('nginx', check=True, timeout=30)
        _, kwargs = mock_run.call_args
        assert kwargs['check'] is True
        assert kwargs['timeout'] == 30

    @patch('app.utils.system.subprocess.run')
    def test_is_active_true(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='active\n')
        assert ServiceControl.is_active('nginx') is True

    @patch('app.utils.system.subprocess.run')
    def test_is_active_false(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 3, stdout='inactive\n')
        assert ServiceControl.is_active('nginx') is False

    @patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError)
    def test_is_active_missing_systemctl(self, _run):
        """A host without systemctl is "could not check", not "not running" —
        the error propagates so the doctor can render a warn row."""
        with pytest.raises(FileNotFoundError):
            ServiceControl.is_active('nginx')

    @patch('app.utils.system.subprocess.run')
    def test_is_enabled_true(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='enabled\n')
        assert ServiceControl.is_enabled('nginx') is True

    @patch('app.utils.system.subprocess.run')
    def test_is_enabled_false(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stdout='disabled\n')
        assert ServiceControl.is_enabled('nginx') is False

    @patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError)
    def test_is_enabled_missing_systemctl(self, _run):
        assert ServiceControl.is_enabled('nginx') is False


class TestResultDict:
    """The one CompletedProcess -> service-dict translation (plan 75 §F5)."""

    def test_success_shape(self):
        proc = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        assert ServiceControl.result_dict(proc, 'Postfix restarted') == {
            'success': True, 'message': 'Postfix restarted'}

    def test_failure_carries_stderr_under_the_error_key_by_default(self):
        proc = subprocess.CompletedProcess([], 1, stdout='', stderr='boom')
        assert ServiceControl.result_dict(proc, 'ok') == {
            'success': False, 'error': 'boom'}

    def test_failure_key_is_parametrized_for_message_shaped_services(self):
        proc = subprocess.CompletedProcess([], 1, stdout='', stderr='boom')
        assert ServiceControl.result_dict(proc, 'ok', error_key='message') == {
            'success': False, 'message': 'boom'}

    def test_empty_stderr_uses_the_fallback(self):
        proc = subprocess.CompletedProcess([], 1, stdout='', stderr='')
        assert ServiceControl.result_dict(proc, 'ok', fallback='Restart failed') == {
            'success': False, 'error': 'Restart failed'}


# ---------------------------------------------------------------------------
# write_privileged_file
# ---------------------------------------------------------------------------
class TestWritePrivilegedFile:
    """The one privileged-write door (plan 75 §G2).

    Fifteen call sites in two competing forms collapsed into this, so the
    properties they each hand-rolled are asserted once, here.
    """

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_writes_via_tee_with_content_on_stdin(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        assert write_privileged_file('/etc/nginx/sites-available/x', 'server {}') == {
            'success': True, 'path': '/etc/nginx/sites-available/x'}
        argv, kwargs = mock_run.call_args[0][0], mock_run.call_args[1]
        assert argv == ['tee', '/etc/nginx/sites-available/x']
        # content never lands on the argv
        assert kwargs['input'] == 'server {}'

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_append_uses_tee_dash_a(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        write_privileged_file('/etc/postfix/main.cf', 'x=1\n', append=True)
        assert mock_run.call_args[0][0] == ['tee', '-a', '/etc/postfix/main.cf']

    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_sudo_is_decided_by_needs_sudo_not_hardcoded(self, _euid, mock_run, *_):
        """The drift this helper exists to remove.

        environment_domain_service hardcoded ``['sudo', 'tee', path]``, which
        fails on a panel already running as root in a container with no sudo
        binary — plan 74's outage shape. Going through run_privileged means the
        decision is made once, by _needs_sudo().
        """
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        write_privileged_file('/etc/x', 'c')
        assert mock_run.call_args[0][0] == ['sudo', '-n', 'tee', '/etc/x']

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_nonzero_exit_reports_stderr(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stdout='', stderr='Permission denied\n')
        result = write_privileged_file('/etc/x', 'c')
        assert result['success'] is False
        assert result['error'] == 'Permission denied'

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_empty_stderr_still_yields_an_error_string(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stdout='', stderr='')
        result = write_privileged_file('/etc/x', 'c')
        assert result['success'] is False
        assert '/etc/x' in result['error']

    @patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError())
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_missing_tee_is_a_failure_not_a_silent_success(self, _euid, _run):
        """§A: a write that could not run must never report as one that did."""
        result = write_privileged_file('/etc/x', 'c')
        assert result['success'] is False
        assert 'tee' in result['error']

    @patch('app.utils.system.subprocess.run',
           side_effect=subprocess.TimeoutExpired('tee', 300))
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_timeout_is_a_failure_not_a_silent_success(self, _euid, _run):
        result = write_privileged_file('/etc/x', 'c')
        assert result['success'] is False
        assert 'timed out' in result['error']

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_mode_and_owner_are_applied_after_the_write(self, _euid, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        write_privileged_file('/etc/postfix/sasl_passwd', 'x', mode='600', owner='root:root')
        assert [c[0][0] for c in mock_run.call_args_list] == [
            ['tee', '/etc/postfix/sasl_passwd'],
            ['chmod', '600', '/etc/postfix/sasl_passwd'],
            ['chown', 'root:root', '/etc/postfix/sasl_passwd'],
        ]

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=0, create=True)
    def test_a_failed_chmod_fails_the_write(self, _euid, mock_run):
        """A secrets file written world-readable is not a successful write."""
        mock_run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout='', stderr=''),
            subprocess.CompletedProcess([], 1, stdout='', stderr='chmod: no such file'),
        ]
        result = write_privileged_file('/etc/x', 'c', mode='600')
        assert result['success'] is False
        assert 'chmod' in result['error']


# ---------------------------------------------------------------------------
# unit_is_active
# ---------------------------------------------------------------------------
class TestUnitIsActive:
    """Tri-state systemd probe (plan 75 §G6).

    Five services re-inlined `systemctl is-active` and every one of them
    collapsed "could not ask" into "not running". None means could-not-tell.
    """

    @patch('app.utils.system.subprocess.run')
    def test_active(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='active\n', stderr='')
        assert unit_is_active('nginx') is True

    @patch('app.utils.system.subprocess.run')
    def test_inactive_is_false_not_none(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 3, stdout='inactive\n', stderr='')
        assert unit_is_active('nginx') is False

    @patch('app.utils.system.subprocess.run')
    def test_failed_unit_is_false(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 3, stdout='failed\n', stderr='')
        assert unit_is_active('nginx') is False

    @patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError())
    def test_no_systemctl_is_none_never_false(self, _run):
        """A host without systemd has not told us the service is down."""
        assert unit_is_active('nginx') is None

    @patch('app.utils.system.subprocess.run',
           side_effect=subprocess.TimeoutExpired('systemctl', 10))
    def test_timeout_is_none(self, _run):
        assert unit_is_active('nginx') is None

    @patch('app.utils.system.subprocess.run')
    def test_empty_answer_is_none(self, mock_run):
        """systemctl answering nothing is not systemctl answering "no"."""
        mock_run.return_value = subprocess.CompletedProcess([], 1, stdout='', stderr='')
        assert unit_is_active('nginx') is None

    @patch('app.utils.system.subprocess.run')
    def test_probe_is_not_privileged(self, mock_run):
        """is-active needs no root; adding sudo would make it fail where the
        sudoers policy is tight, for no benefit."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='active', stderr='')
        unit_is_active('nginx')
        assert mock_run.call_args[0][0] == ['systemctl', 'is-active', 'nginx']


# ---------------------------------------------------------------------------
# run_checked
# ---------------------------------------------------------------------------
class TestRunChecked:
    """The result-shaped door (plan 75 §G1).

    Around the raw subprocess calls it replaces sit 220 copies of
    capture_output/text, 56 hand-rolled TimeoutExpired handlers, 19
    FileNotFoundError handlers, and 1,164 literal error dicts. Each is a place
    an exec failure can become a false fact; the properties that stop that are
    asserted once, here.
    """

    @patch('app.utils.system.subprocess.run')
    def test_success_shape(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='hi\n', stderr='')
        assert run_checked(['echo', 'hi']) == {
            'success': True, 'output': 'hi\n', 'stderr': '',
            'error': None, 'returncode': 0}

    @patch('app.utils.system.subprocess.run')
    def test_stderr_on_a_SUCCESSFUL_command_is_not_an_error(self, mock_run):
        """git, docker exec and friends write to stderr and still succeed.

        Folding the stream into the verdict would invent failures, so
        `stderr` (the stream) and `error` (the verdict) are separate keys.
        """
        mock_run.return_value = subprocess.CompletedProcess(
            [], 0, stdout='', stderr='Cloning into ...\n')
        result = run_checked(['git', 'clone', 'x'])
        assert result['success'] is True
        assert result['error'] is None
        assert result['stderr'] == 'Cloning into ...\n'

    @patch('app.utils.system.subprocess.run')
    def test_stderr_is_raw_while_error_is_stripped(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stdout='', stderr=' boom \n')
        result = run_checked(['false'])
        assert result['stderr'] == ' boom \n'
        assert result['error'] == 'boom'

    @patch('app.utils.system.subprocess.run')
    def test_merge_stderr_interleaves_into_output(self, mock_run):
        """`docker logs` needs it: a container's stderr is part of its log,
        not an error about fetching the log."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='a\nb\n', stderr=None)
        result = run_checked(['docker', 'logs', 'x'], merge_stderr=True)
        assert result['output'] == 'a\nb\n'
        kwargs = mock_run.call_args[1]
        assert kwargs['stderr'] is subprocess.STDOUT
        assert 'capture_output' not in kwargs   # mutually exclusive with stderr=

    def test_a_command_that_never_ran_still_has_every_key(self):
        """A caller destructuring the result must not KeyError on the failure
        path — that is how an exec failure becomes a 500 instead of a message."""
        with patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError('x')), \
                patch('app.utils.system.shutil.which', return_value='/bin/x'):
            result = run_checked(['x'])
        assert set(result) == {'success', 'output', 'stderr', 'error', 'returncode'}

    @patch('app.utils.system.subprocess.run')
    def test_capture_and_text_are_applied_for_the_caller(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        run_checked(['echo'])
        assert mock_run.call_args[1]['capture_output'] is True
        assert mock_run.call_args[1]['text'] is True

    @patch('app.utils.system.subprocess.run')
    def test_nonzero_exit_carries_stderr_and_the_code(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 2, stdout='', stderr='nope\n')
        result = run_checked(['false'])
        assert result['success'] is False
        assert result['error'] == 'nope'
        assert result['returncode'] == 2

    @patch('app.utils.system.subprocess.run')
    def test_nonzero_exit_with_silent_stderr_still_explains_itself(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 3, stdout='', stderr='')
        assert '3' in run_checked(['false'])['error']

    # ---- the distinction the hand-rolled handlers keep losing --------------
    # patch.object on _module, not @patch('app.utils.system.resolve_command'):
    # this file loads system.py under its own spec, so the string path can
    # resolve to a DIFFERENT module object than the one run_checked closes
    # over, depending on what imported `app` earlier in the session. `shutil`
    # is a singleton so patching through it is identity-safe; a module-level
    # function of system.py is not.
    @patch('app.utils.system.subprocess.run', side_effect=FileNotFoundError('no ufw'))
    @patch('app.utils.system.shutil.which', return_value=None)
    @patch.object(_module, 'resolve_command', return_value=None)
    def test_missing_command_has_no_returncode(self, _resolve, _which, _run):
        """Exit 1 means the command answered "no"; no exit code at all means
        nobody answered. A caller rendering "not installed" must be able to
        tell those apart — plan 74's outage in one assertion."""
        result = run_checked(['ufw', 'status'])
        assert result['success'] is False
        assert result['returncode'] is None
        assert 'ufw' in result['error']

    @patch('app.utils.system.subprocess.run',
           side_effect=subprocess.TimeoutExpired('sleep', 60))
    def test_timeout_has_no_returncode_and_names_the_limit(self, _run):
        result = run_checked(['sleep', '999'], timeout=60)
        assert result['returncode'] is None
        assert 'timed out' in result['error'] and '60' in result['error']

    @patch('app.utils.system.subprocess.run', side_effect=PermissionError('denied'))
    def test_permission_error_is_reported_not_raised(self, _run):
        result = run_checked(['/root/thing'])
        assert result['success'] is False and result['returncode'] is None
        assert 'permission denied' in result['error']

    @patch('app.utils.system.subprocess.run')
    def test_a_timeout_is_applied_by_default(self, mock_run):
        """No timeout + captured output = a wedged request, silently, forever."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        run_checked(['echo'])
        assert mock_run.call_args[1]['timeout'] == 60

    @patch('app.utils.system.subprocess.run')
    def test_timeout_none_is_honoured_when_asked_for(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        run_checked(['echo'], timeout=None)
        assert mock_run.call_args[1]['timeout'] is None

    # ---- privilege + PATH, decided in one place ---------------------------
    @patch('app.utils.system.os.name', 'posix')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/sudo')
    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.os.geteuid', return_value=1000, create=True)
    def test_privileged_goes_through_run_privileged(self, _euid, mock_run, *_):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        run_checked(['systemctl', 'restart', 'nginx'], privileged=True)
        assert mock_run.call_args[0][0][:2] == ['sudo', '-n']

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.shutil.which', return_value=None)
    @patch.object(_module, 'resolve_command', return_value='/usr/sbin/nginx')
    def test_unprivileged_still_resolves_an_sbin_binary(self, _resolve, _which, mock_run):
        """The sbin outage does not become survivable only when you ask for
        root — an unprivileged `nginx -t` needs the same resolution."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        run_checked(['nginx', '-t'])
        assert mock_run.call_args[0][0] == ['/usr/sbin/nginx', '-t']

    @patch('app.utils.system.subprocess.run')
    @patch('app.utils.system.shutil.which', return_value='/usr/bin/git')
    def test_a_command_on_path_is_left_alone(self, _which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        run_checked(['git', 'status'])
        assert mock_run.call_args[0][0] == ['git', 'status']

    @patch('app.utils.system.subprocess.run')
    def test_input_is_forwarded(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        run_checked(['crontab', '-'], input='* * * * * true\n')
        assert mock_run.call_args[1]['input'] == '* * * * * true\n'
