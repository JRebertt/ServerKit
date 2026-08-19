"""The one docker runner (plan 75 §G3).

Three services kept private `_docker()` wrappers around the same
`subprocess.run(['docker', ...])` call, and the three had drifted into three
different return contracts — two dict shapes that disagreed about error text,
and one that handed back a raw `CompletedProcess`. A caller reading
`result['success']` against the third got a TypeError, not an answer.

What each copy half-did is asserted here once, with particular attention to the
distinctions §A says a probe must keep: "docker said no", "docker is absent",
and "docker did not answer in time" are three different facts.
"""

import subprocess

import pytest

from app.services.docker_service import DockerService


class TestResultShape:
    def test_success_carries_stdout(self, fake_subprocess):
        fake_subprocess.script(['docker', 'ps'], stdout='CONTAINER\n')
        # DockerService.run sits on run_checked (§G1), so the shape is the
        # shared one — asserted by key here rather than by whole-dict equality,
        # which would have to be edited in every suite each time the door
        # gains a field.
        result = DockerService.run(['ps'])
        assert result['success'] is True
        assert result['output'] == 'CONTAINER\n'
        assert result['error'] is None
        assert result['returncode'] == 0

    def test_the_shape_is_run_checkeds(self, fake_subprocess):
        fake_subprocess.script(['docker', 'ps'])
        assert set(DockerService.run(['ps'])) == {
            'success', 'output', 'stderr', 'error', 'returncode'}

    def test_failure_carries_stderr(self, fake_subprocess):
        fake_subprocess.script(['docker'], returncode=1, stderr='No such container\n')
        result = DockerService.run(['inspect', 'nope'])
        assert result['success'] is False
        assert result['error'] == 'No such container'

    def test_failure_with_empty_stderr_still_has_an_error_string(self, fake_subprocess):
        """One of the three copies returned error=None here, so a caller that
        rendered result['error'] showed the operator nothing at all."""
        fake_subprocess.script(['docker'], returncode=1, stderr='')
        result = DockerService.run(['ps'])
        assert result['success'] is False
        assert result['error']

    def test_output_is_a_string_even_on_failure(self, fake_subprocess):
        fake_subprocess.script(['docker'], returncode=1, stderr='boom')
        assert DockerService.run(['ps'])['output'] == ''


class TestTheThreeWaysItCanNotWork:
    """The distinctions the drifted copies collapsed."""

    def test_docker_absent_says_so(self, fake_subprocess):
        fake_subprocess.script(['docker'], raises=FileNotFoundError)
        result = DockerService.run(['ps'])
        assert result['success'] is False
        assert 'not found' in result['error'].lower()

    def test_timeout_says_so_and_names_the_limit(self, fake_subprocess):
        fake_subprocess.script(['docker'],
                               raises=subprocess.TimeoutExpired('docker', 60))
        result = DockerService.run(['ps'], timeout=60)
        assert result['success'] is False
        assert 'timed out' in result['error']
        assert '60' in result['error']

    def test_absent_and_timed_out_are_distinguishable(self, fake_subprocess):
        """db_config_tuner's copy collapsed both into str(e), so the caller
        could not tell "install docker" from "the daemon is wedged"."""
        fake_subprocess.script(['docker'], raises=FileNotFoundError)
        absent = DockerService.run(['ps'])['error']
        fake_subprocess.script(['docker'],
                               raises=subprocess.TimeoutExpired('docker', 5))
        slow = DockerService.run(['ps'], timeout=5)['error']
        assert absent != slow


class TestAvailable:
    def test_asks_the_daemon_not_just_the_binary(self, fake_subprocess, monkeypatch):
        """`docker version --format {{.Server.Version}}` fails when the CLI is
        installed but the daemon is down — the state callers care about."""
        monkeypatch.setattr('app.services.docker_service.os.name', 'posix')
        fake_subprocess.script(['docker', 'version'], stdout='27.0.3\n')
        assert DockerService.available() is True
        assert '{{.Server.Version}}' in fake_subprocess.argv_for(['docker', 'version'])

    def test_daemon_down_is_false(self, fake_subprocess, monkeypatch):
        monkeypatch.setattr('app.services.docker_service.os.name', 'posix')
        fake_subprocess.script(['docker'], returncode=1, stderr='Cannot connect')
        assert DockerService.available() is False

    def test_missing_docker_is_false_not_an_exception(self, fake_subprocess, monkeypatch):
        monkeypatch.setattr('app.services.docker_service.os.name', 'posix')
        fake_subprocess.script(['docker'], raises=FileNotFoundError)
        assert DockerService.available() is False

    def test_windows_is_false_without_running_anything(self, fake_subprocess, monkeypatch):
        monkeypatch.setattr('app.services.docker_service.os.name', 'nt')
        assert DockerService.available() is False
        assert fake_subprocess.commands() == []


