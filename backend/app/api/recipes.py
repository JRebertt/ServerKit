"""Recipe run API (plan 68 Phase 0).

Registry browsing and bundled recipe content land in later phases. This first
surface accepts a reviewed inline/stored v1 manifest, creates a normal
DeploymentJob, and resumes encrypted human handoffs on that same run.
"""

from flask import Blueprint, jsonify, request

from app import db
from app.middleware.rbac import admin_required, get_current_user
from app.models.application_manifest import STATUS_ERROR, STATUS_PENDING
from app.models.deployment_job import DeploymentJob
from app.models.project import Project
from app.services.manifest_persistence_service import ManifestPersistenceService
from app.services.manifest_spec_service import ManifestError, ManifestSpecService
from app.services.recipe_execution_service import (
    RECIPE_JOB_KIND,
    RecipeExecutionService,
)


recipes_bp = Blueprint('recipes', __name__)


def _normalized_recipe(data, project_id):
    if 'content' in data:
        return ManifestSpecService.normalize_text(data['content']), data['content']
    if 'manifest' in data:
        return ManifestSpecService.normalize(data['manifest']), None
    from app.models.application_manifest import ApplicationManifest
    row = ApplicationManifest.query.filter_by(project_id=project_id).first()
    if row and row.get_normalized():
        return row.get_normalized(), row.raw_text
    raise ManifestError(['Provide `content`/`manifest`, or store one first'])


@recipes_bp.route('/runs', methods=['POST'])
@admin_required
def start_recipe_run():
    data = request.get_json(silent=True) or {}
    project = Project.query.get(data.get('project_id')) if data.get('project_id') else None
    if not project:
        return jsonify({'error': 'A valid project_id is required'}), 400
    try:
        normalized, raw = _normalized_recipe(data, project.id)
    except ManifestError as exc:
        return jsonify({'error': 'Invalid Recipe manifest', 'errors': exc.errors}), 400

    unsupported = RecipeExecutionService.unsupported_capabilities(normalized)
    if unsupported:
        return jsonify({
            'success': False,
            'error': 'This panel does not support every Recipe capability',
            'unsupported_capabilities': unsupported,
        }), 400

    row = ManifestPersistenceService.store_manifest(
        project_id=project.id, normalized=normalized, raw_text=raw,
        status=STATUS_PENDING)
    db.session.commit()

    user = get_current_user()
    wait = request.args.get('wait', 'false').lower() == 'true'
    result = RecipeExecutionService.start(
        project, normalized, user_id=user.id,
        slug=data.get('slug'), title=data.get('title'),
        manifest_row=row, wait=wait)
    if not result.get('success'):
        row.status = STATUS_ERROR
        row.last_error = result.get('error')
        db.session.commit()
        return jsonify(result), 400

    _audit('recipe.start', user.id, result.get('job_id'), {
        'project_id': project.id, 'slug': data.get('slug'),
    })
    return jsonify(result), 200 if wait else 202


@recipes_bp.route('/runs/<job_id>', methods=['GET'])
@admin_required
def get_recipe_run(job_id):
    job = DeploymentJob.query.get(job_id)
    if not job or job.kind != RECIPE_JOB_KIND:
        return jsonify({'error': 'Recipe run not found'}), 404
    return jsonify({'job': job.to_dict(include_plan=True, include_logs=True)}), 200


@recipes_bp.route('/runs/<job_id>/handoffs/<step_id>', methods=['POST'])
@admin_required
def submit_recipe_handoff(job_id, step_id):
    job = DeploymentJob.query.get(job_id)
    if not job or job.kind != RECIPE_JOB_KIND:
        return jsonify({'error': 'Recipe run not found'}), 404
    data = request.get_json(silent=True) or {}
    user = get_current_user()
    wait = request.args.get('wait', 'false').lower() == 'true'
    result = RecipeExecutionService.submit_handoff(
        job, step_id=step_id, value=data.get('value'), user_id=user.id, wait=wait)
    if not result.get('success'):
        return jsonify(result), 400
    _audit('recipe.handoff.submit', user.id, job.id, {'step_id': step_id})
    return jsonify(result), 200 if wait else 202


def _audit(action, user_id, job_id, details):
    try:
        from app.services.audit_service import AuditService
        AuditService.log(
            action, user_id=user_id, target_type='deployment_job',
            target_id=job_id, details=details)
    except Exception:
        pass
