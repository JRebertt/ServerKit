"""Per-app managed volumes — model, service, deploy wiring, and API.

Covers the proving points from docs/plans/10_APP_MANAGED_VOLUMES.md:
- create persists a row AND a namespaced Docker volume
- a duplicate mount path is refused
- delete(wipe=False) never calls `docker volume rm`
- delete(wipe=True) refuses while a container runs off the volume
- the single-container deploy passes `-v <docker_volume>:<mount>` to docker run
- a generated compose stack emits a top-level `volumes:` block (named volume,
  not a relative bind mount)
"""
import subprocess

import pytest
import yaml

from app import db
from app.models import Application, AppVolume, User
from app.services.docker_service import DockerService
from app.services.volume_service import VolumeService, VolumeError


# The shared stub kit (plan 75 §G7) — this class was pasted
# byte-identical in four test modules.
from subprocess_stub import FakeProc as _FakeProc


@pytest.fixture
def owner(app):
    user = User(email='vol@test.local', username='volowner',
                password_hash='x', role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def docker_app(app, owner):
    application = Application(name='vol-app', app_type='docker', status='stopped',
                             root_path='/tmp/vol-app', user_id=owner.id)
    db.session.add(application)
    db.session.commit()
    return application


@pytest.fixture
def fake_docker(monkeypatch):
    """Stub the docker volume plumbing; record created/removed volume names."""
    created, removed = [], []
    monkeypatch.setattr(DockerService, 'create_volume',
                        staticmethod(lambda name, driver='local': created.append(name) or {'success': True, 'volume_name': name}))
    monkeypatch.setattr(DockerService, 'remove_volume',
                        staticmethod(lambda name, force=False: removed.append(name) or {'success': True}))
    monkeypatch.setattr(DockerService, 'inspect_volume',
                        staticmethod(lambda name: {'present': True, 'mountpoint': f'/var/lib/docker/volumes/{name}/_data', 'driver': 'local'}))
    monkeypatch.setattr(DockerService, 'containers_using_volume',
                        staticmethod(lambda name, running_only=False: []))
    return {'created': created, 'removed': removed}


# ── create / list ────────────────────────────────────────────────────────────

def test_create_persists_row_and_namespaced_docker_volume(docker_app, fake_docker):
    volume = VolumeService.create(docker_app, name='uploads', mount_path='/var/www/html/wp-content/uploads')

    assert volume.id is not None
    assert volume.docker_volume_name == f'serverkit-app-{docker_app.id}-uploads'
    assert fake_docker['created'] == [volume.docker_volume_name]
    assert AppVolume.query.filter_by(application_id=docker_app.id).count() == 1


def test_duplicate_mount_path_is_refused(docker_app, fake_docker):
    VolumeService.create(docker_app, name='data', mount_path='/data')
    with pytest.raises(VolumeError):
        VolumeService.create(docker_app, name='data2', mount_path='/data')


def test_mount_path_must_be_absolute(docker_app, fake_docker):
    with pytest.raises(VolumeError):
        VolumeService.create(docker_app, name='rel', mount_path='relative/path')


def test_slug_collision_gets_unique_docker_name(docker_app, fake_docker):
    v1 = VolumeService.create(docker_app, name='db data', mount_path='/a')
    v2 = VolumeService.create(docker_app, name='db-data', mount_path='/b')
    assert v1.docker_volume_name != v2.docker_volume_name  # same slug, disambiguated


def test_list_for_app_joins_live_state(docker_app, fake_docker):
    VolumeService.create(docker_app, name='uploads', mount_path='/uploads')
    rows = VolumeService.list_for_app(docker_app)
    assert len(rows) == 1
    v, live = rows[0]
    assert live['present'] is True
    assert live['mountpoint'].endswith('/_data')


# ── delete / wipe safety ─────────────────────────────────────────────────────

def test_delete_without_wipe_never_removes_docker_volume(docker_app, fake_docker):
    volume = VolumeService.create(docker_app, name='keep', mount_path='/keep')
    VolumeService.delete(volume, wipe=False)
    assert fake_docker['removed'] == []                     # docker volume rm NOT called
    assert AppVolume.query.filter_by(application_id=docker_app.id).count() == 0


def test_wipe_removes_docker_volume_when_stopped(docker_app, fake_docker):
    volume = VolumeService.create(docker_app, name='gone', mount_path='/gone')
    dv = volume.docker_volume_name
    VolumeService.delete(volume, wipe=True)
    assert fake_docker['removed'] == [dv]


def test_wipe_refused_while_container_running(docker_app, fake_docker, monkeypatch):
    volume = VolumeService.create(docker_app, name='busy', mount_path='/busy')
    monkeypatch.setattr(DockerService, 'containers_using_volume',
                        staticmethod(lambda name, running_only=False: ['serverkit-app-x'] if running_only else []))
    with pytest.raises(VolumeError):
        VolumeService.delete(volume, wipe=True)
    assert fake_docker['removed'] == []                     # nothing wiped
    assert AppVolume.query.filter_by(application_id=docker_app.id).count() == 1  # row kept


def test_wipe_refused_while_app_running(docker_app, fake_docker):
    docker_app.status = 'running'
    db.session.commit()
    volume = VolumeService.create(docker_app, name='live', mount_path='/live')
    with pytest.raises(VolumeError):
        VolumeService.delete(volume, wipe=True)
    assert fake_docker['removed'] == []


# ── mount wiring: single-container + compose ─────────────────────────────────

def test_run_args_returns_mount_specs(docker_app, fake_docker):
    VolumeService.create(docker_app, name='data', mount_path='/data')
    VolumeService.create(docker_app, name='ro', mount_path='/ro', read_only=True)
    specs = VolumeService.run_args(docker_app)
    assert f'serverkit-app-{docker_app.id}-data:/data' in specs
    assert f'serverkit-app-{docker_app.id}-ro:/ro:ro' in specs


def test_deploy_docker_mounts_managed_volume(docker_app, fake_docker, monkeypatch):
    """The proving test: a single-container deploy passes -v for each volume."""
    from app.services.deployment_service import DeploymentService
    from app.services.env_service import EnvService
    from app.models.deployment import Deployment

    VolumeService.create(docker_app, name='uploads', mount_path='/uploads')
    docker_app.docker_image = 'nginx:latest'
    deployment = Deployment(app_id=docker_app.id, version=1, version_tag='v1',
                            status='deploying', image_tag='nginx:latest',
                            deployed_by=docker_app.user_id)
    db.session.add(deployment)
    db.session.commit()

    captured = {}

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ['docker', 'run']:
            captured['cmd'] = cmd
        return _FakeProc(returncode=0, stdout='cid123')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(DockerService, 'get_container', staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(EnvService, 'get_effective_env', staticmethod(lambda *a, **k: {}))

    result = DeploymentService._deploy_docker(docker_app, deployment)
    assert result['success'] is True
    cmd = captured['cmd']
    assert '-v' in cmd
    assert f'serverkit-app-{docker_app.id}-uploads:/uploads' in cmd


def test_compose_generation_emits_top_level_named_volume(tmp_path, docker_app, fake_docker):
    """A generated compose stack references a named volume + declares it at the
    top level — no relative bind mount for that path."""
    VolumeService.create(docker_app, name='db-data', mount_path='/var/lib/mysql')
    frag = VolumeService.compose_fragment(docker_app)
    dv = f'serverkit-app-{docker_app.id}-db-data'
    assert frag['service'] == [f'{dv}:/var/lib/mysql']
    assert dv in frag['top_level']

    app_path = str(tmp_path / 'stack')
    DockerService.create_docker_app(app_path, 'web', 'nginx:latest',
                                    volumes=frag['service'],
                                    named_volumes=list(frag['top_level'].keys()))
    with open(f'{app_path}/docker-compose.yml') as f:
        compose = yaml.safe_load(f)

    # Top-level volumes block declares the named volume ...
    assert dv in (compose.get('volumes') or {})
    # ... and the service references it, not a relative ./ bind mount.
    svc_vols = compose['services']['web']['volumes']
    assert f'{dv}:/var/lib/mysql' in svc_vols
    assert not any(str(v).startswith('./') for v in svc_vols)


def test_convert_bind_mount_creates_managed_volume(docker_app, fake_docker, tmp_path, monkeypatch):
    """convert_bind_mount creates a tracked volume for an existing host dir. The
    data-copy container is best-effort; stub subprocess so the test is hermetic."""
    monkeypatch.setattr(subprocess, 'run',
                        lambda *a, **k: _FakeProc(returncode=0))
    src = tmp_path / 'olddata'
    src.mkdir()

    volume = VolumeService.convert_bind_mount(docker_app, str(src), '/var/lib/mysql', name='db')
    assert volume.mount_path == '/var/lib/mysql'
    assert volume.docker_volume_name == f'serverkit-app-{docker_app.id}-db'
    assert AppVolume.query.filter_by(application_id=docker_app.id).count() == 1


# ── API ──────────────────────────────────────────────────────────────────────

def test_api_attach_list_detach(client, auth_headers, app, fake_docker):
    # auth_headers creates its own admin; make an app owned generically
    owner = User.query.filter_by(username='testadmin').first()
    application = Application(name='api-vol', app_type='docker', status='stopped',
                             root_path='/tmp/api-vol', user_id=owner.id)
    db.session.add(application)
    db.session.commit()

    # attach
    resp = client.post(f'/api/v1/apps/{application.id}/volumes', headers=auth_headers,
                       json={'name': 'uploads', 'mount_path': '/uploads'})
    assert resp.status_code == 201, resp.get_json()
    vid = resp.get_json()['volume']['id']

    # list (with live state)
    resp = client.get(f'/api/v1/apps/{application.id}/volumes', headers=auth_headers)
    assert resp.status_code == 200
    vols = resp.get_json()['volumes']
    assert len(vols) == 1 and vols[0]['mount_path'] == '/uploads'
    assert vols[0]['present'] is True

    # duplicate mount path -> 400
    resp = client.post(f'/api/v1/apps/{application.id}/volumes', headers=auth_headers,
                       json={'name': 'dup', 'mount_path': '/uploads'})
    assert resp.status_code == 400

    # detach (no wipe) -> row gone, docker volume untouched
    resp = client.delete(f'/api/v1/apps/{application.id}/volumes/{vid}', headers=auth_headers)
    assert resp.status_code == 200
    assert fake_docker['removed'] == []
    assert AppVolume.query.filter_by(application_id=application.id).count() == 0
