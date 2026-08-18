import json
import hmac
import hashlib
import base64
from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin


class WebhookEndpoint(JsonColumnMixin, db.Model):
    """Inbound webhook endpoint configuration."""
    __tablename__ = 'webhook_endpoints'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    slug = db.Column(db.String(220), nullable=False, unique=True, index=True)
    secret = db.Column(db.String(500), nullable=False)  # HMAC secret
    is_active = db.Column(db.Boolean, default=True)
    filter_paths = db.Column(db.Text, nullable=True)  # JSON list of dotted-path filters
    forward_url = db.Column(db.String(500), nullable=True)
    retry_count = db.Column(db.Integer, default=3)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Workspace scoping (#33): backfilled to the Default workspace by migration 021.
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deliveries = db.relationship('WebhookDelivery', backref='endpoint', lazy='dynamic', cascade='all, delete-orphan')

    def get_filter_paths(self):
        return self._json_read('filter_paths', [])

    def set_filter_paths(self, paths):
        self._json_write('filter_paths', list(paths) if paths else None)

    def verify_signature(self, payload: bytes, signature_header: str, algorithm: str = 'sha256') -> bool:
        """Verify HMAC-SHA1/SHA256 signature from header."""
        if not signature_header:
            return False
        if algorithm == 'sha256':
            expected = 'sha256=' + hmac.new(self.secret.encode(), payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature_header)
        if algorithm == 'sha1':
            expected = 'sha1=' + hmac.new(self.secret.encode(), payload, hashlib.sha1).hexdigest()
            return hmac.compare_digest(expected, signature_header)
        return False

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'is_active': self.is_active,
            'filter_paths': self.get_filter_paths(),
            'forward_url': self.forward_url,
            'retry_count': self.retry_count,
            'workspace_id': self.workspace_id,
            'delivery_count': self.deliveries.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WebhookDelivery(JsonColumnMixin, db.Model):
    """Log of an inbound webhook delivery."""
    __tablename__ = 'webhook_deliveries'

    id = db.Column(db.Integer, primary_key=True)
    endpoint_id = db.Column(db.Integer, db.ForeignKey('webhook_endpoints.id', ondelete='CASCADE'), nullable=False, index=True)
    event_id = db.Column(db.String(300), nullable=False, unique=True, index=True)
    payload = db.Column(db.Text, nullable=True)
    headers = db.Column(db.Text, nullable=True)
    signature_valid = db.Column(db.Boolean, nullable=True)
    status = db.Column(db.String(50), default='received')  # received, filtered, forwarded, failed
    response_status = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    def get_headers(self):
        return self._json_read('headers')

    def set_headers(self, headers):
        self._json_write('headers', dict(headers) if headers else None)

    def to_dict(self):
        return {
            'id': self.id,
            'endpoint_id': self.endpoint_id,
            'event_id': self.event_id,
            'payload': json.loads(self.payload) if self.payload else None,
            'signature_valid': self.signature_valid,
            'status': self.status,
            'response_status': self.response_status,
            'error_message': self.error_message,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }
