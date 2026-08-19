"""REST surface for the fleet health doctor — the panel-host doctor extended
across the agent fleet (plan 26 / ``docs/FLEET_CONTRACT.md``).

Mounted at /api/v1/doctor/fleet (registered in app/__init__.py). Admin-only:
the fleet is not workspace-scoped (Fleet Contract, "explicitly out of scope").

Contract (the frontend ``api/doctor.js`` codes against this):
    GET  /doctor/fleet          -> {'report': {'ran_at', 'servers': [...]}}
    POST /doctor/fleet/run      -> 202 {'job_id'} — the sweep fans out across
                                   agents over the network, so it runs inside a
                                   job handler, never on this request thread
                                   (Fleet Contract, rule 4: the agent gateway
                                   registry is single-worker + in-memory).
    POST /doctor/fleet/repair   -> {'results': [...]} for body
                                   {'items': [{kind, server_id, name}]}

The repair route is a thin passthrough to :class:`FleetRepairService`, which
owns the allowlist, the capability gate and the audit trail (rule 6) — this
layer only authenticates, shapes the batch, and reports refusals as results
rather than errors.
"""
from flask import Blueprint, jsonify, request
from app.error_reporting import unexpected_response

from ..middleware.rbac import admin_required, get_current_user
from ..services.fleet_doctor_service import FLEET_DOCTOR_JOB_KIND, FleetDoctorService
from ..services.fleet_repair_service import FleetRepairService

fleet_doctor_bp = Blueprint('fleet_doctor', __name__)

# A batch bound so one request can't turn into an unbounded fan-out of remote
# mutations against the single-worker gateway.
MAX_REPAIR_ITEMS = 25


@fleet_doctor_bp.route('', methods=['GET'])
@fleet_doctor_bp.route('/', methods=['GET'])
@admin_required
def get_fleet_report():
    """Last recorded per-server rows for every registered server.

    Never runs a sweep: reads the ``fleet_doctor_results`` rows the scheduled
    (or manually enqueued) job wrote. Servers with no rows yet are still listed
    so a freshly paired box is visible before its first sweep.
    """
    try:
        return jsonify({'report': FleetDoctorService.fleet_report()})
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@fleet_doctor_bp.route('/run', methods=['POST'])
@admin_required
def run_fleet_sweep():
    """Enqueue the fleet sweep. 202 + job id — never synchronous."""
    try:
        from app.jobs.service import JobService
        job = JobService.enqueue(FLEET_DOCTOR_JOB_KIND, payload={}, max_attempts=1)
        return jsonify({'job_id': job.id}), 202
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@fleet_doctor_bp.route('/repair', methods=['POST'])
@admin_required
def repair_fleet_items():
    """Batch-run the allowlisted remote repairs the operator selected.

    Each item is the ``repair_ref`` of a repairable finding. A refusal (not
    allowlisted, unknown target, agent offline, capability missing) comes back
    as a per-item ``success: false`` result — the request still succeeds, which
    is what keeps one offline server from failing the whole batch.
    """
    data = request.get_json(silent=True) or {}
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({'error': "Body must carry a non-empty 'items' list."}), 400
    if len(items) > MAX_REPAIR_ITEMS:
        return jsonify({'error': f'At most {MAX_REPAIR_ITEMS} repairs per request.'}), 400

    user = get_current_user()
    user_id = user.id if user else None
    results = []
    try:
        for item in items:
            if not isinstance(item, dict):
                results.append({'success': False, 'error': 'Each item must be an object',
                                'code': 'BAD_REQUEST'})
                continue
            results.append(FleetRepairService.repair(item, user_id=user_id))
        return jsonify({'results': results})
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
