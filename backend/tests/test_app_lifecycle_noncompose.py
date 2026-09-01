"""Start/stop/restart for a docker app that has no compose project.

``app_type == 'docker'`` is not the same as "compose-managed". A build-pack
app is deployed by building an image and running a single container
(``DeploymentService._deploy_docker`` names it ``serverkit-app-<id>``), and
nothing in that path writes a compose file. start/stop/restart nevertheless
called ``docker compose`` for every docker app, so every build-pack app failed
with ``no configuration file provided: not found`` and could never be started
from the panel.

Proving points:
- the compose-project probe is about files on disk, not app_type
- start/restart drive the container, and never touch compose, when there is
  no compose project
- start/restart on an app that was never deployed explain that, rather than
  surfacing a docker error
- stop treats an already-gone container as stopped rather than as a failure
"""
from unittest.mock import patch

import pytest

from app import db
from app.api.apps import _has_local_compose_project
from app.models import Application, User
from factories import headers_for, make_user


@pytest.fixture
def owner(app, db_session):
    return make_user(db_session, role='admin', username='lifecycle-owner')


@pytest.fixture
def buildpack_app(app, owner, tmp_path):
    """A build-pack app: source on disk, no compose file anywhere."""
    application = Application(name='buildpack-app', app_type='docker',
                              status='stopped', root_path=str(tmp_path),
                              buildpack_type='nixpacks', port=4173,
                              user_id=owner.id)
    db.session.add(application)
    db.session.commit()
    return application


# ── the probe ────────────────────────────────────────────────────────────────

def test_docker_app_type_alone_is_not_a_compose_project(buildpack_app):
    assert _has_local_compose_project(buildpack_app) is False


def test_a_compose_file_on_disk_is_a_compose_project(buildpack_app, tmp_path):
    (tmp_path / 'docker-compose.yml').write_text('services: {}\n', encoding='utf-8')
    assert _has_local_compose_project(buildpack_app) is True


# ── start ────────────────────────────────────────────────────────────────────

def test_start_drives_the_container_and_never_compose(client, buildpack_app, owner):
    with patch('app.api.apps.DockerService.get_container', return_value={'Id': 'abc'}), \
            patch('app.api.apps.DockerService.start_container',
                  return_value={'success': True}) as start, \
            patch('app.api.apps.DockerService.compose_up') as compose:
        response = client.post(f'/api/v1/apps/{buildpack_app.id}/start',
                               headers=headers_for(owner))

    assert response.status_code == 200
    start.assert_called_once_with(f'serverkit-app-{buildpack_app.id}')
    compose.assert_not_called()


def test_start_before_any_deploy_says_so(client, buildpack_app, owner):
    with patch('app.api.apps.DockerService.get_container', return_value=None), \
            patch('app.api.apps.DockerService.compose_up') as compose:
        response = client.post(f'/api/v1/apps/{buildpack_app.id}/start',
                               headers=headers_for(owner))

    assert response.status_code == 400
    assert 'not been deployed' in response.get_json()['error']
    compose.assert_not_called()


# ── restart ──────────────────────────────────────────────────────────────────

def test_restart_drives_the_container_and_never_compose(client, buildpack_app, owner):
    with patch('app.api.apps.DockerService.get_container', return_value={'Id': 'abc'}), \
            patch('app.api.apps.DockerService.restart_container',
                  return_value={'success': True}) as restart, \
            patch('app.api.apps.DockerService.compose_restart') as compose:
        response = client.post(f'/api/v1/apps/{buildpack_app.id}/restart',
                               headers=headers_for(owner))

    assert response.status_code == 200
    restart.assert_called_once_with(f'serverkit-app-{buildpack_app.id}')
    compose.assert_not_called()


# ── stop ─────────────────────────────────────────────────────────────────────

def test_stop_of_a_vanished_container_is_not_a_failure(client, buildpack_app, owner):
    with patch('app.api.apps.DockerService.get_container', return_value=None), \
            patch('app.api.apps.DockerService.compose_down') as compose:
        response = client.post(f'/api/v1/apps/{buildpack_app.id}/stop',
                               headers=headers_for(owner))

    assert response.status_code == 200
    assert Application.query.get(buildpack_app.id).status == 'stopped'
    compose.assert_not_called()


def test_stop_drives_the_container_when_it_exists(client, buildpack_app, owner):
    with patch('app.api.apps.DockerService.get_container', return_value={'Id': 'abc'}), \
            patch('app.api.apps.DockerService.stop_container',
                  return_value={'success': True}) as stop, \
            patch('app.api.apps.DockerService.compose_down') as compose:
        response = client.post(f'/api/v1/apps/{buildpack_app.id}/stop',
                               headers=headers_for(owner))

    assert response.status_code == 200
    stop.assert_called_once_with(f'serverkit-app-{buildpack_app.id}')
    compose.assert_not_called()
