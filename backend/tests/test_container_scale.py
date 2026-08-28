"""Tests for container horizontal auto-scaling (decision logic and API flow)."""
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

    def test_rejects_an_enabled_policy_without_a_service(self, app):
        a = _seed_app()
        try:
            ContainerScaleService.set_policy(a.id, enabled=True)
        except ValueError as exc:
            assert str(exc) == 'service_name is required when auto-scale is enabled'
        else:
            raise AssertionError('enabled policy without a service was accepted')

    def test_rejects_overlapping_cpu_thresholds(self, app):
        a = _seed_app()
        try:
            ContainerScaleService.set_policy(
                a.id, service_name='web', cpu_low_percent=80,
                cpu_high_percent=70)
        except ValueError as exc:
            assert str(exc) == 'cpu_low_percent must be less than cpu_high_percent'
        else:
            raise AssertionError('overlapping CPU thresholds were accepted')


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

    def test_enforces_a_raised_minimum_without_waiting_for_high_cpu(self, app, monkeypatch):
        a = _seed_app()
        ContainerScaleService.set_policy(
            a.id, enabled=True, service_name='web', min_replicas=2,
            max_replicas=3, cooldown_seconds=0)
        applied = []
        monkeypatch.setattr(
            ContainerScaleService, '_service_cpu',
            lambda app_, policy: (_ for _ in ()).throw(
                AssertionError('CPU should not gate the replica floor')))
        monkeypatch.setattr(
            ContainerScaleService, '_apply_scale',
            lambda app_, policy, n: applied.append(n) or {'success': True})

        result = ContainerScaleService.evaluate(a.id)

        assert result['action'] == 'scaled_up'
        assert result['replicas'] == 2
        assert applied == [2]


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

    def test_rejects_non_numeric_manual_replica_count(self, client, auth_headers, app):
        from app.models import User
        admin = User.query.filter_by(username='testadmin').first()
        a = _seed_app(user_id=admin.id)
        ContainerScaleService.set_policy(a.id, service_name='web')

        response = client.post(
            f'/api/v1/apps/{a.id}/scale', json={'replicas': 'many'},
            headers=auth_headers)

        assert response.status_code == 400
        assert response.get_json() == {'error': 'replicas must be an integer'}

    def test_rejects_invalid_policy_without_persisting_it(
            self, client, auth_headers, app):
        from app.models import User
        admin = User.query.filter_by(username='testadmin').first()
        a = _seed_app(user_id=admin.id)

        response = client.put(
            f'/api/v1/apps/{a.id}/scale-policy',
            json={'enabled': True, 'service_name': ''},
            headers=auth_headers)

        assert response.status_code == 400
        assert response.get_json() == {
            'error': 'service_name is required when auto-scale is enabled'}
        persisted = client.get(
            f'/api/v1/apps/{a.id}/scale-policy', headers=auth_headers)
        assert persisted.get_json()['enabled'] is False

    def test_policy_to_evaluation_to_manual_scale_workflow(
            self, client, auth_headers, app, monkeypatch):
        from app.models import User
        admin = User.query.filter_by(username='testadmin').first()
        a = _seed_app(user_id=admin.id)
        applied = []
        monkeypatch.setattr(ContainerScaleService, '_service_cpu', lambda app_, policy: 92.0)
        monkeypatch.setattr(
            ContainerScaleService, '_apply_scale',
            lambda app_, policy, n: applied.append(n) or {'success': True})

        initial = client.get(
            f'/api/v1/apps/{a.id}/scale-policy', headers=auth_headers)
        assert initial.status_code == 200
        assert initial.get_json()['current_replicas'] == 1

        configured = client.put(
            f'/api/v1/apps/{a.id}/scale-policy',
            json={
                'enabled': True,
                'service_name': 'web',
                'min_replicas': 1,
                'max_replicas': 4,
                'cpu_low_percent': 20,
                'cpu_high_percent': 75,
                'cooldown_seconds': 0,
            },
            headers=auth_headers)
        assert configured.status_code == 200
        assert configured.get_json()['enabled'] is True

        evaluated = client.post(
            f'/api/v1/apps/{a.id}/scale/evaluate', headers=auth_headers)
        assert evaluated.status_code == 200
        assert evaluated.get_json()['action'] == 'scaled_up'
        assert evaluated.get_json()['replicas'] == 2

        manual = client.post(
            f'/api/v1/apps/{a.id}/scale', json={'replicas': 3},
            headers=auth_headers)
        assert manual.status_code == 200
        assert manual.get_json()['replicas'] == 3

        persisted = client.get(
            f'/api/v1/apps/{a.id}/scale-policy', headers=auth_headers)
        assert persisted.get_json()['current_replicas'] == 3
        assert applied == [2, 3]
