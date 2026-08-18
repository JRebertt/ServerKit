"""Tests for ServerKit system-container protection on the Docker page.

ServerKit's own containers (serverkit-frontend / serverkit-backend) run the
panel itself, so the Docker API must refuse to stop/restart/remove them and the
container list must flag them so the UI can hide lifecycle controls.

The predicate and the list annotation are pure (subprocess is mocked); the
route guard tests drive the real blueprint with an admin JWT.
"""
from unittest.mock import patch

import pytest

from app.services.docker_service import DockerService


class TestIsProtectedName:
    @pytest.mark.parametrize('name', [
        'serverkit-frontend',
        'serverkit_frontend',
        'serverkit-backend',
        'serverkit_backend',
        'serverkit',
        '/serverkit-backend',          # docker inspect Name has a leading slash
        'SERVERKIT-FRONTEND',          # case-insensitive
    ])
    def test_serverkit_names_are_protected(self, name):
        assert DockerService.is_protected_name(name) is True

    @pytest.mark.parametrize('name', [
        'nginx',
        'my-app_web_1',
        'postgres',
        '',
        None,
    ])
    def test_other_names_are_not_protected(self, name):
        assert DockerService.is_protected_name(name) is False


class TestListContainersAnnotation:
    @staticmethod
    def _ps_output(names):
        return '\n'.join(
            '{"ID": "abc%d", "Names": "%s", "Image": "img", "Status": "Up", '
            '"State": "running", "Ports": "", "CreatedAt": "now", "Size": "0B"}'
            % (i, n)
            for i, n in enumerate(names)
        )

    def test_protected_flag_set_per_container(self, fake_subprocess):
        # Scripted through the shared stub kit (plan 75 §G7). The private fake
        # this replaced had only `returncode` and `stdout`; once list_containers
        # went through run_checked, reading `.stderr` off it raised
        # AttributeError, the caller's blanket except swallowed it, and the
        # test saw an empty container list instead of an error. A hand-rolled
        # CompletedProcess stand-in is only correct until something reads the
        # attribute it forgot.
        fake_subprocess.script(['docker', 'ps'],
                               stdout=self._ps_output(['serverkit-backend', 'nginx']))
        containers = DockerService.list_containers()

        by_name = {c['name']: c for c in containers}
        assert by_name['serverkit-backend']['protected'] is True
        assert by_name['nginx']['protected'] is False


class TestIsProtectedContainer:
    def test_resolves_name_from_inspect(self):
        # docker inspect returns the canonical Name with a leading slash.
        with patch.object(DockerService, 'get_container', return_value={'Name': '/serverkit-frontend'}):
            assert DockerService.is_protected_container('abc123') is True

    def test_unknown_container_not_protected(self):
        with patch.object(DockerService, 'get_container', return_value=None):
            assert DockerService.is_protected_container('abc123') is False


class TestRouteGuards:
    """The destructive lifecycle routes must 403 on a protected container."""

    @pytest.mark.parametrize('method,path', [
        ('post', '/api/v1/docker/containers/abc123/stop'),
        ('post', '/api/v1/docker/containers/abc123/restart'),
        ('delete', '/api/v1/docker/containers/abc123'),
    ])
    def test_protected_container_is_rejected(self, client, auth_headers, method, path):
        with patch.object(DockerService, 'is_protected_container', return_value=True):
            resp = getattr(client, method)(path, headers=auth_headers, json={})
        assert resp.status_code == 403
        assert 'system container' in resp.get_json()['error'].lower()

    def test_normal_container_stop_passes_through(self, client, auth_headers):
        with patch.object(DockerService, 'is_protected_container', return_value=False), \
             patch.object(DockerService, 'stop_container', return_value={'success': True}) as stop:
            resp = client.post(
                '/api/v1/docker/containers/abc123/stop', headers=auth_headers, json={}
            )
        assert resp.status_code == 200
        stop.assert_called_once()
