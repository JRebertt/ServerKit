"""Deploy Console backend surface (plan 51 Phases 1-3):

- socket emit helpers push to the per-job room with the right payload;
- RunLogStream's default emitter reaches socketio;
- subscribe_deploy requires an authenticated socket;
- POST /builds/apps/<id>/deploy is 202+job by default, sync under ?wait=true;
- POST /deployment-jobs/<id>/retry clones failed jobs (both kinds) and guards.
"""
import uuid

import pytest

from app import db
from app.models.deployment_job import DeploymentJob
from app.jobs.models import Job


def _make_app(name='consvc'):
    from app.models.application import Application
    a = Application(name=name, app_type='docker', status='stopped',
                    root_path='/srv/' + name, user_id=1)
    db.session.add(a)
    db.session.commit()
    return a


def _make_job(kind='app_deploy', status='failed', app_id=None):
    job = DeploymentJob(id=str(uuid.uuid4()), kind=kind, status=status,
                        app_id=app_id, trigger='manual')
    job.set_plan({'app_id': app_id, 'steps': [{'name': 'Prepare deployment'},
                                              {'name': 'Build application'},
                                              {'name': 'Start containers'}]})
    db.session.add(job)
    db.session.commit()
    return job


# ---------------------------------------------------------------- Phase 1

class TestSocketEmitHelpers:
    def test_emit_deploy_log_room_and_payload(self, app, monkeypatch):
        import app.sockets as sk
        calls = []
        monkeypatch.setattr(sk.socketio, 'emit', lambda *a, **k: calls.append((a, k)))
        lines = [{'id': 7, 'level': 'info', 'message': 'hello', 'step_index': 1, 'ts': None}]
        sk.emit_deploy_log('job-1', lines)
        assert calls, 'expected a socketio emit'
        (args, kwargs) = calls[0]
        assert args[0] == 'deploy_log'
        assert args[1]['job_id'] == 'job-1'
        assert args[1]['lines'][0]['message'] == 'hello'
        assert kwargs['room'] == 'deploy_job-1'

    def test_emit_deploy_status_room_and_payload(self, app, monkeypatch):
        import app.sockets as sk
        calls = []
        monkeypatch.setattr(sk.socketio, 'emit', lambda *a, **k: calls.append((a, k)))
        sk.emit_deploy_status('job-2', {'status': 'running', 'current_step': 2})
        (args, kwargs) = calls[0]
        assert args[0] == 'deploy_status'
        assert args[1]['status']['status'] == 'running'
        assert kwargs['room'] == 'deploy_job-2'

    def test_stream_default_emitter_reaches_socketio(self, app, monkeypatch):
        import app.sockets as sk
        from app.services.run_log_service import RunLogStream
        calls = []
        monkeypatch.setattr(sk.socketio, 'emit', lambda *a, **k: calls.append((a, k)))
        job = _make_job(kind='template_install', status='running')
        stream = RunLogStream.for_job(job)  # default (socket) emitters
        for i in range(50):  # cross the flush-on-count threshold
            stream.log('info', f'line {i}')
        log_events = [c for c in calls if c[0][0] == 'deploy_log']
        assert log_events, 'expected a deploy_log emit from the default emitter'
        assert log_events[0][1]['room'] == f'deploy_{job.id}'

    def test_old_build_socket_surface_removed(self, app):
        import app.sockets as sk
        # The orphaned build_* channel is gone (D3).
        assert not hasattr(sk, 'emit_build_log')
        assert not hasattr(sk, 'emit_build_status')
        assert not hasattr(sk, 'create_build_log_callback')


class _FakeReq:
    def __init__(self, sid):
        self.sid = sid


