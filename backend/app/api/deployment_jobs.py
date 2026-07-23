"""Deployment job API endpoints."""

from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required

from app.models.deployment_job import DeploymentJob, DeploymentJobLog
from app.services.deployment_job_service import DeploymentJobService

deployment_jobs_bp = Blueprint('deployment_jobs', __name__)


@deployment_jobs_bp.route('/simulate', methods=['GET'])
@jwt_required()
def get_simulate_info():
    """Simulated-deploy availability + scenario catalog (plan 51.5 dev tool).

    404 when the DEMO_DEPLOYS_ENABLED gate is off (production default), so the
    surface simply doesn't exist outside dev.
    """
    if not current_app.config.get('DEMO_DEPLOYS_ENABLED'):
        return jsonify({'error': 'Not found'}), 404
    from app.services.demo_deploy_service import DemoDeployService
    return jsonify({'enabled': True,
                    'scenarios': DemoDeployService.list_scenarios()}), 200


@deployment_jobs_bp.route('/simulate', methods=['POST'])
@jwt_required()
def simulate_deployment():
    """Create a simulated deployment job that streams scripted output through
    the real console pipeline. Body: {scenario, speed?}; ?wait=true runs it
    synchronously (tests)."""
    if not current_app.config.get('DEMO_DEPLOYS_ENABLED'):
        return jsonify({'error': 'Not found'}), 404
    from flask_jwt_extended import get_jwt_identity
    from app.services.demo_deploy_service import DemoDeployService

    data = request.get_json(silent=True) or {}
    wait = request.args.get('wait', 'false').lower() == 'true'
    result = DemoDeployService.create(
        scenario=data.get('scenario') or '',
        speed=data.get('speed') or 'fast',
        user_id=get_jwt_identity(),
        wait=wait,
    )
    if not result.get('success'):
        return jsonify({'error': result.get('error')}), 400
    return jsonify(result), 202


@deployment_jobs_bp.route('', methods=['GET'])
@jwt_required()
def list_deployment_jobs():
    status = request.args.get('status')
    target_server_id = request.args.get('server_id')
    app_id = request.args.get('app_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    jobs = DeploymentJobService.list_jobs(
        status=status,
        target_server_id=target_server_id,
        app_id=app_id,
        limit=min(limit, 200),
    )
    return jsonify({'jobs': jobs}), 200


@deployment_jobs_bp.route('/<job_id>', methods=['GET'])
@jwt_required()
def get_deployment_job(job_id):
    include_logs = request.args.get('logs', 'true').lower() == 'true'
    include_plan = request.args.get('plan', 'false').lower() == 'true'
    job = DeploymentJobService.get_job(
        job_id, include_logs=include_logs, include_plan=include_plan
    )
    if not job:
        return jsonify({'error': 'Deployment job not found'}), 404
    return jsonify({'job': job}), 200


@deployment_jobs_bp.route('/<job_id>/retry', methods=['POST'])
@jwt_required()
def retry_deployment_job(job_id):
    """Retry a failed deployment job by cloning it and enqueuing a fresh run
    (plan 51 D8). Only failed jobs may be retried."""
    from flask_jwt_extended import get_jwt_identity
    result = DeploymentJobService.retry_job(job_id, user_id=get_jwt_identity())
    if not result.get('success'):
        # Distinguish "no such job" from a state/enqueue error.
        status = 404 if result.get('error') == 'Deployment job not found' else 400
        return jsonify({'error': result.get('error')}), status
    return jsonify(result), 202


@deployment_jobs_bp.route('/<job_id>/logs', methods=['GET'])
@jwt_required()
def get_deployment_job_logs(job_id):
    job = DeploymentJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Deployment job not found'}), 404

    after_id = request.args.get('after_id', type=int)
    query = DeploymentJobLog.query.filter_by(job_id=job_id)
    if after_id:
        query = query.filter(DeploymentJobLog.id > after_id)

    logs = query.order_by(DeploymentJobLog.created_at.asc()).all()
    return jsonify({'logs': [log.to_dict() for log in logs]}), 200
