"""Tests for container horizontal auto-scaling (decision logic)."""
import uuid
from datetime import datetime

from app import db
from app.models import Application
from factories import make_application
from app.models.container_scale_policy import ContainerScalePolicy
from app.services.container_scale_service import ContainerScaleService


def _seed_app(**kw):
    return make_application(db, **kw)


def _set_current(app_id, n):
    p = ContainerScalePolicy.query.filter_by(application_id=app_id).first()
    p.current_replicas = n
    db.session.commit()
    return p


class TestScalePolicy:
    def test_set_policy_clamps_bounds(self, app):
        a = _seed_app()
        p = ContainerScaleService.set_policy(a.id, enabled=True, service_name='web',
                                             min_replicas=0, max_replicas=2)
        assert p.enabled and p.service_name == 'web'
        assert p.min_replicas == 1 and p.max_replicas == 2

    def test_max_never_below_min(self, app):
        a = _seed_app()
        p = ContainerScaleService.set_policy(a.id, min_replicas=5, max_replicas=2)
        assert p.max_replicas == 5


class TestEvaluate:
    def test_scales_up_on_high_cpu(self, app, monkeypatch):
        a = _seed_app()
        ContainerScaleService.set_policy(a.id, enabled=True, service_name='web',
                                         min_replicas=1, max_replicas=3, cpu_high_percent=75, cooldown_seconds=0)
        monkeypatch.setattr(ContainerScaleService, '_service_cpu', lambda app_, policy: 90.0)
        monkeypatch.setattr(ContainerScaleService, '_apply_scale', lambda app_, policy, n: {'success': True})
        r = ContainerScaleService.evaluate(a.id)
        assert r['action'] == 'scaled_up' and r['replicas'] == 2

    def test_scales_down_on_low_cpu(self, app, monkeypatch):
        a = _seed_app()
        ContainerScaleService.set_policy(a.id, enabled=True, service_name='web',
                                         min_replicas=1, max_replicas=3, cpu_low_percent=25, cooldown_seconds=0)
        _set_current(a.id, 2)
        monkeypatch.setattr(ContainerScaleService, '_service_cpu', lambda app_, policy: 5.0)
        monkeypatch.setattr(ContainerScaleService, '_apply_scale', lambda app_, policy, n: {'success': True})
        r = ContainerScaleService.evaluate(a.id)
        assert r['action'] == 'scaled_down' and r['replicas'] == 1

    def test_holds_at_max(self, app, monkeypatch):
        a = _seed_app()
        ContainerScaleService.set_policy(a.id, enabled=True, service_name='web',
                                         max_replicas=2, cpu_high_percent=75, cooldown_seconds=0)
        _set_current(a.id, 2)
        monkeypatch.setattr(ContainerScaleService, '_service_cpu', lambda app_, policy: 99.0)
        r = ContainerScaleService.evaluate(a.id)
        assert r['action'] == 'hold' and r['replicas'] == 2

    def test_cooldown_blocks_action(self, app, monkeypatch):
        a = _seed_app()
        ContainerScaleService.set_policy(a.id, enabled=True, service_name='web', cooldown_seconds=300)
        p = ContainerScalePolicy.query.filter_by(application_id=a.id).first()
        p.last_scaled_at = datetime.utcnow()
        db.session.commit()
        monkeypatch.setattr(ContainerScaleService, '_service_cpu', lambda app_, policy: 99.0)
        assert ContainerScaleService.evaluate(a.id)['action'] == 'cooldown'

    def test_disabled_policy_is_noop(self, app):
        a = _seed_app()
        ContainerScaleService.set_policy(a.id, enabled=False)
        assert ContainerScaleService.evaluate(a.id)['action'] == 'disabled'

    def test_unknown_cpu_holds(self, app, monkeypatch):
        a = _seed_app()
        ContainerScaleService.set_policy(a.id, enabled=True, service_name='web', cooldown_seconds=0)
        monkeypatch.setattr(ContainerScaleService, '_service_cpu', lambda app_, policy: None)
        assert ContainerScaleService.evaluate(a.id)['action'] == 'unknown'


class TestScaleApi:
    def test_manual_scale_endpoint(self, client, auth_headers, app, monkeypatch):
        from app.models import User
        admin = User.query.filter_by(username='testadmin').first()
        a = _seed_app(user_id=admin.id)
        ContainerScaleService.set_policy(a.id, service_name='web')
        monkeypatch.setattr(ContainerScaleService, '_apply_scale', lambda app_, policy, n: {'success': True})
        resp = client.post(f'/api/v1/apps/{a.id}/scale', json={'replicas': 3}, headers=auth_headers)
        assert resp.status_code == 200 and resp.get_json()['replicas'] == 3

    def test_scale_sweep_requires_admin(self, client, app):
        assert client.post('/api/v1/apps/scale-sweep').status_code == 401