class TestSubscribeDeployAuth:
    """The socketio test client is unusable on this Flask/Werkzeug pairing
    (`ctx.session` became read-only), so exercise the handler's auth guard
    directly by faking the socket context (request.sid / emit / join_room)."""

    def _patch(self, monkeypatch, sid):
        import app.sockets as sk
        emitted, joined = [], []
        monkeypatch.setattr(sk, 'emit', lambda *a, **k: emitted.append((a, k)))
        monkeypatch.setattr(sk, 'join_room', lambda room: joined.append(room))
        monkeypatch.setattr(sk, 'request', _FakeReq(sid))
        return sk, emitted, joined

    def test_unauthenticated_join_rejected(self, app, monkeypatch):
        sk, emitted, joined = self._patch(monkeypatch, 'sid-unauth')
        sk.connected_clients.pop('sid-unauth', None)  # not authenticated
        sk.CHANNELS['deploy']['subscribe']({'job_id': 'abc'})
        assert joined == []  # never joined a room
        assert any(a and a[0] == 'error' for a, k in emitted)

    def test_authenticated_join_succeeds(self, app, monkeypatch):
        sk, emitted, joined = self._patch(monkeypatch, 'sid-auth')
        sk.connected_clients['sid-auth'] = {'user_id': 1, 'role': 'admin'}
        try:
            sk.CHANNELS['deploy']['subscribe']({'job_id': 'job-xyz'})
        finally:
            sk.connected_clients.pop('sid-auth', None)
        assert 'deploy_job-xyz' in joined
        assert any(a and a[0] == 'subscribed' for a, k in emitted)

    def test_missing_job_id_rejected(self, app, monkeypatch):
        sk, emitted, joined = self._patch(monkeypatch, 'sid-auth2')
        sk.connected_clients['sid-auth2'] = {'user_id': 1, 'role': 'admin'}
        try:
            sk.CHANNELS['deploy']['subscribe']({})
        finally:
            sk.connected_clients.pop('sid-auth2', None)
        assert joined == []
        assert any(a and a[0] == 'error' for a, k in emitted)


# ---------------------------------------------------------------- Phase 2

