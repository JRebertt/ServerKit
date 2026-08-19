"""Curated DB config tuner — suggestion formulas, validation, drop-in
rendering, apply/rollback flow (docker + fs stubbed), inspect parsing."""
import os

import pytest

from app.exceptions import (
    DependencyUnavailableError,
    NotFoundError,
    ValidationError,
)

from app.services.db_config_tuner_service import (
    CURATED_SETTINGS, MYSQL_DROPIN_PATH, DbConfigTunerService as S,
)


MYSQL_TARGET = {'container': 'app-db-1', 'engine': 'mysql', 'user': 'root', 'password': 'pw'}
PG_TARGET = {'container': 'app-pg-1', 'engine': 'postgresql', 'user': 'postgres', 'password': None}


@pytest.fixture
def tuner(tmp_path, monkeypatch):
    """Stub every choke point; record calls. Returns a mutable control dict."""
    ctl = {
        'docker_calls': [],
        'sql_calls': [],
        'restarts': [],
        'sql': lambda target, sql: {'success': True, 'output': '1\n', 'error': None},
        'docker': lambda args: {'success': True, 'output': '', 'error': None},
        'restart_ok': True,
    }
    monkeypatch.setattr(S, 'STATE_DIR', str(tmp_path))
    monkeypatch.setattr(S, '_linux_supported', classmethod(lambda cls: True))
    monkeypatch.setattr(S, '_sleep', classmethod(lambda cls, s: None))
    monkeypatch.setattr(S, '_host_ram_mb', classmethod(lambda cls: 8192))

    def fake_docker(cls, args, timeout=60):
        ctl['docker_calls'].append(list(args))
        return ctl['docker'](list(args))

    def fake_sql(cls, target, sql):
        ctl['sql_calls'].append(sql)
        return ctl['sql'](target, sql)

    def fake_restart(cls, container):
        ctl['restarts'].append(container)
        return {'success': ctl['restart_ok']}

    monkeypatch.setattr(S, '_docker', classmethod(fake_docker))
    monkeypatch.setattr(S, '_exec_sql', classmethod(fake_sql))
    monkeypatch.setattr(S, '_restart', classmethod(fake_restart))
    return ctl


# ── suggestion formulas (deterministic RAM inputs) ──────────────────────────

def test_mysql_suggestions_8g_shared():
    assert S.suggest_value('mysql', 'innodb_buffer_pool_size', 8192) == 2048   # 25%
    assert S.suggest_value('mysql', 'max_connections', 8192) == 682            # ram/12
    assert S.suggest_value('mysql', 'slow_query_log', 8192) == 1
    assert S.suggest_value('mysql', 'long_query_time', 8192) == 1.0
    assert S.suggest_value('mysql', 'tmp_table_size', 8192) == 164             # 2%
    assert S.suggest_value('mysql', 'max_heap_table_size', 8192) == 164
    assert S.suggest_value('mysql', 'innodb_log_file_size', 8192) == 512       # pool/4


def test_mysql_suggestions_dedicated_doubles_pool():
    assert S.suggest_value('mysql', 'innodb_buffer_pool_size', 8192, is_dedicated=True) == 4096
    assert S.suggest_value('mysql', 'innodb_log_file_size', 8192, is_dedicated=True) == 1024


def test_pg_suggestions_8g():
    assert S.suggest_value('postgresql', 'shared_buffers', 8192) == 2048           # 25%
    assert S.suggest_value('postgresql', 'work_mem', 8192) == 128                  # ram/64
    assert S.suggest_value('postgresql', 'maintenance_work_mem', 8192) == 410      # 5%
    assert S.suggest_value('postgresql', 'max_connections', 8192) == 100
    assert S.suggest_value('postgresql', 'max_connections', 8192, is_dedicated=True) == 200
    assert S.suggest_value('postgresql', 'effective_cache_size', 8192) == 4096     # 50%
    assert S.suggest_value('postgresql', 'effective_cache_size', 8192, is_dedicated=True) == 6144
    assert S.suggest_value('postgresql', 'log_min_duration_statement', 8192) == 1000


def test_suggestions_clamped_to_safe_range():
    # Tiny box: 25% of 256MB would be 64MB — below shared_buffers' 128MB floor.
    assert S.suggest_value('postgresql', 'shared_buffers', 256) == 128
    # Monster box: pg shared_buffers capped at 16GB.
    assert S.suggest_value('postgresql', 'shared_buffers', 1024 * 1024) == 16384
    assert S.suggest_value('mysql', 'innodb_buffer_pool_size', 256) == 128


