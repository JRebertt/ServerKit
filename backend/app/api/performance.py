from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.cache_service import CacheService
from app.jobs.service import JobService
from app.middleware.rbac import get_current_user

performance_bp = Blueprint('performance', __name__)


@performance_bp.route('/cache/stats', methods=['GET'])
@jwt_required()
def cache_stats():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    return jsonify(CacheService.get_stats())


@performance_bp.route('/cache/flush', methods=['POST'])
@jwt_required()
def cache_flush():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    CacheService.flush()
    return jsonify({'message': 'Cache flushed'})


@performance_bp.route('/jobs', methods=['GET'])
@jwt_required()
def list_jobs():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    # Keyed by id to preserve the prior {job_id: info} response shape.
    return jsonify({'jobs': {j.id: j.to_dict() for j in JobService.list(limit=200)}})


@performance_bp.route('/jobs/<job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    job = JobService.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({'job_id': job_id, **job.to_dict(include_payload=True)})


@performance_bp.route('/jobs/stats', methods=['GET'])
@jwt_required()
def job_stats():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    stats = JobService.stats()
    return jsonify({
        'total_jobs': stats['total'],
        'by_status': stats['by_status'],
        'by_kind': stats['by_kind'],
        'running': stats['by_status'].get('running', 0),
        'queue_size': stats['by_status'].get('pending', 0),
    })


@performance_bp.route('/jobs/cleanup', methods=['POST'])
@jwt_required()
def cleanup_jobs():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    deleted = JobService.cleanup_old()
    return jsonify({'message': f'Cleaned up {deleted} old job(s)'})
