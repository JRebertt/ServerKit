"""Tests for drift detection/repair (drift_service), the doctor sweep
(doctor_service), and the /api/v1/doctor contract."""
import json

import pytest

from app.services import drift_service
from app.services.drift_service import (
    DIFF_MAX_LINES,
    DRIFT_JOB_KIND,
    DriftService,
    LAST_REPORT_KEY as DRIFT_REPORT_KEY,
)
from app.services.doctor_service import (
    DOCTOR_JOB_KIND,
    DOCTOR_REPAIR_JOB_KIND,
    DoctorService,
    LAST_REPORT_KEY as DOCTOR_REPORT_KEY,
)

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


# --------------------------------------------------------------------------- #
# Fake drift check plumbing
# --------------------------------------------------------------------------- #

def make_fake_check(tmp_path, expected_by_id, repaired=None, check_type='fake'):
    """A registry-shaped check whose expected content is table-driven and whose
    'actual' files live under tmp_path (the default reader reads real files)."""
    def render_expected(rid):
        spec = expected_by_id[rid]
        if isinstance(spec, Exception):
            raise spec
        return {str(tmp_path / path): content for path, content in spec.items()}

    def repair(rid):
        wrote = []
        for path, content in (expected_by_id[rid] or {}).items():
            full = tmp_path / path
            if content is None:
                if full.exists():
                    full.unlink()
            else:
                full.write_text(content, encoding='utf-8')
                wrote.append(str(full))
        if repaired is not None:
            repaired.append(rid)
        return {'success': True, 'wrote': wrote, 'reloaded': True}

    return {
        'type': check_type,
        'title': 'Fake check',
        'list_resources': lambda: [(rid, f'res-{rid}') for rid in expected_by_id],
        'render_expected': render_expected,
        'repair': repair,
    }


@pytest.fixture
def fake_registry(monkeypatch):
    """Swap the module registry for an empty one so builtin checks stay out."""
    registry = {}
    monkeypatch.setattr(drift_service, 'DRIFT_CHECKS', registry)
    return registry


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

def test_check_all_statuses(app, tmp_path, fake_registry):
    (tmp_path / 'insync.conf').write_text('same\n', encoding='utf-8')
    (tmp_path / 'drifted.conf').write_text('old\n', encoding='utf-8')
    (tmp_path / 'stale.conf').write_text('should not exist\n', encoding='utf-8')

    check = make_fake_check(tmp_path, {
        'a': {'insync.conf': 'same\n'},
        'b': {'drifted.conf': 'new\n'},
        'c': {'missing.conf': 'want\n'},
        'd': RuntimeError('boom'),
        'e': {'stale.conf': None},   # file must NOT exist -> drift
        'f': {},                     # nothing applies -> in_sync
    })
    drift_service.register_check(check)

    results = {r['id']: r for r in DriftService.check_all()}

    assert results['a']['status'] == 'in_sync'
    assert results['a']['diff'] is None

    assert results['b']['status'] == 'drifted'
    assert '-old' in results['b']['diff']
    assert '+new' in results['b']['diff']

    assert results['c']['status'] == 'missing'
    assert '+want' in results['c']['diff']

    assert results['d']['status'] == 'error'
    assert 'boom' in results['d']['detail']

    assert results['e']['status'] == 'drifted'
    assert '-should not exist' in results['e']['diff']

    assert results['f']['status'] == 'in_sync'

    for r in results.values():
        assert r['type'] == 'fake'
        assert r['checked_at']
        assert r['name'].startswith('res-')


def test_diff_is_capped(app, tmp_path, fake_registry):
    (tmp_path / 'big.conf').write_text(
        '\n'.join(f'old-{i}' for i in range(500)), encoding='utf-8')
    check = make_fake_check(tmp_path, {
        'big': {'big.conf': '\n'.join(f'new-{i}' for i in range(500))},
    })
    drift_service.register_check(check)

    [result] = DriftService.check_all()

    lines = result['diff'].splitlines()
    assert len(lines) == DIFF_MAX_LINES + 1
    assert 'truncated' in lines[-1]


