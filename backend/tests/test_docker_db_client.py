"""Which CLI ServerKit execs inside a database container.

MariaDB 11 dropped the `mysql` symlink in favour of `mariadb`. Every call site
here used to hardcode `mysql`, so introspecting any modern MariaDB container
failed outright with:

    OCI runtime exec failed: exec: "mysql": executable file not found in $PATH

That is not a hypothetical image — `backend/templates/mariadb.yaml`, the engine
template ServerKit itself installs, pins `mariadb:11.4`. Installing MariaDB
through the panel produced a database the panel could not read.

These tests stub `subprocess.run` so nothing here needs Docker.
"""
import pytest

from app.services import database_service as ds
from app.services.database_service import DatabaseService


@pytest.fixture(autouse=True)
def clear_client_cache():
    """The resolved client is memoised per container name."""
    DatabaseService._docker_client_cache.clear()
    yield
    DatabaseService._docker_client_cache.clear()


class _Result:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_run(available):
    """subprocess.run stand-in where only `available` clients exist."""
    calls = []

    def run(cmd, *args, **kwargs):
        calls.append(cmd)
        # `docker exec <name> <client> --version`
        if len(cmd) >= 4 and cmd[0] == 'docker' and cmd[1] == 'exec':
            client = cmd[3]
            if client in available:
                return _Result(0, f'{client} Ver 11.4')
            return _Result(1, stderr=f'exec: "{client}": executable file not found in $PATH')
        return _Result(0)

    run.calls = calls
    return run


def test_modern_mariadb_resolves_to_the_mariadb_client(monkeypatch):
    monkeypatch.setattr(ds.subprocess, 'run', _fake_run({'mariadb'}))
    assert DatabaseService._docker_db_client('mariadb-11') == 'mariadb'


def test_mysql_image_still_resolves_to_mysql(monkeypatch):
    """The fix must not break the images that worked before."""
    monkeypatch.setattr(ds.subprocess, 'run', _fake_run({'mysql'}))
    assert DatabaseService._docker_db_client('mysql-8') == 'mysql'


def test_result_is_cached_per_container(monkeypatch):
    run = _fake_run({'mariadb'})
    monkeypatch.setattr(ds.subprocess, 'run', run)

    DatabaseService._docker_db_client('cached-one')
    probes_after_first = len(run.calls)
    DatabaseService._docker_db_client('cached-one')

    assert len(run.calls) == probes_after_first, 'client probe should run once per container'


def test_unknown_container_falls_back_to_mysql(monkeypatch):
    """Nothing answered — keep the historic default so the caller's error stays
    the familiar one rather than becoming a new mystery."""
    monkeypatch.setattr(ds.subprocess, 'run', _fake_run(set()))
    assert DatabaseService._docker_db_client('empty') == 'mysql'


def test_exec_uses_the_resolved_client_not_a_hardcoded_mysql(monkeypatch):
    """The load-bearing one: the command actually sent to docker must carry the
    client that exists in that container."""
    run = _fake_run({'mariadb'})
    monkeypatch.setattr(ds.subprocess, 'run', run)

    DatabaseService.docker_mysql_execute('mariadb-11', 'SHOW DATABASES', password='pw')

    exec_cmds = [c for c in run.calls if '--version' not in c]
    assert exec_cmds, 'no query command was issued'
    assert 'mariadb' in exec_cmds[-1]
    assert 'mysql' not in exec_cmds[-1]


def test_shipped_mariadb_template_would_be_introspectable(monkeypatch):
    """`mariadb.yaml` pins an image whose client is `mariadb`. If a future edit
    reverts the resolution, this is the test that says the panel just lost the
    ability to read its own installed engine."""
    monkeypatch.setattr(ds.subprocess, 'run', _fake_run({'mariadb'}))
    client = DatabaseService._docker_db_client('serverkit-mariadb')
    assert client == 'mariadb'
