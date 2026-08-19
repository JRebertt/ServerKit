"""Telemetry / system event stream API."""
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func

from app.api._query import PageQuery
from app import db
from app.middleware.rbac import admin_required
from app.models.system_event import SystemEvent
from app.services.telemetry_service import TelemetryService

telemetry_bp = Blueprint('telemetry', __name__)


@telemetry_bp.route('/events', methods=['GET'])
@jwt_required()
def list_events():
    """List system events with filtering and pagination."""
    paging = PageQuery.from_request(request, max_per_page=200)
    source = request.args.get('source') or None
    event_type = request.args.get('event_type') or None
    severity = request.args.get('severity') or None
    resource_type = request.args.get('resource_type') or None
    resource_id = request.args.get('resource_id') or None
    correlation_id = request.args.get('correlation_id') or None
    message_query = request.args.get('q') or None

    start_date = _parse_iso_datetime(request.args.get('start_date'))
    end_date = _parse_iso_datetime(request.args.get('end_date'))

    pagination = TelemetryService.get_events(
        page=paging.page,
        per_page=paging.per_page,
        source=source,
        event_type=event_type,
        severity=severity,
        resource_type=resource_type,
        resource_id=resource_id,
        correlation_id=correlation_id,
        start_date=start_date,
        end_date=end_date,
        message_query=message_query,
    )

    return jsonify({
        'events': [event.to_dict(include_payload=True) for event in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': pagination.page,
        'per_page': pagination.per_page,
    }), 200


@telemetry_bp.route('/events/<int:event_id>', methods=['GET'])
@jwt_required()
def get_event(event_id):
    """Get a single system event by ID."""
    event = TelemetryService.get_event_by_id(event_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    return jsonify(event.to_dict(include_payload=True)), 200


@telemetry_bp.route('/events/by-correlation/<correlation_id>', methods=['GET'])
@jwt_required()
def get_events_by_correlation(correlation_id):
    """Get all events sharing a correlation ID."""
    limit = request.args.get('limit', 100, type=int)
    events = TelemetryService.get_events_by_correlation(correlation_id, limit=limit)
    return jsonify({
        'correlation_id': correlation_id,
        'events': [event.to_dict(include_payload=True) for event in events],
    }), 200


@telemetry_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    """Get telemetry aggregate stats."""
    hours = request.args.get('hours', 24, type=int)
    source = request.args.get('source') or None
    stats = TelemetryService.get_stats(hours=hours, source=source)
    stats['recent_event_types'] = TelemetryService.get_recent_event_types()
    return jsonify(stats), 200


@telemetry_bp.route('/sources', methods=['GET'])
@jwt_required()
def list_sources():
    """Return all distinct event sources."""
    sources = (db.session.query(SystemEvent.source)
               .distinct()
               .order_by(SystemEvent.source)
               .all())
    return jsonify({'sources': [s[0] for s in sources if s[0]]}), 200


@telemetry_bp.route('/event-types', methods=['GET'])
@jwt_required()
def list_event_types():
    """Return all distinct event types, optionally filtered by source."""
    source = request.args.get('source') or None
    query = db.session.query(SystemEvent.event_type).distinct()
    if source:
        query = query.filter(SystemEvent.source == source)
    types = query.order_by(SystemEvent.event_type).all()
    return jsonify({'event_types': [t[0] for t in types if t[0]]}), 200


@telemetry_bp.route('/events', methods=['DELETE'])
@admin_required
def cleanup_events():
    """Delete events older than the specified number of days (admin only)."""
    days = request.args.get('days', 90, type=int)
    deleted = TelemetryService.cleanup_old_events(days=days)
    return jsonify({'deleted': deleted}), 200


@telemetry_bp.route('/events/test', methods=['POST'])
@admin_required
def emit_test_event():
    """Emit a test telemetry event (admin only)."""
    data = request.get_json(silent=True) or {}
    user_id = get_jwt_identity()
    event = TelemetryService.emit(
        source=data.get('source', 'system'),
        event_type=data.get('event_type', 'telemetry.test'),
        message=data.get('message', 'Test telemetry event'),
        severity=data.get('severity', 'info'),
        actor_user_id=user_id,
        payload=data.get('payload', {'test': True}),
        commit=True,
    )
    if event:
        return jsonify(event.to_dict(include_payload=True)), 201
    return jsonify({'error': 'Failed to emit test event'}), 500


def _parse_iso_datetime(value):
    """Parse an ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None
