"""Plan 77 E1 gate — the generalized run envelope.

Contract: a stream line for any RunLike is (1) persisted in run_log_entries
under (run_kind, run_id), (2) emitted as a run_log batch carrying the real DB
ids, and (3) recoverable over GET /api/v1/runs/<kind>/<id>/logs?after_id —
so a client that missed socket frames can always resync.
"""
import pytest

from app import db
from app.jobs.models import Job
from app.models.run_log import RunLogEntry
from app.services.run_log_service import RunLogStream


class _Emitter:
    def __init__(self):
        self.log_calls = []
        self.status_calls = []

    def emit_log(self, run_id, lines):
        self.log_calls.append((run_id, lines))

    def emit_status(self, run_id, status):
        self.status_calls.append((run_id, status))


def _make_job(kind='envelope-test'):
    job = Job(kind=kind)
    db.session.add(job)
    db.session.commit()
    return job


def test_emit_persist_and_after_id_resync(app, client, auth_headers):
    job = _make_job()
    emitter = _Emitter()
    stream = RunLogStream.for_job(job, emit_log=emitter.emit_log,
                                  emit_status=emitter.emit_status)
    assert stream.run_kind == 'job'

    stream.log('info', 'first line')
    stream.flush()
    stream.log('warn', 'second line')
    stream.flush()

    rows = (RunLogEntry.query
            .filter_by(run_kind='job', run_id=str(job.id))
            .order_by(RunLogEntry.id).all())
    assert [r.message for r in rows] == ['first line', 'second line']

    # the emitted batches carry the REAL persisted ids (dedupe/resync anchor)
    emitted_ids = [line['id'] for _, lines in emitter.log_calls for line in lines]
    assert emitted_ids == [r.id for r in rows]

    # REST resync twin
    resp = client.get(f'/api/v1/runs/job/{job.id}/logs', headers=auth_headers)
    assert resp.status_code == 200
    logs = resp.get_json()['logs']
    assert [l['message'] for l in logs] == ['first line', 'second line']

    resp = client.get(f'/api/v1/runs/job/{job.id}/logs?after_id={rows[0].id}',
                      headers=auth_headers)
    assert [l['message'] for l in resp.get_json()['logs']] == ['second line']


def test_runs_endpoint_requires_auth(app, client):
    resp = client.get('/api/v1/runs/job/nope/logs')
    assert resp.status_code == 401


def test_close_emits_terminal_status(app):
    job = _make_job()
    emitter = _Emitter()
    stream = RunLogStream.for_job(job, emit_log=emitter.emit_log,
                                  emit_status=emitter.emit_status)
    stream.log('info', 'line')
    stream.close('succeeded')
    assert emitter.status_calls, 'close() must emit a terminal status'


def test_default_emitters_use_run_envelope(app, monkeypatch):
    calls = []
    import app.sockets as sk
    monkeypatch.setattr(sk, 'emit_run_log',
                        lambda kind, rid, lines: calls.append((kind, rid, len(lines))))
    job = _make_job()
    stream = RunLogStream.for_job(job)
    stream.log('info', 'hello')
    stream.flush()
    assert calls and calls[0][0] == 'job' and calls[0][1] == job.id


def test_deploy_kind_dual_emits_legacy_events(app, monkeypatch):
    import app.sockets as sk
    events = []
    monkeypatch.setattr(sk.socketio, 'emit',
                        lambda name, payload, room=None: events.append((name, room)))
    sk.emit_run_log('deploy', 'j1', [{'id': 1}])
    assert ('run_log', 'run_deploy_j1') in events
    assert ('deploy_log', 'deploy_j1') in events

    events.clear()
    sk.emit_run_status('deploy', 'j1', {'status': 'running'})
    assert ('run_status', 'run_deploy_j1') in events
    assert ('deploy_status', 'deploy_j1') in events


def test_non_deploy_kind_does_not_dual_emit(app, monkeypatch):
    import app.sockets as sk
    events = []
    monkeypatch.setattr(sk.socketio, 'emit',
                        lambda name, payload, room=None: events.append((name, room)))
    sk.emit_run_log('job', 'x', [])
    assert events == [('run_log', 'run_job_x')]


def test_job_consumer_streams_the_run(app, monkeypatch):
    """A unified job processed by the consumer produces persisted run frames —
    Jobs finally have a live channel with a polling twin."""
    from app.jobs import registry as jobs_registry
    from app.jobs.consumer import JobConsumer
    from app.queue_bus.service import QueueBusService

    monkeypatch.setattr(QueueBusService, 'complete',
                        staticmethod(lambda *a, **k: None))

    calls = []
    jobs_registry.register('envelope-proof',
                           lambda job: calls.append(job.id) or {'ok': True},
                           replace=True)

    job = _make_job(kind='envelope-proof')
    consumer = JobConsumer(app=app)
    consumer.process_message({'id': 'm1', 'payload': {'job_id': job.id}, 'attempts': 0})

    assert calls == [job.id]
    assert Job.query.get(job.id).status == Job.STATUS_SUCCEEDED
    rows = RunLogEntry.query.filter_by(run_kind='job', run_id=str(job.id)).all()
    messages = [r.message for r in rows]
    assert any('Job started' in m for m in messages)
    assert any('Job succeeded' in m for m in messages)
