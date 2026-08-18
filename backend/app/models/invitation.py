from datetime import datetime
from uuid import uuid4
from app import db
from app.models.json_column_mixin import JsonColumnMixin


class Invitation(JsonColumnMixin, db.Model):
    """Team invitation model for invite-based registration."""
    __tablename__ = 'invitations'

    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_EXPIRED = 'expired'
    STATUS_REVOKED = 'revoked'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=True)  # Nullable for link-only invites
    token = db.Column(db.String(64), unique=True, nullable=False, index=True,
                      default=lambda: __import__('secrets').token_urlsafe(32))
    role = db.Column(db.String(20), nullable=False, default='developer')
    permissions = db.Column(db.Text, nullable=True)  # JSON custom permissions
    invited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    accepted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    inviter = db.relationship('User', foreign_keys=[invited_by])
    accepter = db.relationship('User', foreign_keys=[accepted_by])

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self):
        return self.status == self.STATUS_PENDING and not self.is_expired

    def get_permissions(self):
        return self._json_read('permissions', None)

    def set_permissions(self, perms_dict):
        self._json_write('permissions', perms_dict)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'token': self.token,
            'role': self.role,
            'permissions': self.get_permissions(),
            'invited_by': self.invited_by,
            'inviter_username': self.inviter.username if self.inviter else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
            'accepted_by': self.accepted_by,
            'status': self.status,
            'is_expired': self.is_expired,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Invitation {self.token[:8]}... role={self.role} status={self.status}>'
