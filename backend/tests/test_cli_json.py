"""--json output on the read-only CLI verbs: every listed command must emit
parseable JSON on stdout (scriptable/monitorable CLI), and the two flags that
conflict with table-only extras must refuse loudly."""
import json

import pytest
from click.testing import CliRunner

import cli as serverkit_cli


def _all_output(result):
    out = result.output
    try:
        out += result.stderr
    except (ValueError, AttributeError):
        pass
    return out


def _json_out(result):
    assert result.exit_code == 0, _all_output(result)
    return json.loads(result.output)


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path):
        self.calls.append(('GET', path, None))
        return self.responses[path]

    def post(self, path, json_body=None):
        self.calls.append(('POST', path, json_body))
        return self.responses[path]


@pytest.fixture
def fake_api(monkeypatch):
    def _install(responses):
        fake = FakeClient(responses)
        monkeypatch.setattr(serverkit_cli, '_api_client', lambda with_token=True: fake)
        return fake
    return _install


# ── API-backed verbs ─────────────────────────────────────────────────────────

def test_status_json(fake_api):
    fake_api({'/system/health': {'status': 'ok', 'service': 'serverkit'}})
    result = CliRunner().invoke(serverkit_cli.cli, ['status', '--json'])
    data = _json_out(result)
    assert data['health']['status'] == 'ok'
    assert data['version']


def test_doctor_json_emits_raw_report(fake_api):
    fake_api({'/doctor/run': {'report': {'checks': [
        {'key': 'nginx', 'title': 'Nginx config', 'status': 'ok', 'detail': ''},
        {'key': 'ssl', 'title': 'SSL cert', 'status': 'fail', 'detail': 'expired'},
    ]}}})
    result = CliRunner().invoke(serverkit_cli.cli, ['doctor', '--json'])
    data = _json_out(result)
    assert [c['key'] for c in data['checks']] == ['nginx', 'ssl']


def test_doctor_json_refuses_repair(fake_api):
    fake_api({})
    result = CliRunner().invoke(serverkit_cli.cli, ['doctor', '--json', '--repair'])
    assert result.exit_code == 1
    assert '--repair' in _all_output(result)


def test_services_list_json(fake_api):
    fake_api({'/processes/services': {'services': [
        {'name': 'nginx', 'status': 'running', 'pid': 123},
    ]}})
    result = CliRunner().invoke(serverkit_cli.cli, ['services', 'list', '--json'])
    data = _json_out(result)
    assert data['services'][0]['name'] == 'nginx'


def test_apps_list_json(fake_api):
    fake_api({'/apps': {'apps': [
        {'name': 'blog', 'app_type': 'wordpress', 'status': 'running'},
    ]}})
    result = CliRunner().invoke(serverkit_cli.cli, ['apps', 'list', '--json'])
    data = _json_out(result)
    assert data['apps'][0]['app_type'] == 'wordpress'


def test_manifest_plan_json(fake_api):
    fake = fake_api({'/manifests/plan': {'plan': {
        'steps': [{'type': 'create', 'service': 'web', 'description': 'create app web'}],
        'step_count': 1,
        'summary': '1 change planned',
        'issues': [],
    }}})
    result = CliRunner().invoke(
        serverkit_cli.cli, ['manifest', 'plan', '--project', '7', '--json'])
    data = _json_out(result)
    assert ('POST', '/manifests/plan', {'project_id': 7}) in fake.calls
    assert data['step_count'] == 1
    assert data['steps'][0]['service'] == 'web'


# ── DIRECT (in-process) verbs ────────────────────────────────────────────────

def test_list_users_json(app):
    from app import db
    from app.models import User

    user = User(email='j@test.local', username='juan', role='admin', is_active=True)
    user.set_password('x')
    db.session.add(user)
    db.session.commit()

    result = CliRunner().invoke(serverkit_cli.cli, ['list-users', '--json'])
    data = _json_out(result)
    assert data['users'] == [{
        'id': user.id,
        'username': 'juan',
        'email': 'j@test.local',
        'role': 'admin',
        'is_active': True,
        'is_locked': False,
    }]


def test_list_apps_json_empty(app):
    result = CliRunner().invoke(serverkit_cli.cli, ['list-apps', '--json'])
    data = _json_out(result)
    assert data == {'apps': []}


def test_list_apps_json_refuses_all(app):
    result = CliRunner().invoke(serverkit_cli.cli, ['list-apps', '--json', '--all'])
    assert result.exit_code == 1
    assert '--all' in _all_output(result)


def test_list_servers_json(app, monkeypatch):
    from app.services.remote_docker_service import RemoteDockerService

    monkeypatch.setattr(
        RemoteDockerService, 'get_available_servers',
        staticmethod(lambda: [{'id': 'local', 'name': 'This server',
                               'status': 'online', 'is_local': True}]),
    )
    result = CliRunner().invoke(serverkit_cli.cli, ['list-servers', '--json'])
    data = _json_out(result)
    assert data['servers'][0]['id'] == 'local'


def test_db_status_json(app, monkeypatch):
    from app.services.migration_service import MigrationService

    monkeypatch.setattr(
        MigrationService, 'get_status',
        staticmethod(lambda: {'current_revision': '074', 'head_revision': '074',
                              'pending_count': 0, 'pending_migrations': [],
                              'needs_migration': False}),
    )
    result = CliRunner().invoke(serverkit_cli.cli, ['db-status', '--json'])
    data = _json_out(result)
    assert data['current_revision'] == '074'
    assert data['pending_count'] == 0


def test_deployment_status_json(app, monkeypatch):
    from app.services.deployment_job_service import DeploymentJobService

    job = {'id': 'j-1', 'kind': 'template.install', 'status': 'succeeded',
           'progress_percent': 100, 'target_server_name': 'local'}
    monkeypatch.setattr(
        DeploymentJobService, 'get_job',
        staticmethod(lambda job_id, include_logs=False: job),
    )
    result = CliRunner().invoke(
        serverkit_cli.cli, ['deployment-status', 'j-1', '--json'])
    data = _json_out(result)
    assert data['job']['status'] == 'succeeded'


def test_disk_json_is_a_read_only_report(app, monkeypatch):
    """`disk --json` with no selection flag reports and changes nothing."""
    from app.services import disk_reclaim_service as svc

    monkeypatch.setattr(svc, 'reclaim', lambda *a, **k: pytest.fail(
        'disk --json without a selection flag must not reclaim anything'))

    result = CliRunner().invoke(serverkit_cli.cli, ['disk', '--json'])
    data = _json_out(result)
    assert 'candidates' in data and 'disk' in data
    keys = {c['key'] for c in data['candidates']}
    assert {'upgrade-snapshots', 'telemetry'} <= keys
    for cand in data['candidates']:
        assert cand['safety'] in ('safe', 'review')
