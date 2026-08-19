"""Tests for image-digest update detection."""
import pytest
import uuid

from app import db
from app.models import Application
from app.services.docker_service import DockerService
from app.services.image_update_service import ImageUpdateService


def _seed_app(image='nginx:latest'):
    from app.models import User
    uid = uuid.uuid4().hex[:8]
    user = User(email=f'{uid}@t.local', username=f'u{uid}',
                password_hash='x', role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.commit()
    row = Application(name='web', app_type='docker', source='manual',
                      docker_image=image, user_id=user.id)
    db.session.add(row)
    db.session.commit()
    return row


class TestImageUpdateService:
    def test_update_available_when_digests_differ(self, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(ImageUpdateService, '_local_digest', lambda ref: 'sha256:aaa')
        monkeypatch.setattr(ImageUpdateService, '_registry_digest', lambda ref: 'sha256:bbb')
        chk = ImageUpdateService.check_application(a.id)
        assert chk['status'] == 'completed'
        assert chk['update_available'] is True
        assert chk['current_digest'] == 'sha256:aaa'
        assert chk['latest_digest'] == 'sha256:bbb'

    def test_up_to_date_when_digests_match(self, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(ImageUpdateService, '_local_digest', lambda ref: 'sha256:same')
        monkeypatch.setattr(ImageUpdateService, '_registry_digest', lambda ref: 'sha256:same')
        chk = ImageUpdateService.check_application(a.id)
        assert chk['status'] == 'completed'
        assert chk['update_available'] is False

    def test_failed_when_local_digest_unknown(self, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(ImageUpdateService, '_local_digest', lambda ref: None)
        monkeypatch.setattr(ImageUpdateService, '_registry_digest', lambda ref: 'sha256:bbb')
        chk = ImageUpdateService.check_application(a.id)
        assert chk['status'] == 'failed'
        assert chk['update_available'] is False

    def test_no_image_raises_typed_error(self, app):
        from app.exceptions import ValidationError
        a = _seed_app(image=None)
        with pytest.raises(ValidationError):
            ImageUpdateService.check_application(a.id)

    def test_badge_present_in_application_to_dict(self, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(ImageUpdateService, '_local_digest', lambda ref: 'sha256:aaa')
        monkeypatch.setattr(ImageUpdateService, '_registry_digest', lambda ref: 'sha256:bbb')
        ImageUpdateService.check_application(a.id)
        badge = a.to_dict()['image_update']
        assert badge is not None
        assert badge['update_available'] is True
        assert badge['status'] == 'completed'


class TestImageUpdateApi:
    def test_check_endpoint_returns_result(self, client, auth_headers, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(ImageUpdateService, '_local_digest', lambda ref: 'sha256:aaa')
        monkeypatch.setattr(ImageUpdateService, '_registry_digest', lambda ref: 'sha256:bbb')
        resp = client.post(f'/api/v1/image-updates/applications/{a.id}/check', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['update_available'] is True

    def test_check_requires_auth(self, client, app):
        assert client.post('/api/v1/image-updates/applications/1/check').status_code == 401


class TestImageUpdateApply:
    def _compose_app(self):
        from app.models import User
        admin = User.query.filter_by(username='testadmin').first()
        row = Application(name='web', app_type='docker', source='manual',
                          root_path='/tmp/web', compose_file='docker-compose.yml',
                          docker_image='nginx:latest', user_id=admin.id)
        db.session.add(row)
        db.session.commit()
        return row

    def test_apply_pulls_and_recreates_compose_app(self, client, auth_headers, app, monkeypatch):
        row = self._compose_app()
        calls = []
        monkeypatch.setattr(DockerService, 'compose_pull',
                            lambda *a, **k: calls.append('pull') or {'success': True})
        monkeypatch.setattr(DockerService, 'compose_up',
                            lambda *a, **k: calls.append('up') or {'success': True})
        monkeypatch.setattr(ImageUpdateService, '_local_digest', lambda ref: 'sha256:x')
        monkeypatch.setattr(ImageUpdateService, '_registry_digest', lambda ref: 'sha256:x')

        resp = client.post(f'/api/v1/apps/{row.id}/image-update/apply', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['app']['status'] == 'running'
        assert calls == ['pull', 'up']   # pulled before recreating

    def test_apply_propagates_pull_failure(self, client, auth_headers, app, monkeypatch):
        row = self._compose_app()
        monkeypatch.setattr(DockerService, 'compose_pull',
                            lambda *a, **k: {'success': False, 'error': 'pull boom'})
        resp = client.post(f'/api/v1/apps/{row.id}/image-update/apply', headers=auth_headers)
        assert resp.status_code == 400
        assert 'pull boom' in resp.get_json()['error']

    def test_apply_guards_non_compose_app(self, client, auth_headers, app):
        from app.models import User
        admin = User.query.filter_by(username='testadmin').first()
        row = Application(name='static', app_type='static', source='manual', user_id=admin.id)
        db.session.add(row)
        db.session.commit()
        resp = client.post(f'/api/v1/apps/{row.id}/image-update/apply', headers=auth_headers)
        assert resp.status_code == 400

    def test_apply_requires_auth(self, client, app):
        assert client.post('/api/v1/apps/1/image-update/apply').status_code == 401
