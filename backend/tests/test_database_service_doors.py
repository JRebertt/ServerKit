"""database_service's subprocess surface after the §G1 migration.

24 raw call sites -> 8, all eight of the survivors being Popen PIPELINES
(mysqldump|gzip, gunzip|mysql, pg_dump|gzip, gunzip|psql). run_checked runs one
process; a pipe is two.

The assertions that matter here are the ones guarding against a *plausible*
future edit rather than a past bug — chiefly the `sudo -u postgres` argv, which
looks exactly like the hardcoded-sudo drift §G2 removed and is not.
"""

import subprocess

from app.services.database_service import DatabaseService


class TestPostgresIdentitySwitching:
    """`sudo -u postgres` must survive, and it is NOT the §G2 drift pattern.

    §G2 removed hardcoded `sudo` because privilege escalation belongs to
    _needs_sudo(), which correctly skips sudo when already root. That reasoning
    does not transfer here: this sudo switches IDENTITY. PostgreSQL's local
    peer auth maps the OS user to the DB role, so a panel running as root that
    dropped the `-u postgres` would connect as role "root" and fail auth.

    run_privileged(user='postgres') cannot express it — privileged_cmd drops
    the -u along with the sudo whenever _needs_sudo() is False.
    """

    def test_pg_execute_runs_as_the_postgres_user(self, fake_subprocess):
        fake_subprocess.script(['sudo'], stdout='1\n')
        DatabaseService.pg_execute('SELECT 1;')
        argv = fake_subprocess.argv_for(['sudo'])
        assert argv[:4] == ['sudo', '-u', 'postgres', 'psql']

    def test_pg_execute_query_runs_as_the_postgres_user(self, fake_subprocess):
        fake_subprocess.script(['sudo'], stdout='c\nv\n')
        DatabaseService.pg_execute_query('mydb', 'SELECT 1;')
        assert fake_subprocess.argv_for(['sudo'])[:3] == ['sudo', '-u', 'postgres']

    def test_the_sudo_is_not_stripped_by_the_privileged_helper(self, fake_subprocess):
        """run_checked must pass this argv through untouched: privileged=False,
        so nothing re-decides the sudo."""
        fake_subprocess.script(['sudo'])
        DatabaseService.pg_execute('SELECT 1;')
        argv = fake_subprocess.argv_for(['sudo'])
        assert argv.count('sudo') == 1          # no `sudo sudo`
        assert '-n' not in argv[:3]             # not rewritten into sudo -n


class TestSecretsStayOffTheArgv:
    def test_mysql_password_goes_in_the_environment(self, fake_subprocess):
        fake_subprocess.script(['mysql'], stdout='')
        DatabaseService.mysql_execute('SELECT 1;', root_password='s3cret')
        argv = fake_subprocess.argv_for(['mysql'])
        assert 's3cret' not in argv
        env = fake_subprocess.kwargs_for(['mysql'])['env']
        assert env['MYSQL_PWD'] == 's3cret'

    def test_no_password_means_no_env_override(self, fake_subprocess):
        """_mysql_env returns None, and run_checked then does not pass `env` at
        all — so the child inherits the parent environment exactly as it did
        before the helper existed, rather than a copy."""
        fake_subprocess.script(['mysql'], stdout='')
        DatabaseService.mysql_execute('SELECT 1;')
        assert 'env' not in fake_subprocess.kwargs_for(['mysql'])


class TestInstalledProbes:
    def test_missing_client_reads_as_not_installed(self, fake_subprocess):
        fake_subprocess.script(['mysql'], raises=FileNotFoundError)
        assert DatabaseService.mysql_is_installed() is False

    def test_present_client_reads_as_installed(self, fake_subprocess):
        fake_subprocess.script(['mysql'], stdout='mysql  Ver 8.0\n')
        assert DatabaseService.mysql_is_installed() is True

    def test_a_failing_client_is_not_installed(self, fake_subprocess):
        fake_subprocess.script(['psql'], returncode=1, stderr='boom')
        assert DatabaseService.pg_is_installed() is False


