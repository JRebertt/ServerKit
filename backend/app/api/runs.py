"""Run envelope REST twin (plan 77 E1).

The polling counterpart of the `run_log` / `run_status` socket events: any
run kind's persisted lines, resumable via ?after_id, so a client that missed
socket frames (or has sockets disabled) can always catch up. The deploy kind
keeps its richer legacy endpoint (/api/v1/deployment-jobs/<id>/logs) — this
one serves every kind stored in run_log_entries.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.models.run_log import RunLogEntry

runs_bp = Blueprint('runs', __name__)


@runs_bp.route('/<run_kind>/<run_id>/logs', methods=['GET'])
@jwt_required()
def get_run_logs(run_kind, run_id):
    after_id = request.args.get('after_id', type=int)
    query = RunLogEntry.query.filter_by(run_kind=run_kind, run_id=str(run_id))
    if after_id:
        query = query.filter(RunLogEntry.id > after_id)
    rows = query.order_by(RunLogEntry.id.asc()).limit(2000).all()
    return jsonify({'logs': [row.to_dict() for row in rows]}), 200
