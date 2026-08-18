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
        assert DockerService.run(['ps']) == {
            'success': True, 'output': 'CONTAINER\n', 'error': None}

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
        assert set(result) == {'success', 'output', 'error'}
        assert result['success'] is True and result['output'] == 'ok\n'
