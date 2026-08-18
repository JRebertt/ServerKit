"""Plan 73 item 9 — the doctor could not see a running-but-broken nginx.

Three separate blind spots, one theme: the panel trusted a signal that does
not mean what the UI claimed it meant.

* ``systemctl is-active nginx`` says "active" for an nginx serving a config
  it can no longer parse, so the doctor reported a healthy box.
* ``NginxService.restart`` did not test the config first the way ``reload``
  does — and a restart stops nginx before starting it, so a broken config
  turned into a full outage instead of a rejected reload.
* ``ProcessService.get_services_status`` substring-matched psutil process
  names while the start/stop/restart buttons went through systemctl, so the
  two disagreed about what was running and what could be controlled.
"""
import subprocess
from unittest.mock import patch

import pytest

from app.services.doctor_service import DoctorService
from app.services.nginx_service import NginxService
from app.services.process_service import ProcessService


# --------------------------------------------------------------------------- #
# doctor: nginx.config
# --------------------------------------------------------------------------- #
class TestNginxConfigCheck:

    def _run(self, *, available=True, test_config=None, raises=None):
        target = 'app.services.nginx_service.NginxService.test_config'
        with patch('app.utils.system.is_command_available', return_value=available), \
                patch(target, side_effect=raises) if raises else \
                patch(target, return_value=test_config):
            return DoctorService._nginx_config_check()

    def test_passing_config_is_ok(self):
        check = self._run(test_config={'success': True, 'message': 'syntax is ok'})

        assert check['key'] == 'nginx.config'
        assert check['status'] == 'ok'

    def test_failing_config_fails_with_nginx_output(self):
        """The operator needs the file and line nginx named, not 'config bad'."""
        message = ('nginx: [emerg] unknown directive "server_nam" in '
                   '/etc/nginx/sites-enabled/example.com:4')
        check = self._run(test_config={'success': False, 'message': message})

        assert check['status'] == 'fail'
        assert message in check['detail']
        # Config repair is operator territory — a wrong guess takes every site
        # on the host down, so the doctor must not offer a repair button.
        assert check['repairable'] is False
        assert check['repair_ref'] is None

    def test_missing_nginx_binary_warns_rather_than_fails(self):
        """No nginx is a legitimate profile, not a broken config."""
        check = self._run(available=False, test_config=None)

        assert check['status'] == 'warn'
        assert 'not found' in check['detail']

    def test_probe_exception_warns_and_does_not_escape(self):
        check = self._run(raises=OSError('boom'))

        assert check['status'] == 'warn'
        assert 'boom' in check['detail']


# --------------------------------------------------------------------------- #
# NginxService.restart
# --------------------------------------------------------------------------- #
class TestRestartTestsConfigFirst:

    def test_broken_config_never_reaches_systemctl(self):
        """The whole point: a restart stops nginx before starting it, so
        restarting on a broken config is an outage, not a rejected reload."""
        with patch.object(NginxService, 'test_config',
                          return_value={'success': False,
                                        'message': 'nginx: [emerg] bad directive'}), \
                patch('app.services.nginx_service.ServiceControl') as control:
            result = NginxService.restart()

        assert result['success'] is False
        assert 'bad directive' in result['error']
        control.restart.assert_not_called()

    def test_good_config_restarts(self):
        with patch.object(NginxService, 'test_config',
                          return_value={'success': True, 'message': 'syntax is ok'}), \
                patch('app.services.nginx_service.ServiceControl') as control:
            control.restart.return_value = subprocess.CompletedProcess(
                [], 0, stdout='', stderr='')
            # The whole class is mocked, so the result translation is too —
            # give it the real one's behavior (tested in test_utils_system).
            control.result_dict.side_effect = (
                lambda proc, msg, **kw: {'success': proc.returncode == 0,
                                         'message': msg})
            result = NginxService.restart()

        assert result['success'] is True
        control.restart.assert_called_once()

    def test_error_key_is_populated_when_test_config_has_no_message(self):
        """test_config reports 'nginx is not installed' under 'error', not
        'message' — the failure text must not come out as None."""
        with patch.object(NginxService, 'test_config',
                          return_value={'success': False,
                                        'error': 'nginx is not installed'}), \
                patch('app.services.nginx_service.ServiceControl'):
            result = NginxService.restart()

        assert result['success'] is False
        assert 'nginx is not installed' in result['error']


# --------------------------------------------------------------------------- #
# ProcessService.get_services_status
# --------------------------------------------------------------------------- #
def _show(*blocks):
    """Render `systemctl show` output: one property block per unit, blank-line
    separated, in argument order."""
    return '\n\n'.join(
        '\n'.join(f'{k}={v}' for k, v in block.items()) for block in blocks) + '\n'


def _unit(unit_id, load='loaded', active='active', pid='0'):
    return {'Id': unit_id, 'LoadState': load, 'ActiveState': active, 'MainPID': pid}


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr('app.services.process_service.platform.system',
                        lambda: 'Linux')


@pytest.fixture
def units(monkeypatch):
    """Shrink the monitored list so a test can spell out systemctl's answer."""
    def _set(names):
        monkeypatch.setattr(ProcessService, 'MONITORED_SERVICES', names)
    return _set