def test_unsupported_check_reports_clean_error(app, fake_registry):
    drift_service.register_check({
        'type': 'linuxish',
        'title': 'Linux-only thing',
        'supported': lambda: (False, 'unsupported on this host'),
        'list_resources': lambda: [(1, 'x')],
        'render_expected': lambda rid: {'/nope': 'x'},
    })

    [result] = DriftService.check_all()

    assert result['status'] == 'error'
    assert result['detail'] == 'unsupported on this host'
    assert result['id'] is None
    assert result['name'] == 'Linux-only thing'


def test_builtin_checks_are_registered():
    # The real module registry (not the fake one) carries the two builtins.
    assert 'nginx_vhost' in drift_service.DRIFT_CHECKS
    assert 'compose_override' in drift_service.DRIFT_CHECKS


# --------------------------------------------------------------------------- #
# Repair
# --------------------------------------------------------------------------- #

def test_repair_writes_and_reports(app, tmp_path, fake_registry):
    repaired = []
    check = make_fake_check(tmp_path, {'r1': {'site.conf': 'fixed\n'}},
                            repaired=repaired)
    drift_service.register_check(check)

    result = DriftService.repair('fake', 'r1')

    assert result['success'] is True
    assert result['wrote'] == [str(tmp_path / 'site.conf')]
    assert result['reloaded'] is True
    assert repaired == ['r1']
    assert (tmp_path / 'site.conf').read_text(encoding='utf-8') == 'fixed\n'

    # Repaired resource now checks clean.
    [entry] = [r for r in DriftService.check_all() if r['id'] == 'r1']
    assert entry['status'] == 'in_sync'


def test_repair_unknown_type_and_unrepairable(app, tmp_path, fake_registry):
    unknown = DriftService.repair('nope', 1)
    assert unknown['success'] is False
    assert 'Unknown drift check type' in unknown['error']

    check = make_fake_check(tmp_path, {'r1': {'x': 'y'}})
    del check['repair']
    drift_service.register_check(check)
    result = DriftService.repair('fake', 'r1')
    assert result['success'] is False
    assert 'not repairable' in result['error']


def test_repair_unsupported_platform(app, fake_registry):
    drift_service.register_check({
        'type': 'gated',
        'title': 'Gated',
        'supported': lambda: (False, 'unsupported on this host'),
        'list_resources': lambda: [],
        'render_expected': lambda rid: {},
        'repair': lambda rid: {'success': True},
    })
    result = DriftService.repair('gated', 1)
    assert result['success'] is False
    assert result['error'] == 'unsupported on this host'


# --------------------------------------------------------------------------- #
# Job handler + notification
# --------------------------------------------------------------------------- #

class _JobStub:
    def get_payload(self):
        return {}


def test_drift_job_stores_report_and_notifies(app, tmp_path, fake_registry, monkeypatch):
    from app.services.settings_service import SettingsService
    import app.plugins_sdk as sdk

    (tmp_path / 'drifted.conf').write_text('old\n', encoding='utf-8')
    drift_service.register_check(make_fake_check(tmp_path, {
        'b': {'drifted.conf': 'new\n'},
    }))

    sent = []
    monkeypatch.setattr(sdk.notify, 'send',
                        lambda event, to, data=None, **kw: sent.append((event, to, data)))

    summary = DriftService.run_drift_check_job(_JobStub())

    assert summary == {'drifted': 1, 'errors': 0, 'checked': 1}
    stored = json.loads(SettingsService.get(DRIFT_REPORT_KEY))
    assert stored['drifted'] == 1
    assert stored['results'][0]['status'] == 'drifted'

    assert len(sent) == 1
    event, to, data = sent[0]
    assert event == 'drift.detected'
    assert to == 'admins'
    assert data['count'] == 1
    assert 'res-b' in data['resources']


def test_drift_job_no_notification_when_clean(app, tmp_path, fake_registry, monkeypatch):
    import app.plugins_sdk as sdk

    (tmp_path / 'insync.conf').write_text('same\n', encoding='utf-8')
    drift_service.register_check(make_fake_check(tmp_path, {
        'a': {'insync.conf': 'same\n'},
    }))

    sent = []
    monkeypatch.setattr(sdk.notify, 'send',
                        lambda *a, **kw: sent.append(a))

    summary = DriftService.run_drift_check_job(_JobStub())

    assert summary['drifted'] == 0
    assert sent == []