class TestTheWrappersDelegate:
    """The three private copies are gone; the named seams remain."""

    @pytest.mark.parametrize('module_path,attr', [
        ('app.services.db_admin_sso_service', 'DbAdminSsoService'),
        ('app.services.db_config_tuner_service', 'DbConfigTunerService'),
        ('app.services.image_update_service', 'ImageUpdateService'),
    ])
    def test_every_wrapper_returns_the_shared_shape(self, module_path, attr,
                                                    fake_subprocess):
        import importlib
        service = getattr(importlib.import_module(module_path), attr)
        fake_subprocess.script(['docker'], stdout='ok\n')
        result = service._docker(['ps'])
        assert {'success', 'output', 'error'} <= set(result)
        assert result['success'] is True and result['output'] == 'ok\n'


class TestLongOperationsAreNotCapped:
    """The one way this migration could have broken a real deployment.

    `run_checked` defaults to a 60s timeout. Every docker call in
    docker_service is unbounded today, and `compose up --build` on a small VPS
    routinely runs longer than a minute — inheriting the default would have
    turned working deploys into timeouts. These pin the opt-out at the sites
    where it matters.
    """

    def _timeout_for(self, fake, prefix):
        return fake.kwargs_for(prefix).get('timeout')

    def test_pull_image_is_unbounded(self, fake_subprocess):
        fake_subprocess.script(['docker', 'pull'])
        DockerService.pull_image('nginx', tag='latest')
        assert self._timeout_for(fake_subprocess, ['docker', 'pull']) is None

    def test_build_image_is_unbounded(self, fake_subprocess):
        fake_subprocess.script(['docker', 'build'])
        DockerService.build_image('/srv/app', 'app:latest')
        assert self._timeout_for(fake_subprocess, ['docker', 'build']) is None

    def test_run_container_is_unbounded(self, fake_subprocess):
        """`docker run` pulls the image when it is absent."""
        fake_subprocess.script(['docker', 'run'], stdout='cid\n')
        DockerService.run_container('nginx')
        assert self._timeout_for(fake_subprocess, ['docker', 'run']) is None

    def test_prune_is_unbounded(self, fake_subprocess):
        fake_subprocess.script(['docker', 'system'])
        DockerService.prune_system()
        assert self._timeout_for(fake_subprocess, ['docker', 'system']) is None

    def test_run_compose_defaults_to_unbounded(self, fake_subprocess):
        fake_subprocess.script(['docker-compose'])
        DockerService.run_compose(['docker-compose', 'up', '-d'], cwd='/srv/x')
        assert self._timeout_for(fake_subprocess, ['docker-compose']) is None

    def test_exec_command_keeps_its_60s_bound(self, fake_subprocess):
        """The one site that DID have a timeout keeps it."""
        fake_subprocess.script(['docker', 'exec'])
        DockerService.exec_command('c1', 'ls')
        assert self._timeout_for(fake_subprocess, ['docker', 'exec']) == 60


class TestLogsKeepInterleaving:
    def test_container_logs_merge_stderr_rather_than_concatenating(self, fake_subprocess):
        """A container writes its log to both streams. `stdout + stderr`
        concatenation put the crash tail above the lines that led to it."""
        fake_subprocess.script(['docker', 'logs'], stdout='one\ntwo\n')
        result = DockerService.get_container_logs('c1')
        assert result['logs'] == 'one\ntwo\n'
        assert fake_subprocess.kwargs_for(['docker', 'logs'])['stderr'] is not None


class TestExecCommandHonesty:
    def test_a_real_nonzero_exit_reports_the_code(self, fake_subprocess):
        fake_subprocess.script(['docker', 'exec'], returncode=2, stderr='nope')
        result = DockerService.exec_command('c1', 'false')
        assert result['success'] is False
        assert result['return_code'] == 2
        assert result['stderr'] == 'nope'

    def test_stderr_on_a_successful_exec_is_not_an_error(self, fake_subprocess):
        fake_subprocess.script(['docker', 'exec'], stdout='out', stderr='warn')
        result = DockerService.exec_command('c1', 'thing')
        assert result['success'] is True
        assert result['stdout'] == 'out' and result['stderr'] == 'warn'

    def test_a_command_that_never_ran_claims_no_return_code(self, fake_subprocess):
        """Reporting return_code here would say the container answered."""
        fake_subprocess.script(['docker'], raises=FileNotFoundError)
        result = DockerService.exec_command('c1', 'ls')
        assert result['success'] is False
        assert 'return_code' not in result
        assert result['error']


class TestProbesStillFallBack:
    def test_compose_detection_never_raises_into_its_caller(self, fake_subprocess,
                                                            monkeypatch):
        """Dropping this guard made a broken probe surface as `compose up`
        exit_code -1 instead of a v1 fallback — caught by test_deploy_console."""
        monkeypatch.setattr(DockerService, '_compose_cmd', None)

        def explode(argv, kwargs):
            raise RuntimeError('probe blew up')

        fake_subprocess.when(['docker'], explode)
        assert DockerService._get_compose_cmd() == ['docker-compose']
