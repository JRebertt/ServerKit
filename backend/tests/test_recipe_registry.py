"""Recipe registry (serverkit-recipes catalog) — browse, fetch, and
server-targeted runs with up-front params."""

import pytest

from app import db
from app.models.deployment_job import DeploymentJob
from app.services import recipe_registry_service
from app.services.manifest_spec_service import ManifestSpecService
from app.services.recipe_execution_service import (
    RecipeExecutionService,
    RecipeStepRegistry,
)
from factories import make_server


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
def _reset_registry_cache():
    """The registry cache is module-level; clear it around each test."""
    recipe_registry_service._cache.update(
        {'ts': 0.0, 'entries': None, 'source': None}
    )
    yield
    recipe_registry_service._cache.update(
        {'ts': 0.0, 'entries': None, 'source': None}
    )


@pytest.fixture(autouse=True)
def _recipe_registry():
    RecipeStepRegistry.clear()
    yield
    RecipeStepRegistry.clear()


class _FakeResp:
    def __init__(self, payload=None, text='', status_code=200):
        self.payload = payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        assert self.status_code == 200

    def json(self):
        return self.payload


def _mock_remote(monkeypatch, manifest_text='version: 1'):
    def fake_get(url, *a, **k):
        if url.endswith('/index.json'):
            return _FakeResp(payload={
                'recipes': [{
                    'slug': 'remote-recipe', 'name': 'Remote recipe',
                    'version': '9.9.9', 'manifest': 'recipes/remote/recipe.yaml',
                }],
            })
        return _FakeResp(text=manifest_text)
    monkeypatch.setattr(recipe_registry_service.requests, 'get', fake_get)
    monkeypatch.setenv('SERVERKIT_RECIPES_REGISTRY_URL', 'https://fake.local/index.json')


def test_bundled_catalog_served_when_registry_disabled(monkeypatch):
    monkeypatch.setenv('SERVERKIT_RECIPES_REGISTRY_URL', '')  # disabled → bundled
    catalog = recipe_registry_service.list_catalog()
    slugs = {e['slug'] for e in catalog}
    assert {'minecraft-java', 'plex', 'jellyfin', 'vaultwarden', 'ollama'} <= slugs
    minecraft = next(e for e in catalog if e['slug'] == 'minecraft-java')
    assert minecraft['requirements']['cpuCores'] == 4
    assert recipe_registry_service.get_entry(
        'minecraft-java')['_manifest_url'].endswith(
        '/recipes/minecraft-java/recipe.yaml')
    assert recipe_registry_service.registry_source_label() == 'bundled'


def test_registry_lists_remote_entries_and_fetches_manifest(client, auth_headers,
                                                            monkeypatch):
    _mock_remote(monkeypatch)
    resp = client.get('/api/v1/recipes/registry', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['source'] == 'remote'
    assert [e['slug'] for e in data['recipes']] == ['remote-recipe']

    resp = client.get('/api/v1/recipes/registry/nope', headers=auth_headers)
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'not_found'

    resp = client.get('/api/v1/recipes/registry/remote-recipe', headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['recipe']['slug'] == 'remote-recipe'
    assert '_manifest_url' not in body['recipe']
    assert body['manifest'] == 'version: 1'


def test_run_requires_server_or_project(client, auth_headers):
    response = client.post('/api/v1/recipes/runs', headers=auth_headers, json={})
    assert response.status_code == 400
    assert 'server_id' in response.get_json()['error']
    assert response.get_json()['code'] == 'validation_error'


def test_server_target_reuses_the_workspace_recipes_project(app):
    from app.models import Project
    from app.services.workspace_service import WorkspaceService

    workspace = WorkspaceService.ensure_default_workspace()
    server = make_server(db, workspace_id=workspace.id)

    resolved = RecipeExecutionService.get_server(server.id)
    first = RecipeExecutionService.get_or_create_project(resolved)
    second = RecipeExecutionService.get_or_create_project(resolved)

    assert first.id == second.id
    assert first.slug == 'recipes'
    assert Project.query.filter_by(
        workspace_id=workspace.id, slug='recipes').count() == 1


def test_params_reject_unknown_keys(client, auth_headers, project):
    response = client.post('/api/v1/recipes/runs', headers=auth_headers, json={
        'project_id': project.id,
        'params': {'not_an_input': 'x'},
        'manifest': {
            'version': 1,
            'capabilities': ['handoff:text'],
            'configure': [{
                'id': 'ask', 'type': 'handoff', 'kind': 'text',
                'input': {'key': 'world_name', 'label': 'World name',
                          'secret': False},
            }],
        },
    })
    assert response.status_code == 400
    assert 'not_an_input' in response.get_json()['error']


def test_params_reject_secret_inputs(client, auth_headers, project):
    response = client.post('/api/v1/recipes/runs', headers=auth_headers, json={
        'project_id': project.id,
        'params': {'rcon_password': 'hunter2'},
        'manifest': {
            'version': 1,
            'capabilities': ['handoff:secret'],
            'configure': [{
                'id': 'ask', 'type': 'handoff', 'kind': 'secret',
                'input': {'key': 'rcon_password', 'label': 'RCON password'},
            }],
        },
    })
    assert response.status_code == 400
    assert 'securely' in response.get_json()['error']


def test_preset_params_satisfy_non_secret_handoffs(project, owner):
    """A param supplied at start time is stored as the handoff value when its
    step is reached — the run never pauses on it."""
    calls = []

    def apply_step(context):
        calls.append(('apply', context.input('world_name')))
        return {'ok': True}

    RecipeStepRegistry.register('apply', 'test-run', apply_step)
    normalized = ManifestSpecService.normalize({
        'version': 1, 'project': 'Preset test',
        'capabilities': ['handoff:text', 'apply:test-run'],
        'configure': [
            {'id': 'ask-world', 'type': 'handoff', 'kind': 'text',
             'input': {'key': 'world_name', 'label': 'World name',
                       'secret': False}},
            {'id': 'run', 'type': 'apply', 'kind': 'test-run',
             'dependsOn': ['ask-world']},
        ],
    })
    started = RecipeExecutionService.start(
        project, normalized, user_id=owner.id,
        params={'world_name': 'survival-01'}, wait=True)
    assert started['success'] is True, started
    job = DeploymentJob.query.get(started['job_id'])
    assert job.status == 'succeeded'
    assert calls == [('apply', 'survival-01')]
