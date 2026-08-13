"""Push-to-reconfigure — re-read serverkit.yaml on every deploy (plan 17, Phase 4).

Both webhook receivers call ``resync_for_app`` after a deploy. If the manifest
hash is unchanged it is a no-op (today's behavior). If it changed, services with
``autoDeploy: true`` auto-apply (logged + snapshotted); anything else flips the
project's manifest to ``pending`` with a notification so push-to-deploy and
push-to-reconfigure become the same motion.

Fully guarded — a manifest problem must never break a deploy.
"""

import logging
from typing import Any, Dict, Optional

from app import db
from app.models.application import Application
from app.models.application_manifest import (
    ApplicationManifest, STATUS_PENDING, STATUS_APPLIED,
)
from app.models.project import Project
from app.services.manifest_persistence_service import ManifestPersistenceService

logger = logging.getLogger(__name__)


class ManifestSyncService:

    @classmethod
    def resync_for_app(cls, app_id: int, commit: Optional[str] = None,
                       trigger: str = 'webhook') -> Dict[str, Any]:
        """Re-read the repo manifest for an app's project and reconcile."""
        try:
            return cls._resync(app_id, commit, trigger)
        except Exception as exc:  # never break a deploy
            logger.warning('Manifest resync failed for app %s: %s', app_id, exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            return {'synced': False, 'error': str(exc)}

    @classmethod
    def _resync(cls, app_id: int, commit: Optional[str], trigger: str) -> Dict[str, Any]:
        from app.services.repository_manifest_service import RepositoryManifestService

        app = Application.query_active().filter_by(id=app_id).first()
        if not app or not app.project_id or not app.root_path:
            return {'synced': False, 'reason': 'no project/root'}

        analysis = RepositoryManifestService.analyze_path(app.root_path)
        normalized = analysis.get('manifest_v1_normalized')
        if not normalized:
            return {'synced': False, 'reason': 'no v1 manifest'}

        new_hash = ManifestPersistenceService.hash_normalized(normalized)
        row = ApplicationManifest.query.filter_by(project_id=app.project_id).first()
        if row and row.manifest_hash == new_hash and row.status == STATUS_APPLIED:
            return {'synced': False, 'reason': 'unchanged'}

        project = Project.query.get(app.project_id)
        row = ManifestPersistenceService.store_manifest(
            project_id=project.id, normalized=normalized,
            raw_text=analysis.get('manifest_v1_raw'),
            source_commit=commit,
            source_path=analysis.get('manifest_v1_file') or 'serverkit.yaml',
            status=STATUS_PENDING)
        db.session.commit()

        services = normalized.get('services', [])
        auto = [s for s in services if s.get('auto_deploy')]
        has_manual = len(auto) < len(services)

        if not auto:
            # nothing opts into auto-apply — a plan is waiting
            cls._emit('manifest.pending', project, {
                'reason': 'manifest changed; no autoDeploy services',
                'commit': commit})
            return {'synced': True, 'action': 'pending', 'auto_applied': 0}

        from app.services.manifest_apply_service import ManifestApplyService
        auto_names = {s['name'] for s in auto}
        filtered = dict(normalized)
        filtered['services'] = auto
        filtered['domains'] = [d for d in normalized.get('domains', [])
                               if not d.get('service') or d['service'] in auto_names]

        result = ManifestApplyService.apply(project, filtered, user_id=None,
                                            manifest_row=row)

        # if manual services still await, the manifest stays pending overall
        if has_manual and result.get('success'):
            row.status = STATUS_PENDING
            db.session.commit()
            cls._emit('manifest.pending', project, {
                'reason': 'autoDeploy services applied; others await review',
                'auto_applied': result.get('applied'), 'commit': commit})
        elif result.get('success'):
            cls._emit('manifest.applied', project, {
                'applied': result.get('applied'), 'commit': commit,
                'trigger': trigger})
        else:
            cls._emit('manifest.error', project, {
                'commit': commit,
                'error': next((r.get('error') for r in result.get('results', [])
                               if r.get('status') == 'error'), None)})

        return {'synced': True, 'action': 'auto_apply',
                'auto_applied': result.get('applied'), 'job_id': result.get('job_id'),
                'success': result.get('success')}

    @staticmethod
    def _emit(event: str, project, data: Dict[str, Any]):
        """Best-effort admin notification (#19)."""
        try:
            from app.plugins_sdk import notify
            payload = {'project': project.name, 'project_id': project.id, **data}
            messages = {
                'manifest.applied': f"Manifest for project “{project.name}” was applied "
                                    f"from a push ({data.get('applied', 0)} change(s)).",
                'manifest.pending': f"Manifest for project “{project.name}” changed on a push "
                                    f"and is waiting for you to review and apply it.",
                'manifest.drifted': f"Live state for project “{project.name}” no longer matches "
                                    f"its manifest.",
                'manifest.error': f"Applying the manifest for project “{project.name}” failed.",
            }
            payload['message'] = messages.get(event, event)
            notify.send(event, to='admins', data=payload, category='deployments')
        except Exception as exc:  # never break the flow
            logger.debug('manifest event %s not sent: %s', event, exc)
