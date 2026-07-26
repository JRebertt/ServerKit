"""Database engine catalog + install, prefix ``/api/v1/databases/engines``.

Deliberately thin. There is no engine model and no engine install mechanism
here: the catalog is composed from templates carrying an ``engine:`` block, and
an install delegates to the same deployment-job pipeline every other template
install uses -- so the UI can navigate straight to the deploy console.

Lifecycle (start / stop / uninstall) is app lifecycle. Use
``POST /api/v1/apps/<id>/start``, ``/stop`` and ``DELETE /api/v1/apps/<id>``
(which preserves an engine's data volumes unless ``?remove_data=true``).
"""
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.middleware.rbac import admin_required
from app.services import database_engine_service as engines
from app.services.deployment_job_service import DeploymentJobService

logger = logging.getLogger(__name__)

database_engines_bp = Blueprint('database_engines', __name__)


@database_engines_bp.route('', methods=['GET'])
@jwt_required()
def list_database_engines():
    """The installable engine catalog plus every engine already installed.

    ``catalog`` is every available template declaring an ``engine:`` block --
    bundled, operator-authored, or pulled in by a synced template repository.
    Nothing here is hardcoded: dropping a new engine YAML into the templates
    directory is enough to make it appear.
    """
    live = request.args.get('live', 'true').lower() != 'false'
    catalog = engines.engine_catalog()
    return jsonify({
        'catalog': catalog,
        'installed': engines.installed_engines(live_status=live),
        # Derived from the catalog so the UI never carries its own family list.
        'families': engines.catalog_families(catalog),
    }), 200


@database_engines_bp.route('', methods=['POST'])
@jwt_required()
@admin_required
def install_database_engine():
    """Install an engine by installing its template.

    Answers with whatever the template pipeline returns (``job_id`` + the job),
    so the caller navigates to the deploy console exactly as it would for any
    other template install.
    """
    data = request.get_json(silent=True) or {}

    plan = engines.plan_install(
        template_id=data.get('template_id'),
        version=data.get('version'),
        instance_name=data.get('instance_name'),
        port=data.get('port'),
        expose_public=bool(data.get('expose_public', False)),
        initial_database=data.get('initial_database'),
        variables=data.get('variables') or {},
    )
    if 'error' in plan:
        status = plan.pop('status_code', 400)
        return jsonify(plan), status

    result = DeploymentJobService.install_template(
        template_id=data.get('template_id'),
        app_name=plan['app_name'],
        user_variables=plan['variables'],
        user_id=get_jwt_identity(),
        server_id=data.get('server_id') or data.get('target_server_id'),
        wait=bool(data.get('wait', False)),
    )
    if not result.get('success'):
        return jsonify(result), 400

    result['engine'] = plan['engine']
    result['app_name'] = plan['app_name']
    if plan.get('warning'):
        result['warning'] = plan['warning']

    status = (result.get('job') or {}).get('status')
    return jsonify(result), 201 if status == 'succeeded' else 202