def test_drift_event_in_notification_catalog():
    from app.notifications import catalog
    entry = catalog.get('drift.detected')
    assert entry is not None
    assert entry['severity'] == 'warning'
    assert entry['category'] == 'system'


def test_register_jobs_registers_handlers(app):
    from app.jobs import registry
    DriftService.register_jobs()
    DoctorService.register_jobs()
    assert registry.get(DRIFT_JOB_KIND) is not None
    assert registry.get(DOCTOR_JOB_KIND) is not None
    assert registry.get(DOCTOR_REPAIR_JOB_KIND) is not None


# --------------------------------------------------------------------------- #
# Doctor sweep
# --------------------------------------------------------------------------- #

def _fixed_drift_results():
    return [
        {'type': 'fake', 'id': 1, 'name': 'clean-app', 'status': 'in_sync',
         'diff': None, 'checked_at': 'now'},
        {'type': 'fake', 'id': 2, 'name': 'bad-app', 'status': 'drifted',
         'diff': '-a\n+b', 'checked_at': 'now'},
        {'type': 'fake', 'id': None, 'name': 'Gated', 'status': 'error',
         'diff': None, 'detail': 'unsupported on this host', 'checked_at': 'now'},
    ]


def test_doctor_run_report_shape(app, monkeypatch):
    from app.services.settings_service import SettingsService

    monkeypatch.setattr(DriftService, 'check_all',
                        classmethod(lambda cls: _fixed_drift_results()))
    monkeypatch.setattr(DoctorService, '_service_checks', classmethod(lambda cls: [
        {'key': 'service.nginx', 'title': 'nginx service', 'status': 'fail',
         'detail': 'Not running.', 'repairable': True,
         'repair_ref': {'kind': 'service', 'name': 'nginx'}},
    ]))

    report = DoctorService.run()

    assert report['ran_at']
    checks = {c['key']: c for c in report['checks']}
    # Drift entries.
    assert checks['drift.fake.1']['status'] == 'ok'
    assert checks['drift.fake.2']['status'] == 'warn'
    assert checks['drift.fake.2']['repairable'] is True
    assert checks['drift.fake.2']['repair_ref'] == {'kind': 'drift', 'type': 'fake', 'id': 2}
    assert checks['drift.fake.2']['diff'] == '-a\n+b'
    assert checks['drift.fake']['status'] == 'warn'
    assert checks['drift.fake']['repairable'] is False
    # Host probes are all present.
    assert checks['service.nginx']['status'] == 'fail'
    for key in ('certs.expiry', 'disk.headroom', 'db.reachable'):
        assert key in checks
        assert checks[key]['status'] in ('ok', 'warn', 'fail')
    assert checks['db.reachable']['status'] == 'ok'
    # Every check carries the full shape.
    for c in report['checks']:
        for field in ('key', 'title', 'status', 'detail', 'repairable', 'repair_ref'):
            assert field in c

    stored = json.loads(SettingsService.get(DOCTOR_REPORT_KEY))
    assert stored['ran_at'] == report['ran_at']


