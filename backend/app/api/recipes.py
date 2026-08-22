"""Recipe run API (plan 68).

Starts runs from three manifest sources — a registry slug (the curated
``serverkit-recipes`` catalog), reviewed inline YAML/JSON, or a manifest
already stored on the project — creates a normal DeploymentJob, and resumes
encrypted human handoffs on that same run. Runs target either an explicit
``project_id`` or a ``server_id``, for which a per-workspace Recipes project
is found or created so a catalog install is one call.
"""

from flask import Blueprint, jsonify, request

from app import db
from app.exceptions import NotFoundError, ValidationError
from app.middleware.rbac import admin_required, auth_required, get_current_user
from app.models.application_manifest import STATUS_ERROR, STATUS_PENDING
from app.models.deployment_job import DeploymentJob
from app.models.project import Project
from app.services import recipe_registry_service
from app.services.manifest_persistence_service import ManifestPersistenceService
from app.services.manifest_spec_service import ManifestError, ManifestSpecService
from app.services.recipe_execution_service import (
    RECIPE_JOB_KIND,
    RecipeExecutionService,
)


recipes_bp = Blueprint('recipes', __name__)

def _normalized_recipe(data, project_id):
    """Resolve the manifest source: registry slug > inline content > stored."""
    if data.get('registry_slug'):
        text = recipe_registry_service.get_manifest_text(data['registry_slug'])
        return ManifestSpecService.normalize_text(text), text
    if 'content' in data:
        return ManifestSpecService.normalize_text(data['content']), data['content']
    if 'manifest' in data:
        return ManifestSpecService.normalize(data['manifest']), None
    from app.models.application_manifest import ApplicationManifest
    row = ApplicationManifest.query.filter_by(project_id=project_id).first()
    if row and row.get_normalized():
        return row.get_normalized(), row.raw_text
    raise ManifestError(['Provide `registry_slug`, `content`, `manifest`, or store one first'])


def _validated_params(normalized, raw_params):
    """Check up-front params against the manifest's declared inputs. Only
    non-secret inputs may be preset; secrets must use the mid-run handoff."""
    if raw_params in (None, {}):
        return {}
    if not isinstance(raw_params, dict):
        raise ValueError('params must be an object of input keys')
    inputs = {
        (step.get('input') or {}).get('key'): (step.get('input') or {})
        for step in (normalized.get('configure') or [])
        if step.get('input')
    }
    unknown = [k for k in raw_params if k not in inputs]
    if unknown:
        raise ValueError(f"Unknown recipe input(s): {', '.join(sorted(unknown))}")
    secrets = [k for k, v in raw_params.items() if v is not None and inputs[k].get('secret')]
    if secrets:
        raise ValueError(
            f"{', '.join(sorted(secrets))} is collected securely during the run "
            "and cannot be preset")
    return {k: str(v) for k, v in raw_params.items() if v is not None}


@recipes_bp.route('/registry', methods=['GET'])
@auth_required()
def list_recipe_registry():
    return jsonify({
        'recipes': recipe_registry_service.list_catalog(),
        'source': recipe_registry_service.registry_source_label(),
    }), 200


@recipes_bp.route('/registry/<slug>', methods=['GET'])
@auth_required()
def get_recipe_registry_entry(slug):
    entry = recipe_registry_service.get_entry(slug)
    if entry is None:
        raise NotFoundError('Recipe not found in the registry')
    manifest_text = recipe_registry_service.get_manifest_text(slug)
    public = {k: v for k, v in entry.items() if k != '_manifest_url'}
    return jsonify({'recipe': public, 'manifest': manifest_text}), 200


@recipes_bp.route('/runs', methods=['POST'])
@admin_required
def start_recipe_run():
    data = request.get_json(silent=True) or {}

    project = None
    server = None
    if data.get('server_id'):
        server = RecipeExecutionService.get_server(data.get('server_id'))
    if data.get('project_id'):
        project = Project.query.get(data.get('project_id'))
        if not project:
            return jsonify({'error': 'A valid project_id is required'}), 400
    if project is None and server is None:
        raise ValidationError('Provide server_id or project_id')

    try:
        normalized, raw = _normalized_recipe(data, project.id if project else None)
        params = _validated_params(normalized, data.get('params'))
    except ManifestError as exc:
        return jsonify({'error': 'Invalid Recipe manifest', 'errors': exc.errors}), 400
    except (ValueError, NotFoundError) as exc:
        raise ValidationError(str(exc)) from exc

    # A server-targeted catalog run pins the manifest's default server ref.
    if server is not None:
        normalized['server'] = server.name
        if project is None:
            project = RecipeExecutionService.get_or_create_project(server)

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
        slug=data.get('slug') or data.get('registry_slug'),
        title=data.get('title'),
        manifest_row=row, params=params, wait=wait)
    if not result.get('success'):
        row.status = STATUS_ERROR
        row.last_error = result.get('error')
        db.session.commit()
        return jsonify(result), 400

    _audit('recipe.start', user.id, result.get('job_id'), {
        'project_id': project.id, 'slug': data.get('slug') or data.get('registry_slug'),
        'server_id': server.id if server else None,
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