def _with_show(stdout, returncode=0):
    return patch('app.services.process_service.subprocess.run',
                 return_value=subprocess.CompletedProcess([], returncode,
                                                          stdout=stdout, stderr=''))


class TestServiceStatusFollowsSystemd:

    def test_state_comes_from_systemd_not_from_process_names(self, linux, units):
        """psutil is not consulted at all on the systemd path — it is what made
        the list disagree with the buttons."""
        units(['nginx', 'mysql'])
        output = _show(_unit('nginx.service', active='active', pid='812'),
                       _unit('mysql.service', load='not-found', active='inactive'))

        with _with_show(output), \
                patch('app.services.process_service.psutil.process_iter',
                      side_effect=AssertionError('psutil must not be consulted')):
            services = ProcessService.get_services_status()

        assert services == [{'name': 'nginx', 'status': 'running', 'pid': 812}]

    def test_units_the_host_does_not_have_are_dropped(self, linux, units):
        """MONITORED_SERVICES carries several spellings of the same daemon so
        that whichever one a distro uses is found; listing the rest as
        'stopped' was noise, not information."""
        units(['mysql', 'mariadb', 'postgresql'])
        output = _show(_unit('mysql.service', load='not-found', active='inactive'),
                       _unit('mariadb.service', active='active', pid='4110'),
                       _unit('postgresql.service', load='not-found', active='inactive'))

        with _with_show(output):
            services = ProcessService.get_services_status()

        assert [s['name'] for s in services] == ['mariadb']

    def test_aliases_of_one_unit_collapse_to_a_single_row(self, linux, units):
        """On a MariaDB box mysql.service is an alias of mariadb.service. Both
        resolve, and the list used to show the same daemon twice."""
        units(['mysql', 'mariadb'])
        output = _show(_unit('mariadb.service', active='active', pid='4110'),
                       _unit('mariadb.service', active='active', pid='4110'))

        with _with_show(output):
            services = ProcessService.get_services_status()

        assert services == [{'name': 'mysql', 'status': 'running', 'pid': 4110}]

    def test_inactive_unit_is_stopped_with_no_pid(self, linux, units):
        units(['nginx'])

        with _with_show(_show(_unit('nginx.service', active='inactive', pid='0'))):
            services = ProcessService.get_services_status()

        assert services == [{'name': 'nginx', 'status': 'stopped', 'pid': None}]

    def test_failed_unit_is_stopped_not_running(self, linux, units):
        """A unit systemd could not start is not 'running' — the old heuristic
        could still see a leftover process and claim it was."""
        units(['nginx'])

        with _with_show(_show(_unit('nginx.service', active='failed', pid='0'))):
            services = ProcessService.get_services_status()

        assert services[0]['status'] == 'stopped'


class TestServiceStatusFallback:
    """Without a usable systemctl the legacy process-name heuristic still
    answers, rather than the list going silently empty."""

    def _legacy_reached(self, output_patch, units_fixture):
        units_fixture(['nginx'])

        class FakeProc:
            pid = 99

            def name(self):
                return 'nginx'

        with output_patch, \
                patch('app.services.process_service.psutil.process_iter',
                      return_value=[FakeProc()]):
            return ProcessService.get_services_status()

    def test_missing_systemctl_falls_back(self, linux, units):
        patched = patch('app.services.process_service.subprocess.run',
                        side_effect=FileNotFoundError())
        assert self._legacy_reached(patched, units) == [
            {'name': 'nginx', 'status': 'running', 'pid': 99}]

    def test_unparseable_output_falls_back_instead_of_guessing(self, linux, units):
        """Fewer blocks than units means the index pairing is not trustworthy;
        reporting a wrong unit's state would be worse than the old heuristic."""
        units(['nginx', 'mysql'])                   # two units asked about...
        patched = _with_show('Id=nginx.service\n')  # ...one block came back

        class FakeProc:
            pid = 99

            def name(self):
                return 'nginx'

        with patched, patch('app.services.process_service.psutil.process_iter',
                            return_value=[FakeProc()]):
            services = ProcessService.get_services_status()

        assert [s['name'] for s in services] == ['nginx', 'mysql']

    def test_nonzero_systemctl_exit_falls_back(self, linux, units):
        patched = _with_show('', returncode=1)
        assert self._legacy_reached(patched, units) == [
            {'name': 'nginx', 'status': 'running', 'pid': 99}]

    def test_non_linux_uses_the_process_heuristic(self, monkeypatch, units):
        """Windows/macOS dev boxes have no systemd; the dev server must still
        render a Services list."""
        monkeypatch.setattr('app.services.process_service.platform.system',
                            lambda: 'Windows')
        units(['nginx'])

        class FakeProc:
            pid = 7

            def name(self):
                return 'nginx.exe'

        with patch('app.services.process_service.subprocess.run',
                   side_effect=AssertionError('systemctl must not be called')), \
                patch('app.services.process_service.psutil.process_iter',
                      return_value=[FakeProc()]):
            services = ProcessService.get_services_status()

        assert services == [{'name': 'nginx', 'status': 'running', 'pid': 7}]
