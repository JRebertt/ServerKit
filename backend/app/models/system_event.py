"""System-wide telemetry event model.

A single, queryable event stream that records what happened, when, and to which
resource across ServerKit. Existing domain-specific tables (audit_logs,
event_deliveries, notification_deliveries, metrics_history, etc.) remain the
authoritative sources; SystemEvent is a correlation layer on top.
"""
import json
from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class SystemEvent(JsonColumnMixin, db.Model):
    """A single event in the unified telemetry stream."""

    __tablename__ = 'system_events'

    # Severity levels
    SEVERITY_DEBUG = 'debug'
    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_ERROR = 'error'
    SEVERITY_CRITICAL = 'critical'
    VALID_SEVERITIES = [
        SEVERITY_DEBUG,
        SEVERITY_INFO,
        SEVERITY_WARNING,
        SEVERITY_ERROR,
        SEVERITY_CRITICAL,
    ]

    # Common event sources
    SOURCE_AUDIT = 'audit'
    SOURCE_BACKUP = 'backup'
    SOURCE_DEPLOYMENT = 'deployment'
    SOURCE_MONITORING = 'monitoring'
    SOURCE_NOTIFICATION = 'notification'
    SOURCE_WEBHOOK = 'webhook'
    SOURCE_WORKFLOW = 'workflow'
    SOURCE_EVENT = 'event'

    id = db.Column(db.Integer, primary_key=True)

    # When the event occurred (may differ from created_at if backdated)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Categorization
    source = db.Column(db.String(50), nullable=False, index=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False, default=SEVERITY_INFO, index=True)

    # Resource scoping
    resource_type = db.Column(db.String(50), nullable=True, index=True)
    resource_id = db.Column(db.String(100), nullable=True, index=True)

    # Actor scoping
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)

    # Human-readable summary
    message = db.Column(db.Text, nullable=True)

    # Correlation / trace ID for grouping related events
    correlation_id = db.Column(db.String(64), nullable=True, index=True)

    # Free-form JSON payload (sanitized before storage)
    payload_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationships
    actor = db.relationship('User', foreign_keys=[actor_user_id])
    workspace = db.relationship('Workspace', foreign_keys=[workspace_id])

    # Composite indexes for common query patterns
    __table_args__ = (
        db.Index('idx_system_events_source_timestamp', 'source', 'timestamp'),
        db.Index('idx_system_events_type_timestamp', 'event_type', 'timestamp'),
        db.Index('idx_system_events_resource', 'resource_type', 'resource_id'),
        db.Index('idx_system_events_severity_timestamp', 'severity', 'timestamp'),
    )

    def get_payload(self):
        """Return parsed payload JSON."""
        return self._json_read('payload_json')

    def set_payload(self, payload_dict):
        """Set payload from a dictionary."""
        self.payload_json = json.dumps(payload_dict) if payload_dict is not None else None

    def to_dict(self, include_payload=True):
        data = {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'source': self.source,
            'event_type': self.event_type,
            'severity': self.severity,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'actor_user_id': self.actor_user_id,
            'actor_username': self.actor.username if self.actor else None,
            'workspace_id': self.workspace_id,
            'workspace_name': self.workspace.name if self.workspace else None,
            'message': self.message,
            'correlation_id': self.correlation_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_payload:
            data['payload'] = self.get_payload()
        return data

    def __repr__(self):
        return f'<SystemEvent {self.source}.{self.event_type} {self.severity}>'
