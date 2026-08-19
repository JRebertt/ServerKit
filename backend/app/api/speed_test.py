"""REST surface for the on-demand server speed test.

Mounted at /api/v1/speedtest (registered in app/__init__.py).
"""
from flask import Blueprint, jsonify
from app.error_reporting import unexpected_response

from ..middleware.rbac import admin_required, viewer_required
from ..services.speed_test_service import SPEEDTEST_JOB_KIND, SpeedTestService

speedtest_bp = Blueprint('speedtest', __name__)


@speedtest_bp.route('', methods=['GET'])
@speedtest_bp.route('/', methods=['GET'])
@viewer_required
def get_speed_test():
    """Last stored result + status of any in-flight speed test job."""
    try:
        return jsonify(SpeedTestService.get_status())
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@speedtest_bp.route('/run', methods=['POST'])
@admin_required
def run_speed_test():
    """Enqueue a one-off speed test job. Rejects if one is already in flight."""
    try:
        if SpeedTestService.is_running():
            return jsonify({'error': 'A speed test is already in progress.'}), 409
        from app.jobs.service import JobService
        job = JobService.enqueue(SPEEDTEST_JOB_KIND, payload={}, max_attempts=1)
        return jsonify({'job_id': job.id}), 202
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
