"""Flow A app deploys — DeploymentJob kind 'app_deploy' + unified job
'deploy.app' (the repo-based create flow deploys through the same observable
pipeline as template installs)."""
import uuid

import pytest

from app import db
from app.jobs import registry
from app.jobs.models import Job
from app.jobs.service import JobService, GROUP_SLUG, QUEUE_SLUG
from app.jobs.consumer import JobConsumer
from app.queue_bus.service import QueueBusService


@pytest.fixture(autouse=True)
def reset_jobs(app):
    """Clean broker + handler registry before each test (same as test_jobs.py)."""
    QueueBusService.reset_broker()
    registry.clear()
    yield
    registry.clear()


def _drain_once(consumer=None):
    consumer = consumer or JobConsumer()
    messages = QueueBusService.receive(GROUP_SLUG, QUEUE_SLUG, max_messages=1)
    assert messages, 'expected a queued job message'
    consumer.process_message(messages[0])
    return messages[0]


def _make_app(name='repo-app'):
    from app.models.application import Application
    a = Application(name=name, app_type='docker', status='stopped',
                    root_path='/srv/' + name, user_id=1)
    db.session.add(a)
    db.session.commit()
    return a


def _make_job(app_id, kind='app_deploy', status='pending'):
    from app.models.deployment_job import DeploymentJob
    job = DeploymentJob(id=str(uuid.uuid4()), kind=kind, status=status,
                        app_id=app_id, trigger='install')
    job.set_plan({'app_id': app_id, 'steps': [{'name': 'Prepare deployment'},
                                              {'name': 'Build application'},
                                              {'name': 'Start containers'}]})
    db.session.add(job)
    db.session.commit()
    return job


