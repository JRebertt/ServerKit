"""Compose v1 hosts must not be handed v2-only flags.

Every template install on a docker-compose v1 host failed at "Start Docker
Compose stack": the streaming path passed `--progress plain`, v1 answered an
unknown global flag by printing its entire usage text and exiting 1, and the
deploy console showed a wall of help output with nothing indicating the
argument was at fault.

v1 and v2 do not share a global flag set, so anything v2-only has to be gated
on the version actually detected.
"""

import pytest

from app.services.docker_service import DockerService


@pytest.fixture(autouse=True)
def _reset_detection():
    # The detected command is cached on the class for the process lifetime.
    DockerService._compose_cmd = None
    yield
    DockerService._compose_cmd = None


def _capture_cmd(monkeypatch):
    """Run compose_up_streaming against a fake Popen and return the argv."""
    seen = {}

    class _FakeProc:
        def __init__(self, *args, **kwargs):
            seen['cmd'] = args[0] if args else kwargs.get('args')
            self.stdout = iter(())

        def wait(self):
            return 0

    class _Stdout:
        def __iter__(self):
            return iter(())

        def readline(self):
            return ''

        def close(self):
            pass

    def _popen(cmd, **kwargs):
        seen['cmd'] = cmd
        proc = _FakeProc.__new__(_FakeProc)
        proc.stdout = _Stdout()
        proc.wait = lambda: 0
        return proc

    monkeypatch.setattr('subprocess.Popen', _popen)
    monkeypatch.setattr(DockerService, '_compose_cmd_with_overlay',
                        classmethod(lambda cls, path, compose_file=None:
                                    cls._get_compose_cmd() + ['-f', 'docker-compose.yml']))
    DockerService.compose_up_streaming('/srv/app', lambda line: None)
    return seen['cmd']


def _pretend_v2(monkeypatch, available):
    """Make v2 detection succeed or fail without touching a real docker."""
    class _Result:
        returncode = 0 if available else 1
        stdout = 'Docker Compose version v2.29.0' if available else ''
        stderr = ''

    monkeypatch.setattr('subprocess.run', lambda *a, **k: _Result())


class TestComposeFlags:
    def test_v1_is_never_given_the_v2_only_progress_flag(self, monkeypatch):
        _pretend_v2(monkeypatch, available=False)
        cmd = _capture_cmd(monkeypatch)

        assert cmd[:1] == ['docker-compose']
        assert '--progress' not in cmd
        # The flag v1 does understand stays.
        assert '--ansi' in cmd
        assert cmd[-1] != '--progress' and 'up' in cmd

    def test_v2_still_gets_plain_progress(self, monkeypatch):
        _pretend_v2(monkeypatch, available=True)
        cmd = _capture_cmd(monkeypatch)

        assert cmd[:2] == ['docker', 'compose']
        assert '--progress' in cmd
        assert cmd[cmd.index('--progress') + 1] == 'plain'

    def test_global_flags_precede_the_subcommand(self, monkeypatch):
        # compose only accepts these before `up`; after it they are argument
        # errors on both versions.
        _pretend_v2(monkeypatch, available=True)
        cmd = _capture_cmd(monkeypatch)

        assert cmd.index('--ansi') < cmd.index('up')
        assert cmd.index('--progress') < cmd.index('up')

    def test_detach_still_applies_on_v1(self, monkeypatch):
        _pretend_v2(monkeypatch, available=False)
        cmd = _capture_cmd(monkeypatch)
        assert cmd[-1] == '-d'


class TestVersionDetection:
    def test_reports_v2_when_the_plugin_answers(self, monkeypatch):
        _pretend_v2(monkeypatch, available=True)
        assert DockerService._is_compose_v2() is True

    def test_reports_v1_when_it_does_not(self, monkeypatch):
        _pretend_v2(monkeypatch, available=False)
        assert DockerService._is_compose_v2() is False

    def test_detection_survives_docker_being_absent(self, monkeypatch):
        def _boom(*a, **k):
            raise FileNotFoundError('docker not installed')

        monkeypatch.setattr('subprocess.run', _boom)
        # Falls back to v1 rather than raising into the deploy path.
        assert DockerService._get_compose_cmd() == ['docker-compose']
        assert DockerService._is_compose_v2() is False
