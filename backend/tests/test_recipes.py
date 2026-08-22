"""Plan 68 Phase 0 — Recipe capability, resume, handoff and API contracts."""

import json

from datetime import datetime, timedelta

import pytest

from app import db
from app.models.deployment_job import DeploymentJob
from app.models.application_manifest import ApplicationManifest
from app.models.secret_vault import Secret, SecretVault
from app.services.manifest_spec_service import ManifestSpecService
from app.services.recipe_execution_service import (
    HANDOFF_VAULT_SLUG,
    RECIPE_WAITING,
    RecipeExecutionService,
    RecipeStepRegistry,
)


@pytest.fixture
def project(app):
    from app.models import Environment, Project
    from app.services.workspace_service import WorkspaceService

    workspace = WorkspaceService.ensure_default_workspace()
    row = Project(workspace_id=workspace.id, name='Recipe test', slug='recipe-test')
    db.session.add(row)
    db.session.commit()
    environment = Environment(
        project_id=row.id, name='Production', slug='production', is_default=True)
    db.session.add(environment)
    db.session.commit()
    return row


@pytest.fixture
def owner(app):
    from app.models import User
    row = User(
        username='recipe-owner', email='recipe-owner@test.local',
        role=User.ROLE_ADMIN, is_active=True)
    row.set_password('testpass')
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture(autouse=True)
def _recipe_registry():
    RecipeStepRegistry.clear()
    yield
    RecipeStepRegistry.clear()


def _manifest():
    return {
        'version': 1,
        'project': 'Media server',
        'capabilities': [
            'apply:test-before', 'handoff:token', 'apply:test-after',
            'verify:test-outcome',
        ],
        'configure': [
            {'id': 'before', 'type': 'apply', 'kind': 'test-before'},
            {
                'id': 'claim', 'type': 'handoff', 'kind': 'token',
                'dependsOn': ['before'], 'ttlSeconds': 240,
                'input': {'key': 'CLAIM_TOKEN', 'label': 'Claim token', 'secret': True},
            },
            {'id': 'after', 'type': 'apply', 'kind': 'test-after',
             'dependsOn': ['claim']},
        ],
        'verify': [
            {'id': 'proof', 'kind': 'test-outcome', 'dependsOn': ['after']},
        ],
    }


def test_recipe_refuses_unsupported_capability_before_creating_job(project, owner):
    normalized = ManifestSpecService.normalize({
        'version': 1,
        'capabilities': ['apply:not-installed'],
        'configure': [{'id': 'nope', 'type': 'apply', 'kind': 'not-installed'}],
    })
    before = DeploymentJob.query.count()
    result = RecipeExecutionService.start(
        project, normalized, user_id=owner.id, wait=True)
    assert result['success'] is False
    assert result['unsupported_capabilities'] == ['apply:not-installed']
    assert DeploymentJob.query.count() == before


def test_recipe_api_refuses_unsupported_capability_before_persisting(
        client, auth_headers, project):
    before = ApplicationManifest.query.count()
    response = client.post('/api/v1/recipes/runs', headers=auth_headers, json={
        'project_id': project.id,
        'manifest': {
            'version': 1,
            'capabilities': ['apply:not-installed'],
            'configure': [
                {'id': 'nope', 'type': 'apply', 'kind': 'not-installed'},
            ],
        },
    })
    assert response.status_code == 400
    assert response.get_json()['unsupported_capabilities'] == ['apply:not-installed']
    assert ApplicationManifest.query.count() == before


def test_recipe_pauses_resumes_and_does_not_repeat_completed_steps(project, owner):
    calls = []

    def before(context):
        calls.append('before')
        return {'prepared': True}

    def after(context):
        calls.append(('after', context.input('CLAIM_TOKEN')))
        return {'configured': True, 'token': 'must-be-redacted'}

    def verify(context):
        calls.append('verify')
        return {'verified': True}

    RecipeStepRegistry.register('apply', 'test-before', before)
    RecipeStepRegistry.register('apply', 'test-after', after)
    RecipeStepRegistry.register('verify', 'test-outcome', verify)
    normalized = ManifestSpecService.normalize(_manifest())

    started = RecipeExecutionService.start(
        project, normalized, user_id=owner.id,
        slug='media-server', title='Media server', wait=True)
    assert started['success'] is True
    assert started['paused'] is True
    job = DeploymentJob.query.get(started['job_id'])
    assert job.status == RECIPE_WAITING
    assert job.to_dict()['requires_action'] is True
    assert job.get_result()['handoff']['step_id'] == 'claim'
    assert calls == ['before']

    resumed = RecipeExecutionService.submit_handoff(
        job, step_id='claim', value='short-lived-token',
        user_id=owner.id, wait=True)
    assert resumed['success'] is True
    job = DeploymentJob.query.get(job.id)
    assert job.status == 'succeeded'
    assert calls == ['before', ('after', 'short-lived-token'), 'verify']
    completed = job.get_result()['completed_steps']
    assert set(completed) == {'before', 'claim', 'after', 'proof'}
    assert completed['after']['result']['token'] == '[redacted]'
    assert job.get_result()['verified'] is True
    assert 'short-lived-token' not in json.dumps(job.to_dict(include_plan=True))

    vault = SecretVault.query.filter_by(slug=HANDOFF_VAULT_SLUG).first()
    assert vault is not None
    assert Secret.query.filter_by(vault_id=vault.id).count() == 0


def test_expired_handoff_is_reprompted(project, owner):
    RecipeStepRegistry.register('apply', 'test-before', lambda context: {'ok': True})
    RecipeStepRegistry.register('apply', 'test-after', lambda context: {'ok': True})
    RecipeStepRegistry.register('verify', 'test-outcome', lambda context: {'ok': True})
    normalized = ManifestSpecService.normalize(_manifest())
    started = RecipeExecutionService.start(project, normalized, user_id=owner.id, wait=True)
    job = DeploymentJob.query.get(started['job_id'])

    RecipeExecutionService._store_handoff_secret(
        job, 'claim', 'expired', user_id=owner.id,
        expires_at=datetime.utcnow() - timedelta(seconds=1))
    job.status = 'pending'
    db.session.commit()
    rerun = RecipeExecutionService.run(job)
    assert rerun['paused'] is True
    assert job.status == RECIPE_WAITING
    assert RecipeExecutionService._handoff_secret(job.id, 'claim') is None


def test_recipe_api_starts_and_resumes_same_run(client, auth_headers, project, owner):
    RecipeStepRegistry.register('apply', 'test-before', lambda context: {'ok': True})
    RecipeStepRegistry.register('apply', 'test-after', lambda context: {
        'has_input': context.input('CLAIM_TOKEN') == 'api-token'})
    RecipeStepRegistry.register('verify', 'test-outcome', lambda context: {'ok': True})

    response = client.post(
        '/api/v1/recipes/runs?wait=true', headers=auth_headers,
        json={'project_id': project.id, 'slug': 'media-server', 'manifest': _manifest()})
    assert response.status_code == 200, response.get_json()
    job_id = response.get_json()['job_id']
    assert response.get_json()['paused'] is True

    response = client.post(
        f'/api/v1/recipes/runs/{job_id}/handoffs/claim?wait=true',
        headers=auth_headers, json={'value': 'api-token'})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['job']['id'] == job_id
    assert response.get_json()['job']['status'] == 'succeeded'


def test_recipe_mutations_require_admin(client, project):
    response = client.post('/api/v1/recipes/runs', json={
        'project_id': project.id, 'manifest': _manifest(),
    })
    assert response.status_code in (401, 422)
