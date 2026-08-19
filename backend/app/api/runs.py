"""Run envelope REST twin (plan 77 E1).

The polling counterpart of the `run_log` / `run_status` socket events: any
run kind's persisted lines, resumable via ?after_id, so a client that missed
socket frames (or has sockets disabled) can always catch up. The deploy kind
keeps its richer legacy endpoint (/api/v1/deployment-jobs/<id>/logs) — this
one serves every kind stored in run_log_entries.
"""
from flask import Blueprint, jsonify, request

from app.middleware.rbac import auth_required
from app.services.run_log_service import list_run_logs

runs_bp = Blueprint('runs', __name__)


@runs_bp.route('/<run_kind>/<run_id>/logs', methods=['GET'])
@auth_required()
def get_run_logs(run_kind, run_id):
    after_id = request.args.get('after_id', type=int)
    return jsonify({'logs': list_run_logs(run_kind, run_id, after_id=after_id)}), 200
