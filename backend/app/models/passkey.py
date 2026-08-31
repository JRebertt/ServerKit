import base64
from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin


def _b64decode_url(value: str) -> bytes:
    """URL-safe base64 decode with padding fix."""
    if not value:
        return b''
    padding = 4 - len(value) % 4
    if padding != 4:
        value += '=' * padding
    return base64.urlsafe_b64decode(value)


class PasskeyCredential(JsonColumnMixin, db.Model):
    """Stored WebAuthn credential for a user."""
    __tablename__ = 'passkey_credentials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    credential_id = db.Column(db.String(500), nullable=False, unique=True, index=True)
    public_key = db.Column(db.Text, nullable=False)  # base64url-encoded COSE key
    sign_count = db.Column(db.Integer, default=0)
    transports = db.Column(db.Text, nullable=True)  # JSON list
    device_name = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    # cascade: user_id is NOT NULL — passkeys die with the account.
    user = db.relationship('User', backref=db.backref(
        'passkeys', lazy='dynamic', cascade='all, delete-orphan'))

    def get_transports(self):
        return self._json_read('transports', [])

    def set_transports(self, transports):
        self._json_write('transports', list(transports) if transports else None)

    def to_dict(self):
        return {
            'id': self.id,
            'credential_id': self.credential_id,
            'device_name': self.device_name,
            'transports': self.get_transports(),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }
