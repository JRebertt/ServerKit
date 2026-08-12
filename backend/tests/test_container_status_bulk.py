"""Tests for the bulk (single ``docker ps``) container-status collection.

The point of this round: ``/status/apps`` used to spawn one ``docker compose ps``
per app plus one ``docker inspect`` per running container — ~120 processes for
30 apps — and the socket emitter re-paid that on a timer. These tests pin the
new contract: ONE collection pass per burst, shared between callers, dropped by
an explicit invalidate.
"""

import pytest

from app.services import container_status_service as css
from app.services.container_status_service import (
    STATUS_DEGRADED,
    STATUS_RUNNING_HEALTHY,
    STATUS_RUNNING_UNHEALTHY,
    STATUS_UNKNOWN,
)
from app.services.docker_service import DockerService


@pytest.fixture(autouse=True)
def clean_status_caches():
    """Both cache layers are process-global; isolate every test from the last."""
    from app.services import cache_service
    cache_service._memory_cache.clear()
    css.invalidate()
    yield
    cache_service._memory_cache.clear()
    css.invalidate()


def _row(**kw):
    """A `docker ps` row in the shape list_compose_containers returns."""
    row = {'id': '', 'name': '', 'state': '', 'status': '',
           'project': '', 'service': '', 'working_dir': '', 'config_files': ''}
    row.update(kw)
    return row


class _FakeApp:
    """Minimal duck-typed Application for the index lookups."""

    def __init__(self, id=1, root_path=None, container_id=None,
                 compose_file=None, server_id=None):
        self.id = id
        self.root_path = root_path
        self.container_id = container_id
        self.compose_file = compose_file
        self.server_id = server_id


# ---------------------------------------------------- health off `docker ps`

class TestHealthFromStatus:
    def test_healthy_suffix(self):
        assert css._health_from_status('Up 2 minutes (healthy)') == 'healthy'

    def test_unhealthy_suffix(self):
        assert css._health_from_status('Up 3 hours (unhealthy)') == 'unhealthy'

    def test_health_starting_suffix(self):
        assert css._health_from_status('Up 4 seconds (health: starting)') == 'starting'

    def test_no_healthcheck_is_none(self):
        # No suffix at all -> None, which _normalize_health reads as 'none'.
        assert css._health_from_status('Up 5 days') is None
        assert css._health_from_status('') is None
        assert css._health_from_status(None) is None

    def test_exit_code_parens_are_not_health(self):
        # 'Exited (137) 2 minutes ago' must not be mistaken for a health value.
        assert css._health_from_status('Exited (137) 2 minutes ago') is None
        assert css._health_from_status('Restarting (1) 5 seconds ago') is None


# ------------------------------------------------------------- the index

class TestContainerIndex:
    def test_matches_by_compose_working_dir(self):
        index = css._ContainerIndex([
            _row(id='a1', name='blog-web-1', state='running', status='Up 2 minutes',
                 project='blog', service='web', working_dir='/srv/apps/blog'),
        ])
        rows = index.for_app(_FakeApp(root_path='/srv/apps/blog'))
        assert [r['id'] for r in rows] == ['a1']

    def test_working_dir_match_survives_trailing_slash(self):
        index = css._ContainerIndex([
            _row(id='a1', name='blog-web-1', state='running',
                 working_dir='/srv/apps/blog/'),
        ])
        assert index.for_app(_FakeApp(root_path='/srv/apps/blog')) != []

    def test_falls_back_to_derived_project_name(self):
        """A custom COMPOSE_PROJECT_NAME still matches through working_dir; an
        older compose with no working_dir label matches through the name."""
        index = css._ContainerIndex([
            _row(id='b1', name='myblog-web-1', state='running', project='myblog'),
        ])
        # Directory 'My_Blog!' normalizes to compose's 'my_blog' — no match,
        # while a directory literally named 'myblog' does match.
        assert index.for_app(_FakeApp(root_path='/srv/apps/myblog')) != []
        assert index.for_app(_FakeApp(root_path='/srv/apps/other')) == []

    def test_matches_by_config_files_directory(self):
        index = css._ContainerIndex([
            _row(id='c1', name='api-web-1', state='running',
                 config_files='/srv/apps/api/docker-compose.yml'),
        ])
        assert index.for_app(_FakeApp(root_path='/srv/apps/api')) != []

    def test_matches_bare_container_id(self):
        index = css._ContainerIndex([
            _row(id='d' * 64, name='lonely', state='running'),
        ])
        app = _FakeApp(root_path=None, container_id='d' * 64)
        assert index.for_app(app) != []
        # ...and by the short id apps often store.
        assert index.for_app(_FakeApp(container_id='d' * 12)) != []
        # ...and by name.
        assert index.for_app(_FakeApp(container_id='lonely')) != []

    def test_unmatched_app_gets_nothing(self):
        index = css._ContainerIndex([_row(id='x', working_dir='/elsewhere')])
        assert index.for_app(_FakeApp(root_path='/srv/apps/nope')) == []

    def test_one_container_is_not_double_counted(self):
        """A container is indexed under several keys; a lookup must still see it
        once, or 'total' would inflate."""
        index = css._ContainerIndex([
            _row(id='e1', name='shop-web-1', state='running', project='shop',
                 working_dir='/srv/apps/shop',
                 config_files='/srv/apps/shop/docker-compose.yml'),
        ])
        rows = index.for_app(_FakeApp(root_path='/srv/apps/shop'))
        assert len(rows) == 1


