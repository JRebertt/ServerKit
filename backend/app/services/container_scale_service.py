"""Horizontal auto-scaling: adjust a compose service's replica count based on
average CPU, within min/max bounds and a cooldown. Local apps only for now;
the service must be scale-capable (no fixed host port or container_name)."""
import logging
import os
import subprocess
from datetime import datetime, timedelta

from app import db
from app.utils.system import run_checked
from app.models import Application
from app.models.container_scale_policy import ContainerScalePolicy

logger = logging.getLogger(__name__)


def _compose_path(app):
    return os.path.join(app.root_path, app.compose_file or 'docker-compose.yml')


class ContainerScaleService:

    @staticmethod
    def get_or_create_policy(application_id):
        policy = ContainerScalePolicy.query.filter_by(application_id=application_id).first()
        if not policy:
            policy = ContainerScalePolicy(application_id=application_id)
            db.session.add(policy)
            db.session.commit()
        return policy

    @classmethod
    def set_policy(cls, application_id, **fields):
        policy = cls.get_or_create_policy(application_id)
        if fields.get('enabled') is not None:
            policy.enabled = bool(fields['enabled'])
        if fields.get('service_name') is not None:
            policy.service_name = (fields['service_name'] or '').strip() or None
        for key in ('min_replicas', 'max_replicas', 'cpu_high_percent',
                    'cpu_low_percent', 'cooldown_seconds'):
            if fields.get(key) is not None:
                setattr(policy, key, max(0, int(fields[key])))
        policy.min_replicas = max(1, policy.min_replicas)
        policy.max_replicas = max(policy.min_replicas, policy.max_replicas)
        db.session.commit()
        return policy

    @classmethod
    def _service_cpu(cls, app, policy):
        """Average CPU% across the service's running containers, or None."""
        try:
            ps_cmd = ['docker', 'compose', '-f', _compose_path(app), 'ps', '-q']
            if policy.service_name:
                ps_cmd.append(policy.service_name)
            ps = run_checked(ps_cmd, cwd=app.root_path, timeout=15)
            ids = [line.strip() for line in ps['output'].splitlines() if line.strip()]
            if not ids:
                return None
            stats = run_checked(
                ['docker', 'stats', '--no-stream', '--format', '{{.CPUPerc}}'] + ids,
                timeout=15)
            values = []
            for line in stats['output'].splitlines():
                try:
                    values.append(float(line.strip().rstrip('%')))
                except ValueError:
                    pass
            return round(sum(values) / len(values), 1) if values else None
        except Exception:
            return None

    @classmethod
    def _apply_scale(cls, app, policy, replicas):
        if app.server_id:
            return {'success': False, 'error': 'Scaling is not yet supported for apps on remote servers'}
        if not (app.app_type == 'docker' and app.root_path and policy.service_name):
            return {'success': False, 'error': 'Scaling requires a docker-compose app with a service_name set'}
        try:
            result = run_checked(
                ['docker', 'compose', '-f', _compose_path(app), 'up', '-d', '--no-recreate',
                 '--scale', f'{policy.service_name}={replicas}'],
                cwd=app.root_path, timeout=120)
            if not result['success']:
                return {'success': False, 'error': result['error'][:300]}
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def scale_to(cls, application_id, replicas):
        # query_active: this runs `docker compose up --scale` — never on a tombstone.
        app = Application.query_active().filter_by(id=application_id).first()
        if not app:
            return {'success': False, 'error': 'Application not found'}
        policy = cls.get_or_create_policy(application_id)
        replicas = max(1, int(replicas))
        result = cls._apply_scale(app, policy, replicas)
        if not result.get('success'):
            return result
        policy.current_replicas = replicas
        policy.last_scaled_at = datetime.utcnow()
        db.session.commit()
        return {'success': True, 'replicas': replicas, 'policy': policy.to_dict()}

    @classmethod
    def evaluate(cls, application_id):
        app = Application.query_active().filter_by(id=application_id).first()
        if not app:
            return {'success': False, 'error': 'Application not found'}
        policy = cls.get_or_create_policy(application_id)
        if not policy.enabled:
            return {'success': True, 'action': 'disabled', 'replicas': policy.current_replicas}

        now = datetime.utcnow()
        if policy.last_scaled_at and (now - policy.last_scaled_at) < timedelta(seconds=policy.cooldown_seconds):
            return {'success': True, 'action': 'cooldown', 'replicas': policy.current_replicas}

        cpu = cls._service_cpu(app, policy)
        if cpu is None:
            return {'success': True, 'action': 'unknown', 'replicas': policy.current_replicas}

        current = policy.current_replicas
        target = current
        if cpu > policy.cpu_high_percent and current < policy.max_replicas:
            target = current + 1
        elif cpu < policy.cpu_low_percent and current > policy.min_replicas:
            target = current - 1

        if target == current:
            return {'success': True, 'action': 'hold', 'replicas': current, 'cpu': cpu}

        result = cls._apply_scale(app, policy, target)
        if not result.get('success'):
            return {'success': False, 'error': result['error'], 'replicas': current}
        policy.current_replicas = target
        policy.last_scaled_at = now
        db.session.commit()
        action = 'scaled_up' if target > current else 'scaled_down'
        logger.info('Auto-scale %s: %s -> %s replicas (cpu=%.1f)', app.name, current, target, cpu)
        return {'success': True, 'action': action, 'replicas': target, 'cpu': cpu}

    @classmethod
    def sweep(cls):
        """Evaluate every enabled policy. Meant to run periodically."""
        scaled = []
        # Scale policies outlive a soft-deleted app; skip them rather than
        # spawning docker/compose probes for an app that no longer exists.
        dead = Application.deleted_ids()
        for policy in ContainerScalePolicy.query.filter_by(enabled=True).all():
            if policy.application_id in dead:
                continue
            result = cls.evaluate(policy.application_id)
            if result.get('action') in ('scaled_up', 'scaled_down'):
                scaled.append({'application_id': policy.application_id,
                               'action': result['action'], 'replicas': result['replicas']})
        return {'success': True, 'scaled': scaled}