class TestDeployAppJobified:
    def test_default_deploy_returns_202_and_job(self, app, client, auth_headers, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        a = _make_app('depsvc')

        seen = {}

        def fake_enqueue(cls, application, user_id=None, trigger='install',
                         no_cache=False, version_tag=None):
            seen['no_cache'] = no_cache
            seen['version_tag'] = version_tag
            return {'success': True, 'job_id': 'dj-async'}

        monkeypatch.setattr(DeploymentJobService, 'enqueue_app_deploy',
                            classmethod(fake_enqueue))
        res = client.post(f'/api/v1/builds/apps/{a.id}/deploy', headers=auth_headers,
                          json={'no_cache': True, 'version_tag': 'v9'})
        assert res.status_code == 202
        body = res.get_json()
        assert body['deploy_job_id'] == 'dj-async'
        assert seen['no_cache'] is True
        assert seen['version_tag'] == 'v9'

    def test_wait_true_runs_synchronously(self, app, client, auth_headers, monkeypatch):
        from app.services.deployment_service import DeploymentService
        a = _make_app('depsvc2')

        monkeypatch.setattr(DeploymentService, 'deploy',
                            classmethod(lambda cls, app_id, **kw: {
                                'success': True, 'deployment': {'id': 1, 'version': 3}}))
        res = client.post(f'/api/v1/builds/apps/{a.id}/deploy?wait=true',
                          headers=auth_headers, json={})
        assert res.status_code == 200
        body = res.get_json()
        assert body['success'] is True
        assert 'deploy_job_id' not in body  # sync path, no job id


# ---------------------------------------------------------------- Phase 3

class TestRetryJob:
    def test_retry_clones_failed_app_deploy(self, app, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        monkeypatch.setattr(DeploymentJobService, '_enqueue_app_deploy',
                            classmethod(lambda cls, job: None))
        a = _make_app('retrysvc')
        job = _make_job(kind='app_deploy', status='failed', app_id=a.id)

        result = DeploymentJobService.retry_job(job.id, user_id=5)
        assert result['success'] is True
        clone = DeploymentJob.query.get(result['job_id'])
        assert clone.id != job.id
        assert clone.kind == 'app_deploy'
        assert clone.app_id == a.id
        assert clone.status == 'pending'
        assert clone.trigger == 'retry'
        assert clone.requested_by == 5
        assert clone.get_plan()['steps'] == job.get_plan()['steps']

    def test_retry_clones_failed_template_install(self, app, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        monkeypatch.setattr(DeploymentJobService, '_enqueue_install',
                            classmethod(lambda cls, job: None))
        job = _make_job(kind='template_install', status='failed')

        result = DeploymentJobService.retry_job(job.id, user_id=1)
        assert result['success'] is True
        clone = DeploymentJob.query.get(result['job_id'])
        assert clone.kind == 'template_install'
        assert clone.trigger == 'retry'

    def test_retry_rejects_non_failed(self, app):
        from app.services.deployment_job_service import DeploymentJobService
        job = _make_job(kind='app_deploy', status='succeeded')
        result = DeploymentJobService.retry_job(job.id)
        assert result['success'] is False
        assert 'failed' in result['error'].lower()

    def test_retry_missing_job(self, app):
        from app.services.deployment_job_service import DeploymentJobService
        result = DeploymentJobService.retry_job('no-such-job')
        assert result['success'] is False
        assert result['error'] == 'Deployment job not found'

    def test_retry_endpoint_status_codes(self, app, client, auth_headers, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        monkeypatch.setattr(DeploymentJobService, '_enqueue_app_deploy',
                            classmethod(lambda cls, job: None))
        a = _make_app('retrysvc2')
        failed = _make_job(kind='app_deploy', status='failed', app_id=a.id)
        ok = _make_job(kind='app_deploy', status='succeeded', app_id=a.id)

        r1 = client.post(f'/api/v1/deployment-jobs/{failed.id}/retry', headers=auth_headers)
        assert r1.status_code == 202
        assert r1.get_json()['job_id']

        r2 = client.post(f'/api/v1/deployment-jobs/{ok.id}/retry', headers=auth_headers)
        assert r2.status_code == 400

        r3 = client.post('/api/v1/deployment-jobs/nope/retry', headers=auth_headers)
        assert r3.status_code == 404


# ---------------------------------------------------------------- Phase 4

class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ''

    def close(self):
        pass


class _FakeProc:
    def __init__(self, lines, code):
        self.stdout = _FakeStdout(lines)
        self._code = code

    def wait(self):
        return self._code


class TestComposeUpStreaming:
    def test_streams_lines_in_order_with_plain_flags(self, app, monkeypatch):
        import app.services.docker_service as ds
        from app.services.docker_service import DockerService

        captured = {}

        def fake_popen(cmd, **kw):
            captured['cmd'] = cmd
            return _FakeProc(['#1 pulling\n', 'Step 1/3 : FROM\n', 'done\n'], 0)

        monkeypatch.setattr(ds.subprocess, 'Popen', fake_popen)
        monkeypatch.setattr(DockerService, '_compose_cmd_with_overlay',
                            classmethod(lambda cls, p, c=None: ['docker', 'compose']))
        # Pin the compose flavour. The real probe shells out to
        # `docker compose version`, so without this the assertion below passes
        # only on a machine that happens to have a working Docker — everywhere
        # else it silently fell back to v1 and the `--progress` check failed.
        monkeypatch.setattr(DockerService, '_is_compose_v2', classmethod(lambda cls: True))

        got = []
        result = DockerService.compose_up_streaming('/srv/x', on_line=got.append, build=True)
        assert result == {'success': True, 'exit_code': 0}
        assert got == ['#1 pulling', 'Step 1/3 : FROM', 'done']  # order preserved
        # D5 flags present.
        assert '--ansi' in captured['cmd'] and 'never' in captured['cmd']
        assert '--progress' in captured['cmd'] and 'plain' in captured['cmd']
        assert '--build' in captured['cmd']

    def test_compose_v1_never_gets_the_v2_only_progress_flag(self, app, monkeypatch):
        """v1 answers an unknown flag with its usage text and exit 1, which is
        how every template install on a v1 host once failed. `--ansi` is
        understood by both, `--progress` is not."""
        import app.services.docker_service as ds
        from app.services.docker_service import DockerService

        captured = {}

        def fake_popen(cmd, **kw):
            captured['cmd'] = cmd
            return _FakeProc(['done\n'], 0)

        monkeypatch.setattr(ds.subprocess, 'Popen', fake_popen)
        monkeypatch.setattr(DockerService, '_compose_cmd_with_overlay',
                            classmethod(lambda cls, p, c=None: ['docker-compose']))
        monkeypatch.setattr(DockerService, '_is_compose_v2', classmethod(lambda cls: False))

        DockerService.compose_up_streaming('/srv/x', on_line=lambda _: None)
        assert '--ansi' in captured['cmd']
        assert '--progress' not in captured['cmd']

    def test_nonzero_exit_is_failure(self, app, monkeypatch):
        import app.services.docker_service as ds
        from app.services.docker_service import DockerService

        monkeypatch.setattr(ds.subprocess, 'Popen',
                            lambda cmd, **kw: _FakeProc(['boom\n'], 1))
        monkeypatch.setattr(DockerService, '_compose_cmd_with_overlay',
                            classmethod(lambda cls, p, c=None: ['docker', 'compose']))
        got = []
        result = DockerService.compose_up_streaming('/srv/x', on_line=got.append)
        assert result['success'] is False
        assert result['exit_code'] == 1
        assert got == ['boom']

    def test_streaming_failure_persists_stdout_tail(self, app, monkeypatch):
        """Regression-proof the #2 gap: a template-install compose failure now
        persists a real, stdout-bearing failure tail (+ a matching hint)."""
        from app.services.deployment_runner import DeploymentPlanRunner
        from app.services.docker_service import DockerService

        def fake_streaming(cls, project_dir, on_line, detach=True, build=False, compose_file=None):
            on_line('#5 [build 3/5] RUN npm ci')
            on_line('npm ERR! missing script: build')
            return {'success': False, 'exit_code': 1}

        monkeypatch.setattr(DockerService, 'compose_up_streaming', classmethod(fake_streaming))

        job = DeploymentJob(id=str(uuid.uuid4()), kind='template_install', status='pending')
        job.set_plan({'steps': [
            {'type': 'docker.compose.up', 'name': 'Start containers', 'project_dir': '/srv/x'},
        ]})
        db.session.add(job)
        db.session.commit()

        result = DeploymentPlanRunner(job).run()
        assert result['success'] is False
        refreshed = DeploymentJob.query.get(job.id)
        assert refreshed.status == 'failed'
        tail = refreshed.get_result().get('failure_tail') or []
        assert any('npm ERR!' in line for line in tail)  # the REAL reason, streamed
        assert 'Node build' in (refreshed.get_result().get('hint') or '')


class TestPlanIncludedInGet:
    def test_plan_returned_when_requested(self, app, client, auth_headers):
        job = _make_job(kind='app_deploy', status='running')
        res = client.get(f'/api/v1/deployment-jobs/{job.id}?logs=false&plan=true',
                         headers=auth_headers)
        assert res.status_code == 200
        body = res.get_json()['job']
        assert 'plan' in body
        assert body['plan']['steps'][0]['name'] == 'Prepare deployment'

    def test_plan_omitted_by_default(self, app, client, auth_headers):
        job = _make_job(kind='app_deploy', status='running')
        res = client.get(f'/api/v1/deployment-jobs/{job.id}?logs=false', headers=auth_headers)
        assert 'plan' not in res.get_json()['job']
