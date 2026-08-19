"""Container registry authentication — service, API, and deploy-path wiring.

Covers the proving points from docs/plans/09_CONTAINER_REGISTRY_AUTH.md:
- encrypt/decrypt round-trip, secret never serialized
- `login()` pipes the secret via stdin and never places it on argv
- `pull_image` runs login -> pull -> logout in order, and still logs out on
  pull failure (the try/finally)
- the deploy path resolves an app's registry_id and authenticates before pull
- API CRUD, masking, and admin-gating
"""
import pytest

from app import db
from app.models import Application, ContainerRegistry, User
from app.services.container_registry_service import ContainerRegistryService
from app.services.docker_service import DockerService


# The shared stub kit (plan 75 §G7). These tests used to patch
# `subprocess.run` per-test with a hand-rolled closure; they now script the
# one seam, so a later migration onto run_checked() retargets the fixture
# instead of this file.
from subprocess_stub import FakeProc


def _docker_subcommands(fake):
    """The docker sub-command order seen so far: ['login','pull','logout']."""
    return [argv[1] for argv in fake.commands()
            if len(argv) > 1 and argv[0] == 'docker']


@pytest.fixture
def registry(app):
    reg = ContainerRegistryService.create(
        name='GHCR (acme)', provider='ghcr', registry_url='ghcr.io',
        username='acme-bot', secret='ghp_supersecrettoken',
    )
    return reg


# ── credential storage ──────────────────────────────────────────────────────

def test_secret_encrypted_at_rest_and_round_trips(app, registry):
    # Stored ciphertext must not equal the plaintext, but must decrypt back.
    assert registry.secret_encrypted
    assert registry.secret_encrypted != 'ghp_supersecrettoken'
    assert ContainerRegistryService._password(registry) == 'ghp_supersecrettoken'


def test_to_dict_never_returns_the_secret(app, registry):
    data = registry.to_dict()
    assert 'secret_encrypted' not in data
    assert 'secret' not in data
    assert data['has_secret'] is True
    assert data['login_host'] == 'ghcr.io'


def test_blank_url_defaults_to_docker_hub(app):
    reg = ContainerRegistryService.create(name='Hub', provider='dockerhub',
                                          username='me', secret='pw')
    assert reg.login_host() == ContainerRegistry.DOCKERHUB_HOST


# ── docker login ─────────────────────────────────────────────────────────────

def test_login_pipes_secret_via_stdin_never_on_argv(app, registry, fake_subprocess):
    fake_subprocess.script(['docker', 'login'])
    result = ContainerRegistryService.login(registry)

    assert result['success'] is True
    # argv_for() hands back the RAW argv on purpose: "nowhere on the argv" is a
    # claim about what was actually exec'd, not about a normalised view of it.
    argv = fake_subprocess.argv_for(['docker', 'login'])
    # The secret is on stdin, and NOWHERE on the argv.
    assert fake_subprocess.kwargs_for(['docker', 'login'])['input'] == 'ghp_supersecrettoken'
    assert '--password-stdin' in argv
    assert 'ghp_supersecrettoken' not in argv
    # Sanity: it targets the right host + user.
    assert argv[:2] == ['docker', 'login']
    assert 'ghcr.io' in argv
    assert 'acme-bot' in argv


def test_login_fails_cleanly_without_a_secret(app):
    reg = ContainerRegistryService.create(name='NoSecret', provider='generic',
                                          registry_url='r.example.com', username='u')
    result = ContainerRegistryService.login(reg)
    assert result['success'] is False


def test_ecr_username_defaults_to_AWS(app):
    reg = ContainerRegistryService.create(
        name='ECR', provider='ecr',
        registry_url='123456.dkr.ecr.us-east-1.amazonaws.com', secret='k:s')
    assert reg.login_username() == 'AWS'


# ── pull_image: login -> pull -> logout ordering + finally ───────────────────

def test_pull_image_logs_in_then_pulls_then_logs_out(app, registry, fake_subprocess):
    fake_subprocess.script(['docker'], stdout='ok')

    result = DockerService.pull_image('ghcr.io/acme/app', tag='v1', registry=registry)

    assert result['success'] is True
    assert _docker_subcommands(fake_subprocess) == ['login', 'pull', 'logout']


def test_pull_image_logs_out_even_when_pull_fails(app, registry, fake_subprocess):
    fake_subprocess.script(['docker'], stdout='ok')
    # the narrower rule wins over the broad one: only the pull fails
    fake_subprocess.script(['docker', 'pull'], returncode=1, stderr='denied')

    result = DockerService.pull_image('ghcr.io/acme/app', tag='v1', registry=registry)

    assert result['success'] is False
    # logout still ran despite the failed pull (the try/finally).
    assert _docker_subcommands(fake_subprocess) == ['login', 'pull', 'logout']


def test_pull_image_anonymous_when_no_registry(app, fake_subprocess):
    fake_subprocess.script(['docker'], stdout='ok')

    DockerService.pull_image('nginx', tag='latest')
    assert _docker_subcommands(fake_subprocess) == ['pull']  # no login/logout


def test_test_connection_logs_in_and_out(app, registry, fake_subprocess):
    fake_subprocess.script(['docker'], stdout='ok')

    result = ContainerRegistryService.test_connection(registry)
    assert result['success'] is True
    assert _docker_subcommands(fake_subprocess) == ['login', 'logout']


# ── proving test: deploy path authenticates before pull ──────────────────────