class TestStatesFromIndexRows:
    def test_state_and_health_are_carried_through(self):
        states = css._states_from_index_rows([
            _row(id='1', name='/web', state='running',
                 status='Up 2 minutes (unhealthy)', service='web'),
        ])
        assert states == [{'id': '1', 'name': 'web', 'service': 'web',
                           'state': 'running', 'health': 'unhealthy'}]

    def test_state_derived_from_status_when_column_missing(self):
        states = css._states_from_index_rows([
            _row(id='1', name='web', state='', status='Up 9 minutes'),
        ])
        assert states[0]['state'] == 'running'

    def test_aggregates_to_the_same_enum_as_before(self):
        rows = [
            _row(id='1', name='web', state='running', status='Up 1 minute', service='web'),
            _row(id='2', name='db', state='exited', status='Exited (0) 1 minute ago', service='db'),
        ]
        agg = css.aggregate_status(css._states_from_index_rows(rows))
        assert agg['status'] == STATUS_DEGRADED
        assert agg['total'] == 2


# ------------------------------------------------- one pass for every app

@pytest.fixture
def three_apps(app):
    """Three local compose apps sharing one Docker host."""
    from app import db
    from app.models import Application, User
    from werkzeug.security import generate_password_hash

    with app.app_context():
        owner = User.query.first()
        if owner is None:
            owner = User(email='statusprobe@t.local', username='statusprobe',
                         password_hash=generate_password_hash('x'),
                         role='admin', is_active=True)
            db.session.add(owner)
            db.session.commit()
        rows = []
        for name in ('alpha', 'beta', 'gamma'):
            row = Application(name=name, app_type='docker', status='running',
                              user_id=owner.id, root_path=f'/srv/apps/{name}',
                              compose_file='docker-compose.yml')
            db.session.add(row)
            rows.append(row)
        db.session.commit()
        yield rows


