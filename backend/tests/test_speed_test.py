"""Tests for the on-demand server speed test (service tiers + API).

All network access is stubbed — the suite stays offline.
"""
import json

import pytest

from app.services import speed_test_service as sts_module
from app.services.speed_test_service import (
    LAST_RESULT_KEY,
    SPEEDTEST_JOB_KIND,
    SpeedTestService,
)

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


# The shared stub kit (plan 75 §G7) — this class was pasted
# byte-identical in four test modules.
from subprocess_stub import FakeProc as _FakeProc


class _FakeResponse:
    def __init__(self, body=b'', status=200):
        self._body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sts_module.requests.HTTPError(f'HTTP {self.status_code}')

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


class _FakeSocket:
    def close(self):
        pass


@pytest.fixture
def no_cli(monkeypatch):
    """Pretend no speedtest binary exists — forces the pure-Python tier."""
    monkeypatch.setattr(sts_module, 'is_command_available', lambda cmd: False)


# ── fallback tier ────────────────────────────────────────────────────────────

def test_fallback_full_success(no_cli, monkeypatch):
    monkeypatch.setattr(
        sts_module.socket, 'create_connection',
        lambda addr, timeout=None: _FakeSocket(),
    )
    monkeypatch.setattr(
        sts_module.requests, 'get',
        lambda url, timeout=None, stream=False: _FakeResponse(b'x' * 1_000_000),
    )
    monkeypatch.setattr(
        sts_module.requests, 'post',
        lambda url, data=None, timeout=None: _FakeResponse(),
    )

    result = SpeedTestService.run_test()

    assert result['success'] is True
    assert result['method'] == 'fallback'
    assert result['download_mbps'] > 0
    assert result['upload_mbps'] > 0
    assert result['latency_ms'] is not None and result['latency_ms'] >= 0
    assert result['tested_at']


def test_fallback_upload_failure_is_best_effort(no_cli, monkeypatch):
    monkeypatch.setattr(
        sts_module.socket, 'create_connection',
        lambda addr, timeout=None: _FakeSocket(),
    )
    monkeypatch.setattr(
        sts_module.requests, 'get',
        lambda url, timeout=None, stream=False: _FakeResponse(b'x' * 500_000),
    )

    def _post_fails(url, data=None, timeout=None):
        raise sts_module.requests.ConnectionError('upload endpoint unreachable')

    monkeypatch.setattr(sts_module.requests, 'post', _post_fails)

    result = SpeedTestService.run_test()

    assert result['success'] is True
    assert result['download_mbps'] > 0
    assert result['upload_mbps'] is None  # best-effort


def test_fallback_total_failure_returns_error(no_cli, monkeypatch):
    def _connect_fails(addr, timeout=None):
        raise OSError('network down')

    def _get_fails(url, timeout=None, stream=False):
        raise sts_module.requests.ConnectionError('no route')

    def _post_fails(url, data=None, timeout=None):
        raise sts_module.requests.ConnectionError('no route')

    monkeypatch.setattr(sts_module.socket, 'create_connection', _connect_fails)
    monkeypatch.setattr(sts_module.requests, 'get', _get_fails)
    monkeypatch.setattr(sts_module.requests, 'post', _post_fails)

    result = SpeedTestService.run_test()

    assert result['success'] is False
    assert 'error' in result


# ── CLI tier ─────────────────────────────────────────────────────────────────

def test_cli_ookla_json_parsed(monkeypatch):
    monkeypatch.setattr(
        sts_module, 'is_command_available', lambda cmd: cmd == 'speedtest'
    )
    ookla = json.dumps({
        'download': {'bandwidth': 12_500_000},   # bytes/s -> 100 Mbps
        'upload': {'bandwidth': 2_500_000},      # bytes/s -> 20 Mbps
        'ping': {'latency': 8.42},
    })
    monkeypatch.setattr(
        sts_module.subprocess, 'run',
        lambda cmd, capture_output=True, text=True, timeout=None: _FakeProc(0, ookla),
    )

    result = SpeedTestService.run_test()

    assert result['success'] is True
    assert result['method'] == 'cli'
    assert result['download_mbps'] == 100.0
    assert result['upload_mbps'] == 20.0
    assert result['latency_ms'] == 8.42


def test_cli_python_speedtest_cli_json_parsed(monkeypatch):
    monkeypatch.setattr(
        sts_module, 'is_command_available', lambda cmd: cmd == 'speedtest-cli'
    )
    legacy = json.dumps({
        'download': 50_000_000.0,  # bits/s -> 50 Mbps
        'upload': 10_000_000.0,    # bits/s -> 10 Mbps
        'ping': 22.5,
    })
    monkeypatch.setattr(
        sts_module.subprocess, 'run',
        lambda cmd, capture_output=True, text=True, timeout=None: _FakeProc(0, legacy),
    )

    result = SpeedTestService.run_test()

    assert result['success'] is True
    assert result['method'] == 'cli'
    assert result['download_mbps'] == 50.0
    assert result['upload_mbps'] == 10.0
    assert result['latency_ms'] == 22.5


