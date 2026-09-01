from datetime import datetime

from app import db


class LoginLink(db.Model):
    """A single-use, short-TTL login URL minted by an admin.

    Only the SHA-256 hash of the token is stored; the raw token is returned
    exactly once at mint time. A link may optionally be bound to a single
    client IP. Rows are reaped on a schedule once used or expired.
    """

    __tablename__ = 'login_links'

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    created_by_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    bound_ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('login_links', lazy='dynamic'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def is_expired(self):
        return self.expires_at is not None and datetime.utcnow() >= self.expires_at

    @property
    def is_used(self):
        return self.used_at is not None

    def to_dict(self):
        # NEVER expose token_hash — the raw token is shown once at mint time.
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'created_by_id': self.created_by_id,
            'created_by': self.created_by.username if self.created_by else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'used_at': self.used_at.isoformat() if self.used_at else None,
            'bound_ip': self.bound_ip,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<LoginLink user={self.user_id} expires={self.expires_at}>'