# ── validation ───────────────────────────────────────────────────────────────

def test_validate_rejects_unknown_key():
    err = S.validate_settings('mysql', {'innodb_evil_flag': 1})
    assert err and 'innodb_evil_flag' in err


def test_validate_rejects_out_of_range():
    err = S.validate_settings('mysql', {'max_connections': 999999})
    assert err and 'max_connections' in err
    err = S.validate_settings('postgresql', {'work_mem': 1})
    assert err and 'work_mem' in err


def test_validate_rejects_non_numeric_and_empty():
    assert S.validate_settings('mysql', {'max_connections': 'lots'})
    assert S.validate_settings('mysql', {})
    assert S.validate_settings('mysql', None)


def test_validate_accepts_and_coerces():
    settings = {'max_connections': '500', 'long_query_time': 2.5}
    assert S.validate_settings('mysql', settings) is None
    assert settings['max_connections'] == 500
    assert settings['long_query_time'] == 2.5


def test_apply_surfaces_validation_error(tuner):
    with pytest.raises(ValidationError, match='not_a_setting'):
        S.apply(MYSQL_TARGET, {'not_a_setting': 1})
    with pytest.raises(ValidationError):
        S.apply(MYSQL_TARGET, {'innodb_buffer_pool_size': 1})  # below 128MB floor


# ── drop-in rendering ────────────────────────────────────────────────────────

def test_render_mysql_dropin_content():
    content = S.render_mysql_dropin({
        'innodb_buffer_pool_size': 2048,
        'slow_query_log': 1,
        'long_query_time': 1.0,
        'max_connections': 300,
    })
    assert content.startswith('# Managed by ServerKit')
    assert '[mysqld]' in content
    assert 'innodb_buffer_pool_size = 2048M' in content   # MB → M suffix
    assert 'slow_query_log = 1' in content
    assert 'long_query_time = 1.0' in content
    assert 'max_connections = 300' in content
    assert content.endswith('\n')


def test_pg_literals():
    cat = CURATED_SETTINGS['postgresql']
    assert S._pg_literal(cat['shared_buffers'], 2048) == "'2048MB'"
    assert S._pg_literal(cat['max_connections'], 200) == '200'
    assert S._pg_literal(cat['log_min_duration_statement'], 1000) == '1000'


# ── inspect parsing ──────────────────────────────────────────────────────────

def test_inspect_mysql_parses_show_variables(tuner):
    output = (
        'innodb_buffer_pool_size\t134217728\n'      # 128MB in bytes
        'innodb_log_file_size\t50331648\n'          # 48MB
        'long_query_time\t10.000000\n'
        'max_connections\t151\n'
        'max_heap_table_size\t16777216\n'
        'slow_query_log\tOFF\n'
        'tmp_table_size\t16777216\n'
    )
    tuner['sql'] = lambda t, sql: {'success': True, 'output': output, 'error': None}
    # No container memory limit → falls back to host RAM (stubbed 8192).
    tuner['docker'] = lambda args: {'success': True, 'output': '0\n', 'error': None}

    result = S.inspect(MYSQL_TARGET)
    assert result['engine'] == 'mysql'
    assert result['ram_mb'] == 8192 and result['ram_source'] == 'host_total'
    rows = {r['key']: r for r in result['settings']}
    assert rows['innodb_buffer_pool_size']['current'] == 128
    assert rows['innodb_buffer_pool_size']['suggested'] == 2048
    assert rows['innodb_buffer_pool_size']['differs'] is True
    assert rows['slow_query_log']['current'] == 0
    assert rows['long_query_time']['current'] == 10.0
    assert rows['max_connections']['current'] == 151
    assert 'innodb_buffer_pool_size' in result['diff']
    assert result['can_rollback'] is False


