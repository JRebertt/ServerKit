"""Read/ops API for the unified job system — the single pane to observe all
background work. Admin-gated, mirroring app/api/queue_bus.py conventions."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.jobs import registry
from app.jobs.models import Job
from app.jobs.service import JobService, ScheduledJobService
from app.middleware.rbac import require_admin_user

jobs_bp = Blueprint('jobs', __name__)


def _job_payload(job, include_payload=False):
    """Serialize the operation actions this admin may invoke right now.

    The Jobs blueprint is admin-only, so permission is already settled at the
    route boundary. These flags are the remaining state/capability decision the
    shell needs; clients must not infer it from a status string.
    """
    payload = job.to_dict(include_payload=include_payload)
    payload['can_cancel'] = job.status in (Job.STATUS_PENDING, Job.STATUS_RUNNING)
    payload['can_retry'] = job.status in (Job.STATUS_FAILED, Job.STATUS_CANCELLED)
    return payload


# --- Static routes first; Werkzeug ranks these above the dynamic /<job_id>. ---
@jobs_bp.route('', methods=['GET'])
@jobs_bp.route('/', methods=['GET'])
@jwt_required()
def list_jobs():
    require_admin_user()
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        offset = max(int(request.args.get('offset', 0)), 0)
    except (TypeError, ValueError):
        limit, offset = 50, 0
    filters = {
        'status': request.args.get('status'),
        'kind': request.args.get('kind'),
        'owner_type': request.args.get('owner_type'),
        'owner_id': request.args.get('owner_id'),
        'q': request.args.get('q'),
    }
    jobs = JobService.list(limit=limit, offset=offset, **filters)
    total = JobService.count(**filters)
    return jsonify({
        'jobs': [_job_payload(j) for j in jobs],
        'total': total,
        'limit': limit,
        'offset': offset,
    })


@jobs_bp.route('/stats', methods=['GET'])
@jwt_required()
def job_stats():
    require_admin_user()
    return jsonify(JobService.stats())


@jobs_bp.route('/kinds', methods=['GET'])
@jwt_required()
def job_kinds():
    require_admin_user()
    return jsonify({'kinds': registry.registered_kinds()})


@jobs_bp.route('/scheduled', methods=['GET'])
@jwt_required()
def list_scheduled():
    require_admin_user()
    return jsonify({'scheduled': [s.to_dict() for s in ScheduledJobService.list()]})


@jobs_bp.route('/scheduled/<int:scheduled_id>/run', methods=['POST'])
@jwt_required()
def run_scheduled(scheduled_id):
    require_admin_user()
    job = ScheduledJobService.run_now(scheduled_id)
    if not job:
        return jsonify({'error': 'Scheduled job not found'}), 404
    return jsonify({'job': _job_payload(job)})


@jobs_bp.route('/scheduled/<int:scheduled_id>/enabled', methods=['POST'])
@jwt_required()
def toggle_scheduled(scheduled_id):
    require_admin_user()
    body = request.get_json(silent=True) or {}
    scheduled = ScheduledJobService.set_enabled(scheduled_id, bool(body.get('enabled', True)))
    if not scheduled:
        return jsonify({'error': 'Scheduled job not found'}), 404
    return jsonify({'scheduled': scheduled.to_dict()})


@jobs_bp.route('/<job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    require_admin_user()
    job = JobService.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({'job': _job_payload(job, include_payload=True)})


@jobs_bp.route('/<job_id>/cancel', methods=['POST'])
@jwt_required()
def cancel_job(job_id):
    require_admin_user()
    job = JobService.cancel(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({'job': _job_payload(job)})


@jobs_bp.route('/<job_id>/retry', methods=['POST'])
@jwt_required()
def retry_job(job_id):
    require_admin_user()
    job = JobService.retry(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({'job': _job_payload(job)})
