"""Telemetry service for the unified system event stream.

This service provides a single, fire-and-forget way to record events from any
subsystem. It never raises into callers and redacts known sensitive keys from
payloads before storage.
"""
import json
import logging
import secrets
from datetime import datetime, timedelta

from flask import g, has_request_context, request
from sqlalchemy import func

from app import db
from app.models.system_event import SystemEvent

logger = logging.getLogger(__name__)

from app.utils.sensitive_data_filter import (  # noqa: F401 (re-export)
    REDACTED,
    SENSITIVE_KEY_PARTS,
    is_sensitive_key as _shared_is_sensitive_key,
)

MAX_STRING_LENGTH = 2000
MAX_LIST_ITEMS = 50
MAX_DICT_ITEMS = 50
MAX_PAYLOAD_BYTES = 32 * 1024


def generate_correlation_id():
    """Generate a unique correlation ID for grouping related events."""
    return secrets.token_hex(16)


class TelemetryService:
    """Service for emitting and querying system telemetry events."""

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------
    @classmethod
    def emit(cls, source, event_type, message=None, severity=SystemEvent.SEVERITY_INFO,
             resource_type=None, resource_id=None, actor_user_id=None, workspace_id=None,
             correlation_id=None, payload=None, commit=True):
        """Record a telemetry event.

        This method is fire-and-forget: any failure is logged but never raised,
        so telemetry cannot break the calling operation.
        """
        try:
            event = cls._create_event(
                source=source,
                event_type=event_type,
                message=message,
                severity=severity,
                resource_type=resource_type,
                resource_id=_stringify_resource_id(resource_id),
                actor_user_id=actor_user_id,
                workspace_id=workspace_id,
                correlation_id=correlation_id,
                payload=payload,
            )
            db.session.add(event)
            if commit:
                db.session.commit()
            return event
        except Exception as exc:
            logger.warning('Telemetry emit failed for %s.%s: %s', source, event_type, exc)
            db.session.rollback()
            return None

    @classmethod
    def emit_for_request(cls, source, event_type, message=None, severity=SystemEvent.SEVERITY_INFO,
                         resource_type=None, resource_id=None, correlation_id=None, payload=None,
                         commit=True):
        """Emit an event, deriving actor/workspace from the current request context."""
        actor_user_id, workspace_id = cls._get_request_scope()
        return cls.emit(
            source=source,
            event_type=event_type,
            message=message,
            severity=severity,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            correlation_id=correlation_id,
            payload=payload,
            commit=commit,
        )

    @classmethod
    def _create_event(cls, source, event_type, message, severity, resource_type,
                      resource_id, actor_user_id, workspace_id, correlation_id, payload):
        if severity not in SystemEvent.VALID_SEVERITIES:
            severity = SystemEvent.SEVERITY_INFO

        sanitized_payload = _sanitize_payload(payload) if payload is not None else None
        if sanitized_payload is not None and _payload_too_large(sanitized_payload):
            sanitized_payload = {'_truncated': True}

        # Truncate very long messages
        if message is not None and len(message) > 4000:
            message = message[:4000] + '...[truncated]'

        event = SystemEvent(
            timestamp=datetime.utcnow(),
            source=source,
            event_type=event_type,
            severity=severity,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            message=message,
            correlation_id=correlation_id,
        )
        event.set_payload(sanitized_payload)
        return event

    @staticmethod
    def _get_request_scope():
        """Return (actor_user_id, workspace_id) from request context if available."""
        if not has_request_context():
            return None, None

        actor_user_id = None
        workspace_id = None

        # JWT or API key user
        try:
            from flask_jwt_extended import get_jwt_identity
            identity = get_jwt_identity()
            if identity is not None:
                try:
                    actor_user_id = int(identity)
                except (TypeError, ValueError):
                    actor_user_id = identity
        except Exception:
            pass

        if actor_user_id is None:
            api_key_user = getattr(g, 'api_key_user', None)
            if api_key_user is not None:
                actor_user_id = api_key_user.id

        # Workspace from g if set by other middleware
        workspace_id = getattr(g, 'workspace_id', None)

        return actor_user_id, workspace_id

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    @classmethod
    def get_events(cls, page=1, per_page=50, source=None, event_type=None, severity=None,
                   resource_type=None, resource_id=None, correlation_id=None,
                   start_date=None, end_date=None, message_query=None):
        """Query system events with filters and pagination."""
        query = SystemEvent.query.order_by(SystemEvent.timestamp.desc())

        if source:
            query = query.filter(SystemEvent.source == source)
        if event_type:
            query = query.filter(SystemEvent.event_type == event_type)
        if severity:
            query = query.filter(SystemEvent.severity == severity)
        if resource_type:
            query = query.filter(SystemEvent.resource_type == resource_type)
        if resource_id is not None:
            query = query.filter(SystemEvent.resource_id == _stringify_resource_id(resource_id))
        if correlation_id:
            query = query.filter(SystemEvent.correlation_id == correlation_id)
        if start_date:
            query = query.filter(SystemEvent.timestamp >= start_date)
        if end_date:
            query = query.filter(SystemEvent.timestamp <= end_date)
        if message_query:
            query = query.filter(SystemEvent.message.ilike(f'%{message_query}%'))

        return query.paginate(page=page, per_page=per_page, error_out=False)

    @classmethod
    def get_event_by_id(cls, event_id):
        """Get a single event by ID."""
        return db.session.get(SystemEvent, event_id)

    @classmethod
    def get_events_by_correlation(cls, correlation_id, limit=100):
        """Get all events sharing a correlation ID, oldest first."""
        return (SystemEvent.query
                .filter_by(correlation_id=correlation_id)
                .order_by(SystemEvent.timestamp.asc())
                .limit(limit)
                .all())

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    @classmethod
    def get_stats(cls, hours=24, source=None):
        """Return aggregate stats for the given time window."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        query = SystemEvent.query.filter(SystemEvent.timestamp >= cutoff)
        if source:
            query = query.filter(SystemEvent.source == source)

        total = query.count()

        by_severity = dict(
            query.with_entities(SystemEvent.severity, func.count(SystemEvent.id))
            .group_by(SystemEvent.severity)
            .all()
        )

        by_source = dict(
            query.with_entities(SystemEvent.source, func.count(SystemEvent.id))
            .group_by(SystemEvent.source)
            .all()
        )

        return {
            'total': total,
            'by_severity': by_severity,
            'by_source': by_source,
            'hours': hours,
        }

    @classmethod
    def get_recent_event_types(cls, limit=20):
        """Return the most common event types in the last 24 hours."""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        rows = (SystemEvent.query
                .filter(SystemEvent.timestamp >= cutoff)
                .with_entities(SystemEvent.event_type, func.count(SystemEvent.id))
                .group_by(SystemEvent.event_type)
                .order_by(func.count(SystemEvent.id).desc())
                .limit(limit)
                .all())
        return [{'event_type': t, 'count': c} for t, c in rows]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    @classmethod
    def cleanup_old_events(cls, days=90):
        """Delete events older than the specified number of days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = SystemEvent.query.filter(SystemEvent.timestamp < cutoff).delete()
        db.session.commit()
        return deleted


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def _stringify_resource_id(resource_id):
    """Normalize resource IDs to strings to support int/UUID/mixed use."""
    if resource_id is None:
        return None
    return str(resource_id)


def _sanitize_payload(value, key=None, depth=0):
    """Sanitize a payload dict/list, redacting sensitive keys and capping size."""
    if key and _is_sensitive_key(key):
        return REDACTED
    if depth >= 4:
        return '[truncated]'

    if isinstance(value, dict):
        result = {}
        for item_key, item_value in list(value.items())[:MAX_DICT_ITEMS]:
            safe_key = str(item_key)[:MAX_STRING_LENGTH]
            result[safe_key] = _sanitize_payload(item_value, key=safe_key, depth=depth + 1)
        return result

    if isinstance(value, (list, tuple)):
        result = [_sanitize_payload(item, depth=depth + 1) for item in value[:MAX_LIST_ITEMS]]
        return result

    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            return value[:MAX_STRING_LENGTH] + '...[truncated]'
        return value

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return str(value)[:MAX_STRING_LENGTH]


def _is_sensitive_key(key):
    return _shared_is_sensitive_key(str(key))


def _payload_too_large(payload):
    """Check whether a payload would exceed the storage limit when serialized."""
    try:
        return len(json.dumps(payload).encode('utf-8')) > MAX_PAYLOAD_BYTES
    except (TypeError, ValueError):
        return False