class _Collector:
    """Counts how many times the bulk `docker ps` was actually run."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def __call__(self, all_containers=False):
        self.calls += 1
        return list(self.rows)


def _install_collector(monkeypatch, rows):
    collector = _Collector(rows)
    monkeypatch.setattr(DockerService, 'list_compose_containers',
                        staticmethod(collector))
    # Any use of these two would mean we regressed to the per-app shape.
    def _boom(*a, **kw):  # pragma: no cover - only runs on regression
        raise AssertionError('per-app docker subprocess was spawned')
    monkeypatch.setattr(DockerService, 'compose_ps', staticmethod(_boom))
    monkeypatch.setattr(DockerService, 'get_container', staticmethod(_boom))
    return collector


class TestSingleCollectionPass:
    def test_list_app_statuses_runs_docker_ps_once_for_all_apps(
            self, app, three_apps, monkeypatch):
        rows = []
        for name in ('alpha', 'beta', 'gamma'):
            rows.append(_row(id=f'{name}-web', name=f'{name}-web-1', state='running',
                             status='Up 2 minutes (healthy)', project=name,
                             service='web', working_dir=f'/srv/apps/{name}'))
            rows.append(_row(id=f'{name}-db', name=f'{name}-db-1', state='running',
                             status='Up 2 minutes', project=name,
                             service='db', working_dir=f'/srv/apps/{name}'))
        collector = _install_collector(monkeypatch, rows)

        with app.app_context():
            summaries = css.list_app_statuses()

        # 3 apps x 2 containers = 6 containers. The old shape cost 3 compose-ps
        # spawns + 6 inspects = 9; the new one costs exactly 1.
        assert collector.calls == 1
        assert len(summaries) == 3
        assert {s['status'] for s in summaries} == {STATUS_RUNNING_HEALTHY}
        assert all(s['total'] == 2 and s['healthy'] == 2 for s in summaries)

    def test_response_shape_is_unchanged(self, app, three_apps, monkeypatch):
        _install_collector(monkeypatch, [])
        with app.app_context():
            summaries = css.list_app_statuses()
        assert all(set(s) == {'app_id', 'status', 'total', 'healthy'}
                   for s in summaries)

    def test_unhealthy_is_seen_without_any_inspect(self, app, three_apps, monkeypatch):
        """Health used to cost one `docker inspect` per running container. It now
        comes off the ps STATUS column — get_container is wired to explode."""
        _install_collector(monkeypatch, [
            _row(id='a1', name='alpha-web-1', state='running',
                 status='Up 2 minutes (unhealthy)', project='alpha',
                 service='web', working_dir='/srv/apps/alpha'),
        ])
        with app.app_context():
            result = css.get_app_status(three_apps[0].id, use_cache=False)
        assert result['status'] == STATUS_RUNNING_UNHEALTHY

    def test_app_with_no_containers_is_unknown(self, app, three_apps, monkeypatch):
        _install_collector(monkeypatch, [])
        with app.app_context():
            result = css.get_app_status(three_apps[0].id, use_cache=False)
        assert result['status'] == STATUS_UNKNOWN
        assert result['total'] == 0
        assert result['app_id'] == three_apps[0].id
        assert result['kind'] == 'app'


class TestSnapshotSharing:
    def test_burst_of_callers_shares_one_collection(self, app, three_apps, monkeypatch):
        """The HTTP route and the socket emitter must not each trigger their own
        pass — that is what made the cost un-amortised."""
        collector = _install_collector(monkeypatch, [])
        with app.app_context():
            css.list_app_statuses()          # HTTP /status/apps
            css._last_app_statuses.clear()
            css.get_changed_app_statuses()   # socket emitter tick
            css.list_app_statuses()
        assert collector.calls == 1
        css._last_app_statuses.clear()

    def test_invalidate_forces_a_fresh_collection(self, app, three_apps, monkeypatch):
        """A stale status is worse than a slow one: an explicit start/stop/deploy
        must drop the snapshot, not wait out its TTL."""
        collector = _install_collector(monkeypatch, [])
        with app.app_context():
            css.list_app_statuses()
            assert collector.calls == 1
            css.invalidate()
            css.list_app_statuses()
        assert collector.calls == 2

    def test_invalidate_for_one_app_clears_its_cached_result(
            self, app, three_apps, monkeypatch):
        _install_collector(monkeypatch, [
            _row(id='a1', name='alpha-web-1', state='running',
                 status='Up 1 minute', working_dir='/srv/apps/alpha'),
        ])
        app_id = three_apps[0].id
        with app.app_context():
            first = css.get_app_status(app_id)
            assert first['status'] == STATUS_RUNNING_HEALTHY

            # Same app, now stopped. Without invalidation the 8s per-app cache
            # would keep serving 'running'.
            _install_collector(monkeypatch, [])
            assert css.get_app_status(app_id)['status'] == STATUS_RUNNING_HEALTHY
            css.invalidate(app_id)
            assert css.get_app_status(app_id)['status'] == STATUS_UNKNOWN

    def test_use_cache_false_bypasses_the_snapshot_too(
            self, app, three_apps, monkeypatch):
        """'Give me the truth now' has to reach Docker, not a 3s-old snapshot."""
        collector = _install_collector(monkeypatch, [])
        with app.app_context():
            css.get_app_status(three_apps[0].id, use_cache=False)
            css.get_app_status(three_apps[0].id, use_cache=False)
        assert collector.calls == 2


class TestRemoteAppsAreNotAnsweredFromTheLocalHost:
    def test_remote_app_never_reads_the_local_snapshot(self, app, monkeypatch):
        """An app on an agent-managed server must not inherit a local container
        that happens to share its project directory."""
        called = {}

        def _fake_remote(a):
            called['app'] = a
            return []

        monkeypatch.setattr(css, '_gather_remote_app_container_states', _fake_remote)
        index = css._ContainerIndex([
            _row(id='local1', name='alpha-web-1', state='running',
                 working_dir='/srv/apps/alpha'),
        ])
        remote_app = _FakeApp(id=7, root_path='/srv/apps/alpha', server_id='srv-abc')
        assert css._gather_app_container_states(remote_app, index=index) == []
        assert called['app'] is remote_app

    def test_offline_agent_costs_nothing(self, app, monkeypatch):
        """send_command blocks for up to 30s; the 5s broadcast loop cannot pay
        that for a server that is not even connected."""
        from app.services import agent_registry as agent_registry_module
        from app.services.remote_docker_service import RemoteDockerService

        monkeypatch.setattr(agent_registry_module.agent_registry, 'get_agent',
                            lambda server_id: None)

        def _boom(*a, **kw):  # pragma: no cover - only runs on regression
            raise AssertionError('agent was contacted for an offline server')

        monkeypatch.setattr(RemoteDockerService, 'compose_ps', staticmethod(_boom))
        remote_app = _FakeApp(id=8, root_path='/srv/apps/alpha', server_id='srv-off')
        with app.app_context():
            assert css._gather_remote_app_container_states(remote_app) == []


# ----------------------------------------------- the docker ps call itself

class TestListComposeContainers:
    def test_parses_tab_delimited_rows(self, monkeypatch):
        import app.services.docker_service as docker_module

        captured = {}

        class _Result:
            returncode = 0
            stdout = (
                'abc123\tblog-web-1\trunning\tUp 2 minutes (healthy)\t'
                'blog\tweb\t/srv/apps/blog\t/srv/apps/blog/docker-compose.yml\n'
                'def456\tblog-db-1\trunning\tUp 2 minutes\t'
                'blog\tdb\t/srv/apps/blog\t/srv/apps/blog/docker-compose.yml\n'
            )
            stderr = ''

        def _fake_run(cmd, **kwargs):
            captured['cmd'] = cmd
            return _Result()

        monkeypatch.setattr(docker_module.subprocess, 'run', _fake_run)
        rows = DockerService.list_compose_containers()

        assert len(rows) == 2
        assert rows[0]['project'] == 'blog'
        assert rows[0]['service'] == 'web'
        assert rows[0]['working_dir'] == '/srv/apps/blog'
        assert rows[0]['status'] == 'Up 2 minutes (healthy)'
        # One process, and no `-a`: matching `docker compose ps`'s default keeps
        # a fully-stopped project reporting exactly what it reported before.
        assert captured['cmd'][:2] == ['docker', 'ps']
        assert '-a' not in captured['cmd']

    def test_missing_labels_do_not_drop_the_row(self, monkeypatch):
        import app.services.docker_service as docker_module

        class _Result:
            returncode = 0
            # A non-compose container: trailing label columns are empty, and
            # some docker versions render them as '<no value>'.
            stdout = 'zzz\tsolo\trunning\tUp 1 hour\t<no value>\t<no value>\t\t\n'
            stderr = ''

        monkeypatch.setattr(docker_module.subprocess, 'run',
                            lambda cmd, **kw: _Result())
        rows = DockerService.list_compose_containers()
        assert len(rows) == 1
        assert rows[0]['name'] == 'solo'
        assert rows[0]['project'] == ''

    def test_docker_failure_is_an_empty_list(self, monkeypatch):
        import app.services.docker_service as docker_module

        class _Result:
            returncode = 1
            stdout = ''
            stderr = 'Cannot connect to the Docker daemon'

        monkeypatch.setattr(docker_module.subprocess, 'run',
                            lambda cmd, **kw: _Result())
        assert DockerService.list_compose_containers() == []

    def test_exception_is_an_empty_list(self, monkeypatch):
        import app.services.docker_service as docker_module

        def _explode(*a, **kw):
            raise OSError('docker not found')

        monkeypatch.setattr(docker_module.subprocess, 'run', _explode)
        assert DockerService.list_compose_containers() == []