def test_cli_failure_falls_back_to_python_tier(monkeypatch):
    monkeypatch.setattr(
        sts_module, 'is_command_available', lambda cmd: cmd == 'speedtest'
    )
    monkeypatch.setattr(
        sts_module.subprocess, 'run',
        lambda cmd, capture_output=True, text=True, timeout=None: _FakeProc(1, '', 'boom'),
    )
    monkeypatch.setattr(
        sts_module.socket, 'create_connection',
        lambda addr, timeout=None: _FakeSocket(),
    )
    monkeypatch.setattr(
        sts_module.requests, 'get',
        lambda url, timeout=None, stream=False: _FakeResponse(b'x' * 100_000),
    )
    monkeypatch.setattr(
        sts_module.requests, 'post',
        lambda url, data=None, timeout=None: _FakeResponse(),
    )

    result = SpeedTestService.run_test()

    assert result['success'] is True
    assert result['method'] == 'fallback'


# ── job handler ──────────────────────────────────────────────────────────────

def test_job_handler_stores_last_result(app, monkeypatch):
    from app.services.settings_service import SettingsService

    fixed = {
        'success': True, 'method': 'fallback', 'download_mbps': 42.0,
        'upload_mbps': 7.5, 'latency_ms': 12.0, 'tested_at': '2026-07-03T00:00:00Z',
    }
    monkeypatch.setattr(SpeedTestService, 'run_test', classmethod(lambda cls: fixed))

    class _JobStub:
        def get_payload(self):
            return {}

    result = SpeedTestService.run_speed_test_job(_JobStub())

    assert result == fixed
    stored = SettingsService.get(LAST_RESULT_KEY)
    assert json.loads(stored) == fixed


def test_register_jobs_registers_handler(app):
    from app.jobs import registry

    SpeedTestService.register_jobs()
    assert registry.get(SPEEDTEST_JOB_KIND) is not None


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def st_client(app):
    """Test client with the speedtest blueprint mounted (registration in
    app/__init__.py is wired separately)."""
    from app.api.speed_test import speedtest_bp
    if 'speedtest' not in app.blueprints:
        app.register_blueprint(speedtest_bp, url_prefix='/api/v1/speedtest')
    return app.test_client()


def test_get_returns_last_result_and_running_flag(st_client, auth_headers, app):
    from app.services.settings_service import SettingsService

    fixed = {'success': True, 'method': 'cli', 'download_mbps': 90.0,
             'upload_mbps': 30.0, 'latency_ms': 5.0,
             'tested_at': '2026-07-03T01:00:00Z'}
    SettingsService.set(LAST_RESULT_KEY, json.dumps(fixed))

    resp = st_client.get('/api/v1/speedtest', headers=auth_headers)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['last_result'] == fixed
    assert data['running'] is False
    assert data['job'] is None


def test_get_with_no_result_yet(st_client, auth_headers):
    resp = st_client.get('/api/v1/speedtest', headers=auth_headers)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['last_result'] is None
    assert data['running'] is False


def test_run_enqueues_job(st_client, auth_headers, monkeypatch):
    from app.jobs.service import JobService

    enqueued = []

    class _FakeJob:
        id = 'job-123'

    def _fake_enqueue(kind, payload=None, max_attempts=3, **kwargs):
        enqueued.append((kind, payload, max_attempts))
        return _FakeJob()

    monkeypatch.setattr(JobService, 'enqueue', staticmethod(_fake_enqueue))

    resp = st_client.post('/api/v1/speedtest/run', headers=auth_headers)

    assert resp.status_code == 202
    assert resp.get_json() == {'job_id': 'job-123'}
    assert enqueued == [(SPEEDTEST_JOB_KIND, {}, 1)]


def test_run_rejects_when_already_running(st_client, auth_headers, app):
    from app import db
    from app.jobs.models import Job

    job = Job(kind=SPEEDTEST_JOB_KIND, status=Job.STATUS_RUNNING)
    job.set_payload({})
    db.session.add(job)
    db.session.commit()

    resp = st_client.post('/api/v1/speedtest/run', headers=auth_headers)

    assert resp.status_code == 409
    assert 'error' in resp.get_json()


def test_endpoints_require_auth(st_client):
    assert st_client.get('/api/v1/speedtest').status_code == 401
    assert st_client.post('/api/v1/speedtest/run').status_code == 401