class TestEnqueueAppDeploy:
    def test_creates_deployment_job_and_enqueues_unified_job(self, app):
        from app.services.deployment_job_service import DeploymentJobService
        from app.models.deployment_job import DeploymentJob
        with app.app_context():
            a = _make_app()
            result = DeploymentJobService.enqueue_app_deploy(a, user_id=1, trigger='install')

            assert result['success'] is True
            job = DeploymentJob.query.get(result['job_id'])
            assert job is not None
            assert job.kind == 'app_deploy'
            assert job.status == 'pending'  # enqueued, not run inline
            assert job.app_id == a.id
            assert job.requested_by == 1
            assert job.trigger == 'install'
            assert job.total_steps == 3  # prepare / build / start

            unified = Job.query.filter_by(kind='deploy.app', owner_id=job.id).first()
            assert unified is not None
            assert unified.owner_type == 'deployment_job'
            assert unified.get_payload() == {'deployment_job_id': job.id}
            assert unified.max_attempts == 1
            assert unified.correlation_id == job.correlation_id

    def test_enqueue_failure_marks_job_failed(self, app, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        from app.models.deployment_job import DeploymentJob

        def _boom(job):
            raise RuntimeError('queue bus down')

        monkeypatch.setattr(DeploymentJobService, '_enqueue_app_deploy',
                            classmethod(lambda cls, job: _boom(job)))
        with app.app_context():
            a = _make_app()
            result = DeploymentJobService.enqueue_app_deploy(a, user_id=1)
            assert result['success'] is False
            job = DeploymentJob.query.get(result['job_id'])
            assert job.status == 'failed'
            assert 'queue bus down' in (job.error_message or '')
            assert job.completed_at is not None


class TestRunAppDeployJob:
    def test_success_marks_job_succeeded_with_logs(self, app, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        from app.services.deployment_service import DeploymentService
        from app.models.deployment_job import DeploymentJob

        seen = {}

        def fake_deploy(cls, app_id, user_id=None, trigger='manual', log_callback=None, **kw):
            seen['app_id'] = app_id
            seen['trigger'] = trigger
            if log_callback:
                log_callback('Starting build for repo-app...')
            return {'success': True, 'deployment': {'id': 42}}

        monkeypatch.setattr(DeploymentService, 'deploy', classmethod(fake_deploy))
        with app.app_context():
            a = _make_app()
            job = _make_job(a.id)

            result = DeploymentJobService.run_job(job.id)

            assert result['success'] is True
            assert result['app_id'] == a.id
            assert seen['app_id'] == a.id
            assert seen['trigger'] == 'install'

            refreshed = DeploymentJob.query.get(job.id)
            assert refreshed.status == 'succeeded'
            assert refreshed.completed_at is not None
            assert refreshed.get_result()['app_id'] == a.id
            assert refreshed.deployment_id == 42

            messages = [log.message for log in refreshed.logs.all()]
            assert any('Deploying application' in m for m in messages)
            assert any('Starting build' in m for m in messages)  # streamed log_callback
            assert any('Containers started' in m for m in messages)
            assert any('now live' in m for m in messages)

    def test_failure_marks_job_failed_with_error(self, app, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        from app.services.deployment_service import DeploymentService
        from app.models.deployment_job import DeploymentJob

        monkeypatch.setattr(DeploymentService, 'deploy',
                            classmethod(lambda cls, app_id, **kw: {
                                'success': False, 'error': 'build boom'}))
        with app.app_context():
            a = _make_app()
            job = _make_job(a.id)

            result = DeploymentJobService.run_job(job.id)

            assert result['success'] is False
            refreshed = DeploymentJob.query.get(job.id)
            assert refreshed.status == 'failed'
            assert refreshed.error_message == 'build boom'
            assert refreshed.completed_at is not None
            error_logs = [log for log in refreshed.logs.all() if log.level == 'error']
            assert error_logs and 'build boom' in error_logs[-1].message

    def test_missing_app_fails_visibly(self, app):
        from app.services.deployment_job_service import DeploymentJobService
        from app.models.deployment_job import DeploymentJob
        with app.app_context():
            job = _make_job(app_id=99999)  # no such application
            result = DeploymentJobService.run_job(job.id)
            assert result['success'] is False
            refreshed = DeploymentJob.query.get(job.id)
            assert refreshed.status == 'failed'
            assert 'not found' in (refreshed.error_message or '').lower()


class TestDeployAppUnifiedHandler:
    def test_register_jobs_adds_handler(self, app):
        from app.services.deployment_job_service import DeploymentJobService, APP_JOB_KIND
        with app.app_context():
            DeploymentJobService.register_jobs()
            assert APP_JOB_KIND == 'deploy.app'
            assert registry.is_registered('deploy.app')
            assert registry.is_registered('deploy.install')

    def test_handler_success(self, app, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService

        monkeypatch.setattr(DeploymentJobService, 'run_job',
                            staticmethod(lambda job_id: {'success': True, 'app_id': 7}))
        with app.app_context():
            DeploymentJobService.register_jobs()
            unified = JobService.enqueue('deploy.app', {'deployment_job_id': 'dep-1'},
                                         max_attempts=1)
            _drain_once()

            refreshed = Job.query.get(unified.id)
            assert refreshed.status == Job.STATUS_SUCCEEDED
            assert refreshed.get_result()['app_id'] == 7

    def test_handler_failure_raises_and_marks_unified_failed(self, app, monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService

        monkeypatch.setattr(DeploymentJobService, 'run_job',
                            staticmethod(lambda job_id: {'success': False, 'error': 'build boom'}))
        with app.app_context():
            DeploymentJobService.register_jobs()
            unified = JobService.enqueue('deploy.app', {'deployment_job_id': 'dep-2'},
                                         max_attempts=1)
            _drain_once()

            refreshed = Job.query.get(unified.id)
            assert refreshed.status == Job.STATUS_FAILED
            assert 'build boom' in (refreshed.error_message or '')


class TestFromRepositoryDeployWiring:
    """POST /apps/from-repository must hand the new service to the deploy
    pipeline and surface the job id (and must still succeed when it can't)."""

    def _mock_create_stack(self, monkeypatch, enqueue_result=None, enqueue_exc=None):
        from app.services.git_service import GitService
        from app.services.build_service import BuildService
        from app.services.repository_manifest_service import RepositoryManifestService
        from app.services.manifest_persistence_service import ManifestPersistenceService
        from app.services.deployment_job_service import DeploymentJobService

        monkeypatch.setattr(GitService, 'clone_repository',
                            classmethod(lambda cls, *a, **kw: {'success': True}))
        monkeypatch.setattr(RepositoryManifestService, 'analyze_path',
                            classmethod(lambda cls, *a, **kw: {
                                'recommended': {}, 'strategy': None, 'manifests': []}))
        monkeypatch.setattr(BuildService, 'detect_build_method',
                            classmethod(lambda cls, *a, **kw: {
                                'build_method': 'dockerfile', 'has_dockerfile': True,
                                'has_docker_compose': False, 'language': 'python',
                                'framework': 'flask', 'detected_files': ['Dockerfile']}))
        monkeypatch.setattr(GitService, 'configure_deployment',
                            classmethod(lambda cls, *a, **kw: {
                                'success': True, 'webhook_url': 'http://panel/hooks/1'}))
        monkeypatch.setattr(BuildService, 'configure_build',
                            classmethod(lambda cls, *a, **kw: {
                                'success': True, 'config': {'build_method': 'dockerfile'}}))
        monkeypatch.setattr(ManifestPersistenceService, 'apply_import',
                            classmethod(lambda cls, *a, **kw: None))

        def fake_enqueue(cls, app, user_id=None, trigger='install'):
            if enqueue_exc:
                raise enqueue_exc
            return enqueue_result

        monkeypatch.setattr(DeploymentJobService, 'enqueue_app_deploy',
                            classmethod(fake_enqueue))

    def test_response_contains_deploy_job_id(self, app, client, auth_headers, monkeypatch):
        self._mock_create_stack(monkeypatch, enqueue_result={'success': True, 'job_id': 'dj-123'})
        res = client.post('/api/v1/apps/from-repository', headers=auth_headers, json={
            'name': 'repo-svc', 'repo_url': 'https://github.com/acme/repo-svc.git',
        })
        assert res.status_code == 201
        body = res.get_json()
        assert body['deploy_job_id'] == 'dj-123'
        assert body['app']['name'] == 'repo-svc'

    def test_enqueue_failure_does_not_fail_creation(self, app, client, auth_headers, monkeypatch):
        self._mock_create_stack(monkeypatch, enqueue_exc=RuntimeError('queue bus down'))
        res = client.post('/api/v1/apps/from-repository', headers=auth_headers, json={
            'name': 'repo-svc2', 'repo_url': 'https://github.com/acme/repo-svc2.git',
        })
        assert res.status_code == 201
        assert res.get_json()['deploy_job_id'] is None


class TestListJobsAppIdFilter:
    def test_service_filter(self, app):
        from app.services.deployment_job_service import DeploymentJobService
        with app.app_context():
            j1 = _make_job(app_id=1)
            j2 = _make_job(app_id=2)
            j3 = _make_job(app_id=None, kind='template_install')

            filtered = DeploymentJobService.list_jobs(app_id=1)
            assert [j['id'] for j in filtered] == [j1.id]

            everything = DeploymentJobService.list_jobs()
            assert {j['id'] for j in everything} == {j1.id, j2.id, j3.id}

    def test_api_filter(self, app, client, auth_headers):
        with app.app_context():
            a1 = _make_app('filter-svc1')
            a2 = _make_app('filter-svc2')
            j1 = _make_job(app_id=a1.id)
            _make_job(app_id=a2.id)
            a1_id, j1_id = a1.id, j1.id
        res = client.get(f'/api/v1/deployment-jobs?app_id={a1_id}', headers=auth_headers)
        assert res.status_code == 200
        jobs = res.get_json()['jobs']
        assert [j['id'] for j in jobs] == [j1_id]
        assert jobs[0]['app_id'] == a1_id
