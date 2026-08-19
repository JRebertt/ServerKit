"""REST surface for the doctor sweep + configuration drift.

Mounted at /api/v1/doctor (registered in app/__init__.py). Admin-only.

Contract (the CLI codes against this too):
    GET  /drift                       -> {'report': <last drift report>|null}
    POST /drift/check                 -> 202 {'job_id'}
    POST /drift/<type>/<id>/repair    -> repair result; body must carry
                                         {'confirm': true} (400 otherwise)
    GET  /                            -> {'report': <last doctor report>|null}
    POST /run                         -> runs synchronously, {'report': ...}
    POST /repair                      -> {'results': [...]} for body
                                         {'items': [{kind, type?, id?, name?}]}
"""
from flask import Blueprint, jsonify, request
from app.error_reporting import unexpected_response

from ..middleware.rbac import admin_required
from ..services.doctor_service import DoctorService
from ..services.drift_service import DRIFT_JOB_KIND, DriftService

doctor_bp = Blueprint('doctor', __name__)


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #

@doctor_bp.route('/drift', methods=['GET'])
@admin_required
def get_drift_report():
    """Last stored drift report (null when no sweep has run yet)."""
    try:
        return jsonify({'report': DriftService.get_last_report()})
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@doctor_bp.route('/drift/check', methods=['POST'])
@admin_required
def run_drift_check():
    """Enqueue a one-off drift sweep job."""
    try:
        from app.jobs.service import JobService
        job = JobService.enqueue(DRIFT_JOB_KIND, payload={}, max_attempts=1)
        return jsonify({'job_id': job.id}), 202
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@doctor_bp.route('/drift/<check_type>/<resource_id>/repair', methods=['POST'])
@admin_required
def repair_drift(check_type, resource_id):
    """Repair one drifted resource. Explicit confirmation required."""
    data = request.get_json(silent=True) or {}
    if data.get('confirm') is not True:
        return jsonify({'error': 'Confirmation required: pass {"confirm": true}.'}), 400
    try:
        rid = int(resource_id) if resource_id.isdigit() else resource_id
        result = DriftService.repair(check_type, rid)
        status = 200 if result.get('success') else 400
        return jsonify(result), status
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


# --------------------------------------------------------------------------- #
# Doctor
# --------------------------------------------------------------------------- #

@doctor_bp.route('', methods=['GET'])
@doctor_bp.route('/', methods=['GET'])
@admin_required
def get_doctor_report():
    """Last stored doctor report (null when the doctor has never run)."""
    try:
        return jsonify({'report': DoctorService.get_last_report()})
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@doctor_bp.route('/run', methods=['POST'])
@admin_required
def run_doctor():
    """Run the sweep synchronously (the doctor is interactive; every internal
    probe is time-capped) and return the fresh report."""
    try:
        report = DoctorService.run()
        return jsonify({'report': report})
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@doctor_bp.route('/repair', methods=['POST'])
@admin_required
def repair_items():
    """Batch-repair the explicit items the operator selected."""
    data = request.get_json(silent=True) or {}
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({'error': "Body must carry a non-empty 'items' list."}), 400
    try:
        return jsonify({'results': DoctorService.repair(items)})
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
