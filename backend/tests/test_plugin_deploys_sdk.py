"""Deployment kinds contributed by plugins (plugins_sdk.deploys).

Covers the promise the SDK makes: a plugin's work becomes a real DeploymentJob,
so it inherits the Deploy Console, the activity feed and retry without any
frontend change — and a misbehaving handler can never leave a job stuck
'running'.
"""

import pytest

from app import db
from app.models.deployment_job import DeploymentJob
from app.services import deploy_kind_registry
from app.services.deployment_job_service import DeploymentJobService


@pytest.fixture(autouse=True)
def _clean_registry():
    deploy_kind_registry.clear()
    yield
    deploy_kind_registry.clear()


class TestRegistry:
    def test_registers_and_resolves(self):
        handler = lambda job: {'success': True}
        deploy_kind_registry.register('demo.thing', handler)
        assert deploy_kind_registry.get('demo.thing') is handler
        assert 'demo.thing' in deploy_kind_registry.kinds()

    def test_core_kinds_cannot_be_hijacked(self):
        # A plugin overriding app_deploy would silently take over real
        # deployments, so this is refused rather than merely discouraged.
        for kind in ('app_deploy', 'template_install', 'demo_deploy'):
            with pytest.raises(ValueError):
                deploy_kind_registry.register(kind, lambda job: None)

    def test_duplicate_registration_needs_replace(self):
        deploy_kind_registry.register('demo.thing', lambda job: None)
        with pytest.raises(ValueError):
            deploy_kind_registry.register('demo.thing', lambda job: None)
        deploy_kind_registry.register('demo.thing', lambda job: None, replace=True)

    def test_rejects_non_callable(self):
        with pytest.raises(ValueError):
            deploy_kind_registry.register('demo.thing', 'not-callable')


class TestRun:
    def test_start_creates_a_job_addressable_by_the_console(self, app):
        with app.app_context():
            deploy_kind_registry.register('demo.thing', lambda job: {'success': True})
            result = DeploymentJobService.start_registered(
                'demo.thing', steps=['One', 'Two'], wait=True,
            )
            assert result['success'] is True

            job = DeploymentJob.query.get(result['job_id'])
            assert job.kind == 'demo.thing'
            assert job.status == 'succeeded'
            # The step plan is what the console's pipeline strip and the feed's
            # tick bar render from.
            assert [s['name'] for s in job.get_plan()['steps']] == ['One', 'Two']
            assert job.total_steps == 2

    def test_start_refuses_an_unregistered_kind(self, app):
        with app.app_context():
            result = DeploymentJobService.start_registered('nobody.registered', wait=True)
            assert result['success'] is False
            assert 'no handler' in result['error'].lower()

    def test_handler_returning_failure_marks_the_job_failed(self, app):
        with app.app_context():
            deploy_kind_registry.register(
                'demo.thing', lambda job: {'success': False, 'error': 'nope'})
            result = DeploymentJobService.start_registered('demo.thing', wait=True)
            assert result['success'] is False

            job = DeploymentJob.query.get(result['job_id'])
            assert job.status == 'failed'
            assert job.error_message == 'nope'
            assert job.completed_at is not None

    def test_raising_handler_fails_the_job_instead_of_wedging_it(self, app):
        # Third-party code: an exception must still end the job visibly, or the
        # UI shows a deployment spinning forever with no explanation.
        with app.app_context():
            def boom(job):
                raise RuntimeError('handler exploded')

            deploy_kind_registry.register('demo.thing', boom)
            result = DeploymentJobService.start_registered('demo.thing', wait=True)
            assert result['success'] is False

            job = DeploymentJob.query.get(result['job_id'])
            assert job.status == 'failed'
            assert 'handler exploded' in job.error_message
            assert job.completed_at is not None

    def test_handler_may_finalise_the_job_itself(self, app):
        with app.app_context():
            def finalise(job):
                job.status = 'failed'
                job.error_message = 'set by handler'
                db.session.commit()
                return {'success': True}   # deliberately contradicts itself

            deploy_kind_registry.register('demo.thing', finalise)
            result = DeploymentJobService.start_registered('demo.thing', wait=True)

            job = DeploymentJob.query.get(result['job_id'])
            # A handler that took ownership of the outcome keeps it.
            assert job.status == 'failed'
            assert job.error_message == 'set by handler'
            assert result['success'] is False


class TestSdkFacade:
    def test_sdk_exposes_register_start_and_kinds(self, app):
        from app import plugins_sdk

        with app.app_context():
            plugins_sdk.deploys.register('demo.sdk', lambda job: {'success': True})
            assert 'demo.sdk' in plugins_sdk.deploys.kinds()

            result = plugins_sdk.deploys.start('demo.sdk', steps=['Only step'], wait=True)
            assert result['success'] is True
            assert DeploymentJob.query.get(result['job_id']).status == 'succeeded'

    def test_steps_helper_advances_progress_and_records_the_failing_step(self, app):
        from app import plugins_sdk

        with app.app_context():
            def two_steps(job):
                with plugins_sdk.deploys.steps(job) as step:
                    with step('First'):
                        pass
                    with step('Second'):
                        raise RuntimeError('second failed')

            plugins_sdk.deploys.register('demo.steps', two_steps)
            result = plugins_sdk.deploys.start(
                'demo.steps', steps=['First', 'Second'], wait=True)

            job = DeploymentJob.query.get(result['job_id'])
            assert job.status == 'failed'
            # Progress stopped on the step that failed — that is what the
            # console highlights and the feed's tick bar shows in red.
            assert job.current_step == 2
            assert job.current_step_name == 'Second'
