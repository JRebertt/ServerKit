"""Panel disk-reclaim surface — curated safe set, validated server-side."""

import pytest

from app import db
from app.services import disk_reclaim_service as svc


def _scan_report():
    return {
        'disk': {'path': '/', 'total': 100, 'used': 95, 'free': 5,
                 'percent_used': 95.0},
        'candidates': [
            {'key': 'upgrade-snapshots', 'safety': 'safe', 'title': 'snapshots',
             'detail': '', 'bytes': 40},
            {'key': 'package-caches', 'safety': 'safe', 'title': 'caches',
             'detail': '', 'bytes': 20},
            {'key': 'telemetry', 'safety': 'review', 'title': 'telemetry',
             'detail': '', 'bytes': 10},
        ],
        'total_bytes': 70,
    }


@pytest.fixture(autouse=True)
def _fake_measurements(monkeypatch):
    """Keep every scan/reclaim off the real filesystem and Docker."""
    monkeypatch.setattr(svc, 'scan', lambda *a, **kw: _scan_report())
    monkeypatch.setattr(svc, 'reclaim', lambda keys, **kw: {
        'dry_run': False,
        'results': [{'key': k, 'bytes': 1, 'note': ''} for k in keys],
        'freed_bytes': len(list(keys)),
        'disk_before': {}, 'disk_after': {},
    })


# ── Report ───────────────────────────────────────────────────────────────────

def test_report_requires_admin(client, viewer_headers):
    response = client.get('/api/v1/system/disk/reclaim/report',
                          headers=viewer_headers)
    assert response.status_code == 403


def test_report_measures_without_deleting(client, auth_headers):
    response = client.get('/api/v1/system/disk/reclaim/report',
                          headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body['total_bytes'] == 70
    assert [c['key'] for c in body['candidates']] == [
        'upgrade-snapshots', 'package-caches', 'telemetry']


# ── Reclaim contract ─────────────────────────────────────────────────────────

def test_reclaim_requires_explicit_confirmation(client, auth_headers):
    response = client.post('/api/v1/system/disk/reclaim', headers=auth_headers,
                           json={'keys': ['upgrade-snapshots']})
    assert response.status_code == 400
    assert 'confirm' in response.get_json()['error'].lower()


def test_reclaim_rejects_review_and_unknown_keys(client, auth_headers):
    for bad in (['telemetry'], ['nope'], ['telemetry', 'upgrade-snapshots']):
        response = client.post('/api/v1/system/disk/reclaim',
                               headers=auth_headers,
                               json={'confirm': True, 'keys': bad})
        assert response.status_code == 400, bad
        body = response.get_json()
        assert 'reviewed-safe' in body['error']
        assert any(k in body['error'] for k in ('telemetry', 'nope'))


def test_reclaim_rejects_empty_or_malformed_keys(client, auth_headers):
    for body in ({'confirm': True}, {'confirm': True, 'keys': []},
                 {'confirm': True, 'keys': ['ok', 3]},
                 {'confirm': True, 'keys': 'upgrade-snapshots'}):
        response = client.post('/api/v1/system/disk/reclaim',
                               headers=auth_headers, json=body)
        assert response.status_code == 400


def test_reclaim_runs_safe_set_inline(client, auth_headers):
    response = client.post('/api/v1/system/disk/reclaim', headers=auth_headers,
                           json={'confirm': True,
                                 'keys': ['upgrade-snapshots', 'package-caches']})
    assert response.status_code == 200
    body = response.get_json()
    assert body['freed_bytes'] == 2
    assert [r['key'] for r in body['results']] == [
        'upgrade-snapshots', 'package-caches']


def test_reclaim_validates_against_a_fresh_scan_not_the_request(
        client, auth_headers, monkeypatch):
    """A candidate that was safe when the report was fetched can go stale."""
    stale = _scan_report()
    stale['candidates'][0]['safety'] = 'review'
    monkeypatch.setattr(svc, 'scan', lambda *a, **kw: stale)

    response = client.post('/api/v1/system/disk/reclaim', headers=auth_headers,
                           json={'confirm': True, 'keys': ['upgrade-snapshots']})
    assert response.status_code == 400
    assert 'upgrade-snapshots' in response.get_json()['error']


# ── Background path ──────────────────────────────────────────────────────────

def test_wait_false_enqueues_a_job_instead_of_running_inline(
        client, auth_headers, app, monkeypatch):
    def _unexpected(*args, **kwargs):
        raise AssertionError('reclaim must run in the job, not the request')

    monkeypatch.setattr(svc, 'reclaim', _unexpected)

    response = client.post('/api/v1/system/disk/reclaim?wait=false',
                           headers=auth_headers,
                           json={'confirm': True,
                                 'keys': ['package-caches']})
    assert response.status_code == 202
    body = response.get_json()
    assert body['kind'] == svc.DISK_RECLAIM_JOB_KIND

    from app.jobs.models import Job
    job = db.session.get(Job, body['job_id'])
    assert job is not None
    assert job.get_payload() == {'keys': ['package-caches']}


def test_job_handler_reruns_validation_before_reclaiming(app, monkeypatch):
    """The queue may pick the job up long after the request was validated."""
    from app.jobs.service import JobService

    job = JobService.enqueue(svc.DISK_RECLAIM_JOB_KIND,
                             payload={'keys': ['telemetry']}, max_attempts=1)
    with pytest.raises(RuntimeError, match='reviewed-safe'):
        svc.run_reclaim_job(job)


def test_job_handler_reclaims_the_safe_set(app):
    from app.jobs.service import JobService

    job = JobService.enqueue(svc.DISK_RECLAIM_JOB_KIND,
                             payload={'keys': ['package-caches']},
                             max_attempts=1)
    result = svc.run_reclaim_job(job)
    assert result['freed_bytes'] == 1
    assert result['results'] == [
        {'key': 'package-caches', 'bytes': 1, 'note': ''}]


# ── Service-level guard ──────────────────────────────────────────────────────

def test_safe_candidate_keys_reads_safety_tags():
    assert svc.safe_candidate_keys(_scan_report()) == {
        'upgrade-snapshots', 'package-caches'}


def test_validate_reclaim_keys_names_every_rejected_key():
    keys, error = svc.validate_reclaim_keys(
        ['package-caches', 'telemetry', 'nope'])
    assert keys is None
    assert error.startswith('Only reviewed-safe candidates')
    assert 'nope' in error and 'telemetry' in error
