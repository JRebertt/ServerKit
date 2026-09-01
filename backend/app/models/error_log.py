from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin


class ErrorLog(JsonColumnMixin, db.Model):
    """Centralized error log with fingerprint-based dedup."""
    __tablename__ = 'error_logs'

    id = db.Column(db.Integer, primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False, index=True)  # sha256 hex
    source = db.Column(db.String(20), nullable=False, index=True)  # backend | frontend
    level = db.Column(db.String(20), nullable=False, default='error')
    exception_type = db.Column(db.String(200), nullable=True)
    message = db.Column(db.Text, nullable=False)
    traceback = db.Column(db.Text, nullable=True)
    endpoint = db.Column(db.String(255), nullable=True)  # API path / page URL
    method = db.Column(db.String(10), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    context_json = db.Column(db.Text, nullable=True)  # JSON string
    count = db.Column(db.Integer, nullable=False, default=1)  # dedup hit counter
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    resolved = db.Column(db.Boolean, default=False, index=True)

    # Relationship to user
    user = db.relationship('User', foreign_keys=[user_id])

    def get_context(self):
        """Return parsed context JSON."""
        return self._json_read('context_json')

    def set_context(self, context_dict):
        """Set context from a dictionary."""
        self._json_write('context_json', context_dict)

    def to_dict(self):
        return {
            'id': self.id,
            'fingerprint': self.fingerprint,
            'source': self.source,
            'level': self.level,
            'exception_type': self.exception_type,
            'message': self.message,
            'traceback': self.traceback,
            'endpoint': self.endpoint,
            'method': self.method,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'context': self.get_context(),
            'count': self.count,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'resolved': self.resolved,
        }

    def __repr__(self):
        return f'<ErrorLog {self.source}:{self.exception_type} x{self.count}>'