def test_inspect_pg_parses_pg_settings_units(tuner):
    output = (
        'effective_cache_size\t524288\t8kB\n'       # 4096 MB
        'log_min_duration_statement\t-1\tms\n'
        'maintenance_work_mem\t65536\tkB\n'         # 64 MB
        'max_connections\t100\t\n'
        'shared_buffers\t16384\t8kB\n'              # 128 MB
        'work_mem\t4096\tkB\n'                      # 4 MB
    )
    tuner['sql'] = lambda t, sql: {'success': True, 'output': output, 'error': None}
    # Container has a 4GB memory limit.
    tuner['docker'] = lambda args: {'success': True, 'output': str(4 * 1024 ** 3) + '\n',
                                    'error': None}

    result = S.inspect(PG_TARGET)
    assert result['ram_mb'] == 4096 and result['ram_source'] == 'container_limit'
    rows = {r['key']: r for r in result['settings']}
    assert rows['shared_buffers']['current'] == 128
    assert rows['shared_buffers']['suggested'] == 1024        # 25% of 4096
    assert rows['effective_cache_size']['current'] == 4096
    assert rows['maintenance_work_mem']['current'] == 64
    assert rows['work_mem']['current'] == 4
    assert rows['max_connections']['current'] == 100
    assert rows['max_connections']['differs'] is False


def test_inspect_engine_query_failure_is_clean_error(tuner):
    tuner['sql'] = lambda t, sql: {'success': False, 'output': '', 'error': 'access denied'}
    with pytest.raises(DependencyUnavailableError, match='access denied'):
        S.inspect(MYSQL_TARGET)


def test_non_linux_is_clean_error(tuner, monkeypatch):
    monkeypatch.setattr(S, '_linux_supported', classmethod(lambda cls: False))
    for op in (lambda: S.inspect(MYSQL_TARGET),
               lambda: S.apply(MYSQL_TARGET, {'max_connections': 300}),
               lambda: S.rollback(MYSQL_TARGET)):
        with pytest.raises(ValidationError, match='Linux'):
            op()


# ── apply / rollback flow (mysql) ────────────────────────────────────────────

def _mysql_docker_stub(ctl, existing_dropin=None):
    """docker stub that emulates cp-out (existing drop-in or absent) and
    accepts cp-in / exec rm."""
    def docker(args):
        if args[0] == 'cp' and args[1].startswith('app-db-1:'):
            if existing_dropin is None:
                return {'success': False, 'output': '', 'error': 'no such file'}
            with open(args[2], 'w') as fh:
                fh.write(existing_dropin)
            return {'success': True, 'output': '', 'error': None}
        return {'success': True, 'output': '', 'error': None}
    ctl['docker'] = docker


def test_apply_mysql_happy_path(tuner, tmp_path):
    _mysql_docker_stub(tuner, existing_dropin='[mysqld]\nmax_connections = 100\n')
    result = S.apply(MYSQL_TARGET, {'max_connections': 300, 'slow_query_log': 1})

    assert result.get('success') is True
    assert result['applied'] == {'max_connections': 300, 'slow_query_log': 1}
    assert tuner['restarts'] == ['app-db-1']

    # Timestamped backup of the previous drop-in was kept on the panel host.
    state = tmp_path / 'mysql' / 'app-db-1'
    backups = [f for f in os.listdir(state) if f.startswith('previous-') and f.endswith('.cnf')]
    assert len(backups) == 1
    assert (state / backups[0]).read_text() == '[mysqld]\nmax_connections = 100\n'

    # The staged drop-in was rendered and docker cp'd into the container.
    staged = state / 'serverkit-tuner.cnf'
    assert 'max_connections = 300' in staged.read_text()
    assert ['cp', str(staged), f'app-db-1:{MYSQL_DROPIN_PATH}'] in tuner['docker_calls']

    # And inspect now offers a rollback.
    assert S._latest_backup(MYSQL_TARGET) is not None


def test_apply_mysql_first_time_records_absent_marker(tuner, tmp_path):
    _mysql_docker_stub(tuner, existing_dropin=None)
    result = S.apply(MYSQL_TARGET, {'max_connections': 300})
    assert result.get('success') is True
    state = tmp_path / 'mysql' / 'app-db-1'
    assert any(f.endswith('.absent') for f in os.listdir(state))


def test_apply_mysql_ping_failure_rolls_back(tuner):
    _mysql_docker_stub(tuner, existing_dropin='[mysqld]\nold = 1\n')
    tuner['sql'] = lambda t, sql: {'success': False, 'output': '', 'error': 'down'}

    with pytest.raises(DependencyUnavailableError, match='restored'):
        S.apply(MYSQL_TARGET, {'max_connections': 300})
    # Restarted twice: once for the apply, once after restoring the backup.
    assert tuner['restarts'] == ['app-db-1', 'app-db-1']
    # The backup was cp'd back into the container.
    restore_calls = [c for c in tuner['docker_calls']
                     if c[0] == 'cp' and c[2] == f'app-db-1:{MYSQL_DROPIN_PATH}'
                     and 'previous-' in c[1]]
    assert restore_calls