def test_start_app_authenticates_registry_before_compose_up(client, auth_headers, app, registry, monkeypatch, fake_subprocess):
    """The primary path for a private-image app is compose. Starting a
    registry-bound docker app must `docker login` before `compose up`, then log
    out (the try/finally around the local compose branch)."""
    owner = User.query.filter_by(username='testadmin').first()
    application = Application(name='compose-priv', app_type='docker', status='stopped',
                             root_path='/tmp/compose-priv', registry_id=registry.id,
                             user_id=owner.id)
    db.session.add(application)
    db.session.commit()

    # compose_up is stubbed at the service, not at subprocess, so the ordering
    # assertion needs one interleaved list rather than the fixture's call log.
    order = []

    def record(argv, kwargs):
        order.append(argv[1] if len(argv) > 1 else argv[0])  # login / logout
        return FakeProc(returncode=0)

    fake_subprocess.when(['docker'], record)
    monkeypatch.setattr(DockerService, 'compose_up',
                        staticmethod(lambda *a, **k: order.append('compose_up') or {'success': True}))

    resp = client.post(f'/api/v1/apps/{application.id}/start', headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    assert 'login' in order and 'compose_up' in order and 'logout' in order
    assert order.index('login') < order.index('compose_up') < order.index('logout')


def test_deploy_docker_authenticates_before_pull(app, registry, monkeypatch, fake_subprocess):
    """A Docker app bound to a registry must `docker login` before the image is
    pulled, then run the container."""
    from app.services.deployment_service import DeploymentService
    from app.services.env_service import EnvService
    from app.models.deployment import Deployment

    user = User(email='o@test.local', username='owner',
                password_hash='x', role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.commit()

    application = Application(name='private-app', app_type='docker', status='stopped',
                             docker_image='ghcr.io/acme/app:v1', registry_id=registry.id,
                             user_id=user.id)
    db.session.add(application)
    db.session.commit()

    deployment = Deployment(app_id=application.id, version=1, version_tag='v1',
                            status='deploying', image_tag='ghcr.io/acme/app:v1',
                            deployed_by=user.id)
    db.session.add(deployment)
    db.session.commit()

    order = []

    def record(argv, kwargs):
        order.append(argv[1] if len(argv) > 1 else argv[0])
        return FakeProc(returncode=0, stdout='')

    fake_subprocess.when(['docker'], record)
    monkeypatch.setattr(DockerService, 'get_container', staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(EnvService, 'get_effective_env', staticmethod(lambda *a, **k: {}))
    monkeypatch.setattr(DockerService, 'run_container',
                        staticmethod(lambda **k: order.append('run') or {'success': True, 'container_id': 'abc'}))

    result = DeploymentService._deploy_docker(application, deployment)

    assert result['success'] is True
    assert 'login' in order and 'pull' in order and 'run' in order
    assert order.index('login') < order.index('pull') < order.index('run')


# ── API: CRUD, masking, admin-gating ─────────────────────────────────────────

def test_api_crud_and_masking(client, auth_headers, app):
    # Create
    resp = client.post('/api/v1/connections/registries', headers=auth_headers, json={
        'name': 'GitLab reg', 'provider': 'gitlab', 'registry_url': 'registry.gitlab.com',
        'username': 'deploy', 'secret': 'glpat-abc',
    })
    assert resp.status_code == 201, resp.get_json()
    created = resp.get_json()['registry']
    assert created['has_secret'] is True
    assert 'secret' not in created and 'secret_encrypted' not in created

    reg_id = created['id']

    # List (masked)
    resp = client.get('/api/v1/connections/registries', headers=auth_headers)
    assert resp.status_code == 200
    listed = resp.get_json()['registries']
    assert any(r['id'] == reg_id for r in listed)
    assert all('secret' not in r and 'secret_encrypted' not in r for r in listed)

    # Update label without touching the secret
    resp = client.put(f'/api/v1/connections/registries/{reg_id}', headers=auth_headers,
                      json={'name': 'GitLab (renamed)'})
    assert resp.status_code == 200
    assert resp.get_json()['registry']['name'] == 'GitLab (renamed)'
    reg = ContainerRegistryService.get(reg_id)
    assert ContainerRegistryService._password(reg) == 'glpat-abc'  # secret preserved

    # Delete
    resp = client.delete(f'/api/v1/connections/registries/{reg_id}', headers=auth_headers)
    assert resp.status_code == 200
    assert ContainerRegistryService.get(reg_id) is None


def test_api_create_requires_admin(client, app):
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    dev = User(email='dev@test.local', username='dev',
               password_hash=generate_password_hash('x'),
               role=User.ROLE_DEVELOPER, is_active=True)
    db.session.add(dev)
    db.session.commit()
    headers = {'Authorization': f'Bearer {create_access_token(identity=dev.id)}'}

    resp = client.post('/api/v1/connections/registries', headers=headers,
                       json={'name': 'x', 'provider': 'ghcr'})
    assert resp.status_code == 403


def test_registry_appears_in_unified_connections(client, auth_headers, app):
    client.post('/api/v1/connections/registries', headers=auth_headers, json={
        'name': 'GHCR', 'provider': 'ghcr', 'registry_url': 'ghcr.io',
        'username': 'bot', 'secret': 'tok',
    })
    resp = client.get('/api/v1/connections', headers=auth_headers)
    assert resp.status_code == 200
    conns = resp.get_json()['connections']
    reg_entries = [c for c in conns if c['kind'] == 'registry']
    assert len(reg_entries) == 1
    assert reg_entries[0]['encrypted'] is True
    assert 'secret' not in reg_entries[0]
