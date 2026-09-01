"""Event subscription and delivery models for webhook system."""
from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin
from app.models.json_column_mixin import JsonColumnMixin
import secrets


class EventSubscription(TimestampMixin, JsonColumnMixin, db.Model):
    """Webhook subscription for event notifications."""
    __tablename__ = 'event_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(2048), nullable=False)
    secret = db.Column(db.String(256), nullable=True)
    events = db.Column(db.Text, nullable=False)  # JSON array of event types
    is_active = db.Column(db.Boolean, default=True)
    headers = db.Column(db.Text, nullable=True)  # JSON dict of custom headers
    retry_count = db.Column(db.Integer, default=3)
    timeout_seconds = db.Column(db.Integer, default=10)

    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('event_subscriptions', lazy='dynamic'))
    deliveries = db.relationship('EventDelivery', back_populates='subscription',
                                 lazy='dynamic', cascade='all, delete-orphan')

    @staticmethod
    def generate_secret():
        """Generate a signing secret for HMAC."""
        return 'whsec_' + secrets.token_hex(24)

    def get_events(self):
        """Return parsed events list."""
        return self._json_read('events', [])

    def set_events(self, events_list):
        """Set events from a list."""
        self._json_write('events', events_list, falsy='[]')

    def get_headers(self):
        """Return parsed custom headers."""
        return self._json_read('headers')

    def set_headers(self, headers_dict):
        """Set custom headers from a dict."""
        self._json_write('headers', headers_dict)

    def matches_event(self, event_type):
        """Check if this subscription matches the given event type."""
        events = self.get_events()
        if '*' in events:
            return True
        if event_type in events:
            return True
        # Check wildcard category match (e.g. 'app.*' matches 'app.created')
        category = event_type.split('.')[0] if '.' in event_type else event_type
        if f'{category}.*' in events:
            return True
        return False

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'url': self.url,
            'has_secret': bool(self.secret),
            'events': self.get_events(),
            'is_active': self.is_active,
            'headers': self.get_headers(),
            'retry_count': self.retry_count,
            'timeout_seconds': self.timeout_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<EventSubscription {self.name} → {self.url}>'


class EventDelivery(JsonColumnMixin, db.Model):
    """Record of a webhook delivery attempt."""
    __tablename__ = 'event_deliveries'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('event_subscriptions.id'), nullable=False, index=True)
    event_type = db.Column(db.String(100), nullable=False)
    payload = db.Column(db.Text, nullable=True)  # JSON
    status = db.Column(db.String(20), default='pending')  # pending | success | failed
    http_status = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.String(1000), nullable=True)
    attempts = db.Column(db.Integer, default=0)
    next_retry_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    duration_ms = db.Column(db.Float, nullable=True)

    # Correlation ID for grouping this webhook delivery with related telemetry events.
    correlation_id = db.Column(db.String(64), nullable=True, index=True)

    subscription = db.relationship('EventSubscription', back_populates='deliveries')

    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'

    def get_payload(self):
        return self._json_read('payload')

    def set_payload(self, payload_dict):
        self._json_write('payload', payload_dict)

    def to_dict(self):
        return {
            'id': self.id,
            'subscription_id': self.subscription_id,
            'event_type': self.event_type,
            'payload': self.get_payload(),
            'status': self.status,
            'http_status': self.http_status,
            'response_body': self.response_body,
            'attempts': self.attempts,
            'next_retry_at': self.next_retry_at.isoformat() if self.next_retry_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'duration_ms': self.duration_ms,
            'correlation_id': self.correlation_id,
        }

    def __repr__(self):
        return f'<EventDelivery {self.event_type} → {self.status}>'