def test_apply_mysql_restart_failure_restores_file(tuner):
    _mysql_docker_stub(tuner, existing_dropin='[mysqld]\nold = 1\n')
    tuner['restart_ok'] = False
    with pytest.raises(DependencyUnavailableError, match='restored'):
        S.apply(MYSQL_TARGET, {'max_connections': 300})


def test_rollback_mysql_restores_and_consumes_backup(tuner):
    _mysql_docker_stub(tuner, existing_dropin='[mysqld]\nold = 1\n')
    assert S.apply(MYSQL_TARGET, {'max_connections': 300}).get('success')
    tuner['restarts'].clear()

    result = S.rollback(MYSQL_TARGET)
    assert result.get('success') is True
    assert tuner['restarts'] == ['app-db-1']
    # Backup consumed — nothing further to roll back to.
    assert S._latest_backup(MYSQL_TARGET) is None
    with pytest.raises(NotFoundError):
        S.rollback(MYSQL_TARGET)


def test_rollback_mysql_absent_marker_deletes_dropin(tuner):
    _mysql_docker_stub(tuner, existing_dropin=None)
    assert S.apply(MYSQL_TARGET, {'max_connections': 300}).get('success')

    result = S.rollback(MYSQL_TARGET)
    assert result.get('success') is True
    assert ['exec', 'app-db-1', 'rm', '-f', MYSQL_DROPIN_PATH] in tuner['docker_calls']


def test_rollback_without_backup_is_clean_error(tuner):
    with pytest.raises(NotFoundError):
        S.rollback(MYSQL_TARGET)


# ── apply / rollback flow (postgresql) ───────────────────────────────────────

def _pg_sql_stub(ctl, alter_ok=True):
    def sql(target, statement):
        if statement.startswith('SHOW data_directory'):
            return {'success': True, 'output': '/var/lib/postgresql/data\n', 'error': None}
        if statement.startswith('ALTER SYSTEM'):
            return {'success': alter_ok, 'output': '',
                    'error': None if alter_ok else 'permission denied'}
        return {'success': True, 'output': '1\n', 'error': None}
    ctl['sql'] = sql


def test_apply_pg_happy_path(tuner, tmp_path):
    _pg_sql_stub(tuner)

    def docker(args):
        if args[0] == 'cp' and args[1].startswith('app-pg-1:'):
            with open(args[2], 'w') as fh:
                fh.write("shared_buffers = '128MB'\n")
            return {'success': True, 'output': '', 'error': None}
        return {'success': True, 'output': '', 'error': None}
    tuner['docker'] = docker

    result = S.apply(PG_TARGET, {'shared_buffers': 1024, 'max_connections': 200})
    assert result.get('success') is True
    assert tuner['restarts'] == ['app-pg-1']
    # ALTER SYSTEM per key, size rendered with MB unit.
    alters = [s for s in tuner['sql_calls'] if s.startswith('ALTER SYSTEM')]
    assert "ALTER SYSTEM SET shared_buffers = '1024MB';" in alters
    assert 'ALTER SYSTEM SET max_connections = 200;' in alters
    # auto.conf backed up + metadata saved for SQL-free rollback.
    state = tmp_path / 'postgresql' / 'app-pg-1'
    assert any(f.endswith('.auto.conf') for f in os.listdir(state))
    assert (state / 'applied.json').exists()


def test_apply_pg_alter_failure_restores_conf_without_restart(tuner):
    _pg_sql_stub(tuner, alter_ok=False)
    with pytest.raises(DependencyUnavailableError, match='ALTER SYSTEM'):
        S.apply(PG_TARGET, {'shared_buffers': 1024})
    assert tuner['restarts'] == []   # nothing took effect, no restart


def test_rollback_pg_uses_saved_auto_conf_path(tuner):
    _pg_sql_stub(tuner)

    def docker(args):
        if args[0] == 'cp' and args[1].startswith('app-pg-1:'):
            with open(args[2], 'w') as fh:
                fh.write("shared_buffers = '128MB'\n")
        return {'success': True, 'output': '', 'error': None}
    tuner['docker'] = docker

    assert S.apply(PG_TARGET, {'shared_buffers': 1024}).get('success')
    tuner['docker_calls'].clear()

    result = S.rollback(PG_TARGET)
    assert result.get('success') is True
    restore = [c for c in tuner['docker_calls']
               if c[0] in ('cp', 'exec') and
               'postgresql.auto.conf' in ' '.join(c)]
    assert restore
