"""Tests for container auto-sleep (policy, manual sleep/wake, idle sweep)."""
import uuid
from datetime import datetime, timedelta

from app import db
from app.models import Application
from factories import make_application
from app.models.container_sleep_policy import ContainerSleepPolicy
from app.services.docker_service import DockerService
from app.services.container_sleep_service import ContainerSleepService


def _seed_app(**kw):
    return make_application(db, **kw)


def _mock_docker(monkeypatch, ok=True):
    monkeypatch.setattr(DockerService, 'compose_down', lambda *a, **k: {'success': ok})
    monkeypatch.setattr(DockerService, 'compose_up', lambda *a, **k: {'success': ok})


class TestSleepPolicy:
    def test_set_and_get_policy(self, app):
        a = _seed_app()
        p = ContainerSleepService.set_policy(a.id, enabled=True, idle_timeout_minutes=15)
        assert p.enabled is True and p.idle_timeout_minutes == 15
        assert ContainerSleepService.get_or_create_policy(a.id).enabled is True

    def test_timeout_has_a_floor_of_one(self, app):
        a = _seed_app()
        p = ContainerSleepService.set_policy(a.id, idle_timeout_minutes=0)
        assert p.idle_timeout_minutes == 1


class TestSleepWake:
    def test_sleep_then_wake(self, app, monkeypatch):
        _mock_docker(monkeypatch)
        a = _seed_app()
        r = ContainerSleepService.sleep_app(a.id)
        assert r['success'] and r['policy']['asleep'] is True
        assert Application.query.get(a.id).status == 'stopped'
        r2 = ContainerSleepService.wake_app(a.id)
        assert r2['success'] and r2['policy']['asleep'] is False
        assert Application.query.get(a.id).status == 'running'

    def test_sleep_propagates_docker_failure(self, app, monkeypatch):
        _mock_docker(monkeypatch, ok=False)
        a = _seed_app()
        assert ContainerSleepService.sleep_app(a.id)['success'] is False

    def test_remote_app_is_guarded(self, app):
        a = _seed_app(server_id='srv-1')
        r = ContainerSleepService.sleep_app(a.id)
        assert r['success'] is False and 'remote' in r['error'].lower()


class TestSweep:
    def test_sweeps_only_idle_enabled_awake(self, app, monkeypatch):
        _mock_docker(monkeypatch)
        idle, active, disabled = _seed_app(), _seed_app(), _seed_app()

        ContainerSleepService.set_policy(idle.id, enabled=True, idle_timeout_minutes=30)
        ContainerSleepPolicy.query.filter_by(application_id=idle.id).first().last_activity_at = \
            datetime.utcnow() - timedelta(minutes=60)
        ContainerSleepService.set_policy(active.id, enabled=True, idle_timeout_minutes=30)  # activity just now
        ContainerSleepService.set_policy(disabled.id, enabled=False, idle_timeout_minutes=1)
        ContainerSleepPolicy.query.filter_by(application_id=disabled.id).first().last_activity_at = \
            datetime.utcnow() - timedelta(minutes=60)
        db.session.commit()

        slept = ContainerSleepService.sweep_idle()['slept']
        assert idle.id in slept
        assert active.id not in slept
        assert disabled.id not in slept

    def test_sweep_skips_without_activity_baseline(self, app, monkeypatch):
        _mock_docker(monkeypatch)
        a = _seed_app()
        p = ContainerSleepService.set_policy(a.id, enabled=True, idle_timeout_minutes=30)
        p.last_activity_at = None
        db.session.commit()
        assert a.id not in ContainerSleepService.sweep_idle()['slept']


class TestSleepApi:
    def test_sleep_and_wake_endpoints(self, client, auth_headers, app, monkeypatch):
        _mock_docker(monkeypatch)
        from app.models import User
        admin = User.query.filter_by(username='testadmin').first()
        a = _seed_app(user_id=admin.id)
        assert client.post(f'/api/v1/apps/{a.id}/sleep', headers=auth_headers).status_code == 200
        assert client.post(f'/api/v1/apps/{a.id}/wake', headers=auth_headers).status_code == 200

    def test_sweep_requires_admin_auth(self, client, app):
        assert client.post('/api/v1/apps/sweep-idle').status_code == 401