class TestQueryTimeouts:
    """The explorer's bound is the one thing here that was already explicit."""

    def test_mysql_query_keeps_its_caller_supplied_timeout(self, fake_subprocess):
        fake_subprocess.script(['mysql'], stdout='')
        DatabaseService.mysql_execute_query('db', 'SELECT 1', timeout=7)
        assert fake_subprocess.kwargs_for(['mysql'])['timeout'] == 7

    def test_docker_exec_keeps_its_timeout(self, fake_subprocess, monkeypatch):
        # Pin the client so the only docker call is the query itself — the
        # client probe runs first and carries its own 10s bound.
        monkeypatch.setattr(DatabaseService, '_docker_db_client',
                            staticmethod(lambda name: 'mysql'))
        fake_subprocess.script(['docker'], stdout='')
        DatabaseService.docker_mysql_execute('c1', 'SELECT 1', timeout=11)
        assert fake_subprocess.kwargs_for(['docker'])['timeout'] == 11

    def test_the_client_probe_carries_its_own_short_bound(self, fake_subprocess,
                                                          monkeypatch):
        monkeypatch.setattr(DatabaseService, '_docker_client_cache', {})
        fake_subprocess.script(['docker'], stdout='mariadb Ver 11.4')
        DatabaseService._docker_db_client('c1')
        assert fake_subprocess.kwargs_for(['docker'])['timeout'] == 10

    def test_a_timed_out_query_reports_the_limit(self, fake_subprocess):
        """The hand-rolled handler said only "Query timed out"; the shared door
        names the bound, which is the difference between "your query is slow"
        and "something is wedged"."""
        fake_subprocess.script(['docker'],
                               raises=subprocess.TimeoutExpired('docker', 11))
        result = DatabaseService.docker_mysql_execute('c1', 'SELECT 1', timeout=11)
        assert result['success'] is False
        assert '11' in result['error']

    def test_unbounded_admin_calls_stay_unbounded(self, fake_subprocess):
        """mysql_execute has no timeout today; inheriting run_checked's 60s
        would cap a legitimately slow ALTER TABLE."""
        fake_subprocess.script(['mysql'], stdout='')
        DatabaseService.mysql_execute('ALTER TABLE big ADD COLUMN x INT;')
        assert fake_subprocess.kwargs_for(['mysql'])['timeout'] is None


class TestDockerClientProbe:
    """MariaDB 11 dropped the `mysql` symlink; the probe picks what is there."""

    def test_prefers_mariadb_when_present(self, fake_subprocess, monkeypatch):
        monkeypatch.setattr(DatabaseService, '_docker_client_cache', {})
        fake_subprocess.script(['docker'], stdout='mariadb Ver 11.4\n')
        assert DatabaseService._docker_db_client('c1') == 'mariadb'

    def test_falls_back_to_mysql_when_neither_answers(self, fake_subprocess, monkeypatch):
        monkeypatch.setattr(DatabaseService, '_docker_client_cache', {})
        fake_subprocess.script(['docker'], returncode=127, stderr='not found')
        assert DatabaseService._docker_db_client('c1') == 'mysql'

    def test_a_broken_docker_does_not_raise_out_of_the_probe(self, fake_subprocess,
                                                             monkeypatch):
        monkeypatch.setattr(DatabaseService, '_docker_client_cache', {})
        fake_subprocess.script(['docker'], raises=FileNotFoundError)
        assert DatabaseService._docker_db_client('c1') == 'mysql'


class TestPipelinesStayRaw:
    def test_the_only_remaining_raw_calls_are_pipelines(self):
        """A pipe is two processes; run_checked runs one. If this count moves,
        either a pipeline was migrated (it cannot be) or a new raw call landed.
        """
        import sys
        sys.path.insert(0, 'tests') if 'tests' not in sys.path else None
        from raw_subprocess_census import count_file

        hits = count_file('app/services/database_service.py')
        assert [name for _, name in hits] == ['subprocess.Popen'] * 8