def test_doctor_cert_check_warns_on_near_expiry(app):
    from datetime import datetime, timedelta
    from werkzeug.security import generate_password_hash
    from app import db
    from app.models import User
    from app.models.application import Application
    from app.models.domain import Domain

    user = User(email='certs@test.local', username='certuser',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.flush()
    site = Application(name='certsite', app_type='static', user_id=user.id)
    db.session.add(site)
    db.session.flush()
    db.session.add(Domain(name='soon.example.com', application_id=site.id,
                          ssl_expires_at=datetime.utcnow() + timedelta(days=5)))
    db.session.commit()

    check = DoctorService._cert_check()
    assert check['status'] == 'warn'
    assert 'soon.example.com' in check['detail']


def test_doctor_batch_repair(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        DriftService, 'repair',
        classmethod(lambda cls, t, i: calls.append(('drift', t, i)) or
                    {'success': True, 'wrote': ['/x'], 'reloaded': True}))
    monkeypatch.setattr(
        DoctorService, '_restart_service',
        classmethod(lambda cls, name: calls.append(('service', name)) or
                    {'success': True, 'restarted': name}))

    results = DoctorService.repair([
        {'kind': 'drift', 'type': 'nginx_vhost', 'id': 7},
        {'kind': 'service', 'name': 'nginx'},
        {'kind': 'wat'},
    ])

    assert calls == [('drift', 'nginx_vhost', 7), ('service', 'nginx')]
    assert results[0]['success'] is True and results[0]['wrote'] == ['/x']
    assert results[1]['success'] is True and results[1]['restarted'] == 'nginx'
    assert results[2]['success'] is False
    assert 'Unknown repair kind' in results[2]['error']


def test_restart_service_rejects_unknown_service(app):
    result = DoctorService._restart_service('sshd')
    assert result['success'] is False
    assert 'not repairable' in result['error']


# --------------------------------------------------------------------------- #
# API contract
# --------------------------------------------------------------------------- #

@pytest.fixture
def doctor_client(app):
    """Test client with the doctor blueprint mounted (registration in
    app/__init__.py is wired separately)."""
    from app.api.doctor import doctor_bp
    if 'doctor' not in app.blueprints:
        app.register_blueprint(doctor_bp, url_prefix='/api/v1/doctor')
    return app.test_client()


@pytest.fixture
def viewer_headers(app):
    """A non-admin (viewer) token, to prove admin-only enforcement."""
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    user = User(
        email='viewer@test.local', username='vieweruser',
        password_hash=generate_password_hash('testpass'),
        role=User.ROLE_VIEWER, is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    token = create_access_token(identity=user.id)
    return {'Authorization': f'Bearer {token}'}


def test_api_requires_auth(doctor_client):
    assert doctor_client.get('/api/v1/doctor').status_code == 401
    assert doctor_client.get('/api/v1/doctor/drift').status_code == 401
    assert doctor_client.post('/api/v1/doctor/drift/check').status_code == 401
    assert doctor_client.post('/api/v1/doctor/run').status_code == 401
    assert doctor_client.post('/api/v1/doctor/repair').status_code == 401


def test_api_requires_admin(doctor_client, viewer_headers):
    resp = doctor_client.get('/api/v1/doctor', headers=viewer_headers)
    assert resp.status_code == 403
    assert 'error' in resp.get_json()
    resp = doctor_client.post('/api/v1/doctor/run', headers=viewer_headers)
    assert resp.status_code == 403


def test_get_drift_report_null_then_value(doctor_client, auth_headers, app):
    from app.services.settings_service import SettingsService

    resp = doctor_client.get('/api/v1/doctor/drift', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {'report': None}

    report = {'results': [], 'drifted': 0, 'errors': 0, 'generated_at': 'x'}
    SettingsService.set(DRIFT_REPORT_KEY, json.dumps(report))
    resp = doctor_client.get('/api/v1/doctor/drift', headers=auth_headers)
    assert resp.get_json() == {'report': report}


def test_post_drift_check_enqueues(doctor_client, auth_headers, monkeypatch):
    from app.jobs.service import JobService

    class _FakeJob:
        id = 'job-drift-1'

    enqueued = []

    def _fake_enqueue(kind, payload=None, max_attempts=3, **kwargs):
        enqueued.append((kind, payload, max_attempts))
        return _FakeJob()

    monkeypatch.setattr(JobService, 'enqueue', staticmethod(_fake_enqueue))

    resp = doctor_client.post('/api/v1/doctor/drift/check', headers=auth_headers)

    assert resp.status_code == 202
    assert resp.get_json() == {'job_id': 'job-drift-1'}
    assert enqueued == [(DRIFT_JOB_KIND, {}, 1)]


def test_drift_repair_requires_confirm(doctor_client, auth_headers):
    resp = doctor_client.post('/api/v1/doctor/drift/nginx_vhost/1/repair',
                              headers=auth_headers, json={})
    assert resp.status_code == 400
    assert 'error' in resp.get_json()

    resp = doctor_client.post('/api/v1/doctor/drift/nginx_vhost/1/repair',
                              headers=auth_headers, json={'confirm': 'yes'})
    assert resp.status_code == 400


def test_drift_repair_with_confirm(doctor_client, auth_headers, monkeypatch):
    calls = []
    monkeypatch.setattr(
        DriftService, 'repair',
        classmethod(lambda cls, t, i: calls.append((t, i)) or
                    {'success': True, 'wrote': ['/etc/nginx/sites-available/blog'],
                     'reloaded': True}))

    resp = doctor_client.post('/api/v1/doctor/drift/nginx_vhost/7/repair',
                              headers=auth_headers, json={'confirm': True})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['wrote'] == ['/etc/nginx/sites-available/blog']
    assert body['reloaded'] is True
    assert calls == [('nginx_vhost', 7)]  # numeric ids are cast to int


def test_get_doctor_report_null_then_value(doctor_client, auth_headers, app):
    from app.services.settings_service import SettingsService

    resp = doctor_client.get('/api/v1/doctor', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {'report': None}

    report = {'checks': [], 'ran_at': 'x'}
    SettingsService.set(DOCTOR_REPORT_KEY, json.dumps(report))
    resp = doctor_client.get('/api/v1/doctor', headers=auth_headers)
    assert resp.get_json() == {'report': report}


def test_post_run_is_synchronous(doctor_client, auth_headers, monkeypatch):
    fixed = {'checks': [{'key': 'db.reachable', 'title': 'Database',
                         'status': 'ok', 'detail': 'Reachable.',
                         'repairable': False, 'repair_ref': None}],
             'ran_at': '2026-07-03T00:00:00Z'}
    monkeypatch.setattr(DoctorService, 'run', classmethod(lambda cls: fixed))

    resp = doctor_client.post('/api/v1/doctor/run', headers=auth_headers)

    assert resp.status_code == 200
    assert resp.get_json() == {'report': fixed}


def test_post_repair_batch(doctor_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        DoctorService, 'repair',
        classmethod(lambda cls, items: [{'item': i, 'success': True} for i in items]))

    items = [{'kind': 'drift', 'type': 'fake', 'id': 1},
             {'kind': 'service', 'name': 'nginx'}]
    resp = doctor_client.post('/api/v1/doctor/repair',
                              headers=auth_headers, json={'items': items})

    assert resp.status_code == 200
    assert resp.get_json() == {'results': [{'item': items[0], 'success': True},
                                           {'item': items[1], 'success': True}]}


def test_post_repair_can_enqueue_operation(doctor_client, auth_headers):
    from app.jobs.models import Job

    items = [{'kind': 'service', 'name': 'nginx'}]
    resp = doctor_client.post(
        '/api/v1/doctor/repair?wait=false',
        headers=auth_headers,
        json={'items': items},
    )

    assert resp.status_code == 202
    body = resp.get_json()
    assert body['kind'] == DOCTOR_REPAIR_JOB_KIND
    job = Job.query.get(body['job_id'])
    assert job.status == Job.STATUS_PENDING
    assert job.get_payload() == {'items': items}
    assert job.owner_type == 'doctor'
    assert job.owner_id == 'host'


def test_doctor_repair_job_persists_progress_and_fails_honestly(app, monkeypatch):
    from app.jobs.models import Job
    from app.jobs.service import JobService

    items = [
        {'kind': 'service', 'name': 'nginx'},
        {'kind': 'dns', 'host': 'broken.example.com'},
    ]
    job = JobService.enqueue(
        DOCTOR_REPAIR_JOB_KIND, {'items': items}, max_attempts=1,
    )
    monkeypatch.setattr(
        DoctorService,
        'repair',
        classmethod(lambda cls, selected: [
            {'item': selected[0], 'success': True},
            {'item': selected[1], 'success': False, 'error': 'still broken'},
        ]),
    )

    with pytest.raises(RuntimeError, match='1 of 2 doctor repairs failed'):
        DoctorService.run_doctor_repair_job(job)

    persisted = Job.query.get(job.id).get_result()
    assert persisted['completed'] == 2
    assert persisted['total'] == 2
    assert persisted['failed'] == 1


def test_post_repair_requires_items(doctor_client, auth_headers):
    resp = doctor_client.post('/api/v1/doctor/repair', headers=auth_headers, json={})
    assert resp.status_code == 400
    resp = doctor_client.post('/api/v1/doctor/repair', headers=auth_headers,
                              json={'items': []})
    assert resp.status_code == 400
