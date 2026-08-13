"""REST surface for the fleet doctor (plan 72 A.2).

The sweep engine itself is covered by test_fleet_doctor.py; this file covers the
routes that make it reachable:

* auth + admin gating on all three routes,
* ``POST /doctor/fleet/run`` is a 202 + job id (never a synchronous fan-out —
  the agent gateway registry is single-worker and in-memory),
* the report shape ``{'report': {'ran_at', 'servers': [...]}}`` including the
  ``key`` alias the panel renders findings by,
* an offline/unknown server degrades to a reported state rather than an error.
"""
import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.services import agent_registry as agent_registry_mod
from app.services.fleet_doctor_service import FLEET_DOCTOR_JOB_KIND, FleetDoctorService

registry = agent_registry_mod.agent_registry


@pytest.fixture
def server(app):
    from app import db
    from app.models.server import Server
    row = Server(name='box1', hostname='box', ip_address='203.0.113.10')
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture
def user_headers(app):
    """A non-admin (viewer) JWT — the negative case for @admin_required."""
    from app import db
    from app.models import User
    user = User(
        email='fleetpleb@test.local',
        username='fleetpleb',
        password_hash=generate_password_hash('x'),
        role=User.ROLE_VIEWER,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


def _seed_rows(server_id):
    from app.services.fleet_doctor_service import _row
    FleetDoctorService._persist(server_id, [
        _row('service.nginx', 'nginx service', 'ok', 'Running.'),
        _row('service.docker', 'docker service', 'fail', 'Not running.',
             repairable=True,
             repair_ref={'kind': 'fleet.service', 'server_id': server_id,
                         'name': 'docker'}),
    ])


# --------------------------------------------------------------------------- #
# Gating
# --------------------------------------------------------------------------- #

class TestGating:
    @pytest.mark.parametrize('method,path', [
        ('get', '/api/v1/doctor/fleet'),
        ('post', '/api/v1/doctor/fleet/run'),
        ('post', '/api/v1/doctor/fleet/repair'),
    ])
    def test_anonymous_is_rejected(self, client, method, path):
        resp = getattr(client, method)(path)
        assert resp.status_code in (401, 422)

    @pytest.mark.parametrize('method,path', [
        ('get', '/api/v1/doctor/fleet'),
        ('post', '/api/v1/doctor/fleet/run'),
        ('post', '/api/v1/doctor/fleet/repair'),
    ])
    def test_non_admin_is_forbidden(self, client, user_headers, method, path):
        resp = getattr(client, method)(path, headers=user_headers)
        assert resp.status_code == 403
        assert 'error' in resp.get_json()


# --------------------------------------------------------------------------- #
# GET /doctor/fleet
# --------------------------------------------------------------------------- #

class TestReport:
    def test_report_is_empty_but_well_shaped_with_no_servers(self, client, auth_headers):
        resp = client.get('/api/v1/doctor/fleet', headers=auth_headers)
        assert resp.status_code == 200
        report = resp.get_json()['report']
        assert report['servers'] == []
        assert report['ran_at'] is None

    def test_report_lists_a_server_with_no_rows_yet(self, client, auth_headers,
                                                    server, monkeypatch):
        monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
        report = client.get('/api/v1/doctor/fleet',
                            headers=auth_headers).get_json()['report']
        assert len(report['servers']) == 1
        entry = report['servers'][0]
        assert entry['server_id'] == server.id
        assert entry['name'] == 'box1'
        assert entry['connected'] is True
        assert entry['checks'] == []
        assert entry['ran_at'] is None

    def test_report_returns_rows_counts_and_the_key_alias(self, client, auth_headers,
                                                          server, monkeypatch):
        monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
        _seed_rows(server.id)

        report = client.get('/api/v1/doctor/fleet',
                            headers=auth_headers).get_json()['report']
        entry = report['servers'][0]
        assert entry['counts'] == {'ok': 1, 'warn': 0, 'fail': 1, 'error': 0}
        assert entry['ran_at'] and report['ran_at']

        checks = {c['key']: c for c in entry['checks']}
        # The panel renders findings field-driven off key/repairable/repair_ref.
        assert set(checks) == {'service.nginx', 'service.docker'}
        assert checks['service.docker']['check_key'] == 'service.docker'
        assert checks['service.docker']['repairable'] is True
        assert checks['service.docker']['repair_ref'] == {
            'kind': 'fleet.service', 'server_id': server.id, 'name': 'docker'}
        assert checks['service.nginx']['repairable'] is False

    def test_offline_server_is_reported_not_dropped(self, client, auth_headers,
                                                    server, monkeypatch):
        """An unreachable box keeps its last rows and reports connected=false."""
        _seed_rows(server.id)
        monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: False)

        report = client.get('/api/v1/doctor/fleet',
                            headers=auth_headers).get_json()['report']
        entry = report['servers'][0]
        assert entry['connected'] is False
        assert len(entry['checks']) == 2


# --------------------------------------------------------------------------- #
# POST /doctor/fleet/run
# --------------------------------------------------------------------------- #

