"""
Monitors API

Uptime/synthetic checks against URLs, hosts and managed sites. Core, not part of
the serverkit-status extension — watching a site must not require publishing a
status page. See app/services/monitor_service.py.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.exceptions import NotFoundError
from app.services.monitor_service import MonitorService

monitors_bp = Blueprint('monitors', __name__)


@monitors_bp.route('', methods=['GET'])
@monitors_bp.route('/', methods=['GET'])
@jwt_required()
def list_monitors():
    """List monitors.

    Query params: status, type, q, page_id.
    """
    page_id = request.args.get('page_id', type=int)
    monitors = MonitorService.list_monitors(
        status=request.args.get('status') or None,
        check_type=request.args.get('type') or None,
        q=request.args.get('q') or None,
        page_id=page_id,
    )
    # One extra query for every row's sparkline, not one per row.
    sparks = MonitorService.recent_response_times([m.id for m in monitors])
    payload = []
    for monitor in monitors:
        item = monitor.to_dict()
        item['spark'] = sparks.get(monitor.id, [])
        payload.append(item)
    return jsonify({'monitors': payload})


@monitors_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    """KPI-band counts for the Monitors tab."""
    return jsonify({'stats': MonitorService.stats()})


@monitors_bp.route('', methods=['POST'])
@monitors_bp.route('/', methods=['POST'])
@jwt_required()
def create_monitor():
    data = request.get_json() or {}
    monitor = MonitorService.create(data)
    return jsonify(monitor.to_dict()), 201


@monitors_bp.route('/<int:monitor_id>', methods=['GET'])
@jwt_required()
def get_monitor(monitor_id):
    monitor = MonitorService.get(monitor_id)
    if not monitor:
        raise NotFoundError('Monitor not found', code='monitor_not_found')
    return jsonify(monitor.to_dict())


@monitors_bp.route('/<int:monitor_id>', methods=['PATCH', 'PUT'])
@jwt_required()
def update_monitor(monitor_id):
    data = request.get_json() or {}
    monitor = MonitorService.update(monitor_id, data)
    if not monitor:
        raise NotFoundError('Monitor not found', code='monitor_not_found')
    return jsonify(monitor.to_dict())


@monitors_bp.route('/<int:monitor_id>', methods=['DELETE'])
@jwt_required()
def delete_monitor(monitor_id):
    if not MonitorService.delete(monitor_id):
        return {'error': 'Monitor not found'}, 404
    return jsonify({'deleted': True})


@monitors_bp.route('/<int:monitor_id>/check', methods=['POST'])
@jwt_required()
def run_check(monitor_id):
    """Probe now, out of band from the scheduler."""
    hc = MonitorService.run_check(monitor_id)
    if not hc:
        return {'error': 'Monitor not found'}, 404
    monitor = MonitorService.get(monitor_id)
    return jsonify({'check': hc.to_dict(), 'monitor': monitor.to_dict()})


@monitors_bp.route('/<int:monitor_id>/pause', methods=['POST'])
@jwt_required()
def set_paused(monitor_id):
    data = request.get_json() or {}
    monitor = MonitorService.set_paused(monitor_id, data.get('paused', True))
    if not monitor:
        return {'error': 'Monitor not found'}, 404
    return jsonify(monitor.to_dict())


@monitors_bp.route('/<int:monitor_id>/history', methods=['GET'])
@jwt_required()
def get_history(monitor_id):
    """Recent check results. Query params: hours (default 24), limit."""
    if not MonitorService.get(monitor_id):
        return {'error': 'Monitor not found'}, 404
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 200, type=int)
    checks = MonitorService.get_check_history(monitor_id, hours=hours, limit=limit)
    return jsonify({'checks': [c.to_dict() for c in checks]})


@monitors_bp.route('/<int:monitor_id>/uptime', methods=['GET'])
@jwt_required()
def get_uptime(monitor_id):
    """Per-day uptime buckets for the 90-day bar strip. Query param: days."""
    monitor = MonitorService.get(monitor_id)
    if not monitor:
        return {'error': 'Monitor not found'}, 404
    days = min(request.args.get('days', 90, type=int), 365)
    return jsonify({
        'days': MonitorService.uptime_days(monitor_id, days=days),
        'uptime_24h': monitor.uptime_24h,
        'uptime_7d': monitor.uptime_7d,
        'uptime_30d': monitor.uptime_30d,
        'uptime_90d': monitor.uptime_90d,
    })


# --- Incidents -------------------------------------------------------------
# Incidents are core because the scheduler opens them automatically, with or
# without the status-page extension installed.

@monitors_bp.route('/incidents', methods=['GET'])
@jwt_required()
def list_incidents():
    """Query params: state (active|resolved|all), limit."""
    state = request.args.get('state', 'all')
    limit = request.args.get('limit', 100, type=int)
    incidents = MonitorService.list_incidents(state=state, limit=limit)
    return jsonify({'incidents': [i.to_dict() for i in incidents]})


@monitors_bp.route('/incidents', methods=['POST'])
@jwt_required()
def create_incident():
    data = request.get_json() or {}
    if not data.get('title'):
        return {'error': 'Incident title is required'}, 400
    incident = MonitorService.create_incident(data.get('page_id'), data)
    return jsonify(incident.to_dict()), 201


@monitors_bp.route('/incidents/<int:incident_id>', methods=['PATCH', 'PUT'])
@jwt_required()
def update_incident(incident_id):
    incident = MonitorService.update_incident(incident_id, request.get_json() or {})
    if not incident:
        return {'error': 'Incident not found'}, 404
    return jsonify(incident.to_dict())


@monitors_bp.route('/incidents/<int:incident_id>', methods=['DELETE'])
@jwt_required()
def delete_incident(incident_id):
    if not MonitorService.delete_incident(incident_id):
        return {'error': 'Incident not found'}, 404
    return jsonify({'deleted': True})