class TestRun:
    def test_run_returns_202_with_a_job_id(self, client, auth_headers, monkeypatch):
        from app.jobs.models import Job

        # Never fan out on the request thread — if the route called the sweep
        # directly this would blow up.
        def _boom():
            raise AssertionError('run_fleet_doctor must not run on a request thread')

        monkeypatch.setattr(FleetDoctorService, 'run_fleet_doctor',
                            classmethod(lambda cls: _boom()))

        resp = client.post('/api/v1/doctor/fleet/run', headers=auth_headers)
        assert resp.status_code == 202
        job_id = resp.get_json()['job_id']
        assert job_id

        job = Job.query.get(job_id)
        assert job is not None
        assert job.kind == FLEET_DOCTOR_JOB_KIND
        assert job.status == Job.STATUS_PENDING

    def test_the_job_kind_has_a_registered_handler(self, app):
        from app.jobs import registry as job_registry
        FleetDoctorService.register_jobs()
        assert job_registry.is_registered(FLEET_DOCTOR_JOB_KIND)

    def test_the_fleet_sweep_schedule_is_seeded_and_staggered(self, app):
        from app.jobs.builtin_handlers import seed_builtin_schedules
        from app.jobs.models import ScheduledJob
        from app.services.doctor_service import DOCTOR_SCHEDULE_NAME
        from app.services.fleet_doctor_service import FLEET_DOCTOR_SCHEDULE_NAME

        seed_builtin_schedules()
        fleet = ScheduledJob.query.filter_by(name=FLEET_DOCTOR_SCHEDULE_NAME).first()
        host = ScheduledJob.query.filter_by(name=DOCTOR_SCHEDULE_NAME).first()
        assert fleet is not None and host is not None
        assert fleet.kind == FLEET_DOCTOR_JOB_KIND
        assert fleet.interval_seconds == 86400
        # Staggered: the fleet sweep must not fire alongside the host sweep.
        assert fleet.next_run_at > host.next_run_at


# --------------------------------------------------------------------------- #
# POST /doctor/fleet/repair
# --------------------------------------------------------------------------- #

class TestRepair:
    def test_empty_items_is_a_400(self, client, auth_headers):
        resp = client.post('/api/v1/doctor/fleet/repair', headers=auth_headers,
                           json={'items': []})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_non_allowlisted_kind_is_refused_as_a_result(self, client, auth_headers):
        resp = client.post('/api/v1/doctor/fleet/repair', headers=auth_headers,
                           json={'items': [{'kind': 'fleet.rm-rf',
                                            'server_id': 'x', 'name': 'nginx'}]})
        assert resp.status_code == 200
        result = resp.get_json()['results'][0]
        assert result['success'] is False
        assert result['code'] == 'NOT_ALLOWLISTED'

    def test_offline_agent_is_refused_not_errored(self, client, auth_headers,
                                                  server, monkeypatch):
        monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: False)
        resp = client.post('/api/v1/doctor/fleet/repair', headers=auth_headers,
                           json={'items': [{'kind': 'fleet.service',
                                            'server_id': server.id,
                                            'name': 'nginx'}]})
        assert resp.status_code == 200
        result = resp.get_json()['results'][0]
        assert result['success'] is False
        assert result['code'] == 'AGENT_OFFLINE'

    def test_allowlisted_repair_dispatches_and_reports_success(
            self, client, auth_headers, server, monkeypatch):
        monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
        monkeypatch.setattr(registry, 'has_capability', lambda sid, feat: True)
        sent = {}

        def _send(server_id, action, params, timeout=None, user_id=None):
            sent.update(server_id=server_id, action=action, params=params)
            return {'success': True}

        monkeypatch.setattr(registry, 'send_command', _send)

        resp = client.post('/api/v1/doctor/fleet/repair', headers=auth_headers,
                           json={'items': [{'kind': 'fleet.service',
                                            'server_id': server.id,
                                            'name': 'nginx'}]})
        assert resp.status_code == 200
        assert resp.get_json()['results'][0]['success'] is True
        assert sent['action'] == 'systemd:restart'
        assert sent['params'] == {'unit': 'nginx'}

    def test_one_bad_item_does_not_sink_the_batch(self, client, auth_headers,
                                                  server, monkeypatch):
        monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
        monkeypatch.setattr(registry, 'has_capability', lambda sid, feat: True)
        monkeypatch.setattr(
            registry, 'send_command',
            lambda server_id, action, params, timeout=None, user_id=None:
                {'success': True})

        resp = client.post('/api/v1/doctor/fleet/repair', headers=auth_headers,
                           json={'items': [
                               {'kind': 'fleet.service', 'server_id': server.id,
                                'name': 'not-a-unit'},
                               {'kind': 'fleet.service', 'server_id': server.id,
                                'name': 'nginx'},
                           ]})
        assert resp.status_code == 200
        results = resp.get_json()['results']
        assert [r['success'] for r in results] == [False, True]
        assert results[0]['code'] == 'NOT_ALLOWLISTED'
