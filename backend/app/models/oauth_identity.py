from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin


class OAuthIdentity(TimestampMixin, db.Model):
    """Links an external OAuth/SAML identity to a local user."""
    __tablename__ = 'oauth_identities'
    __table_args__ = (
        db.UniqueConstraint('provider', 'provider_user_id', name='uq_provider_identity'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False)  # google, github, oidc, saml
    provider_user_id = db.Column(db.String(256), nullable=False)
    provider_email = db.Column(db.String(256), nullable=True)
    provider_display_name = db.Column(db.String(256), nullable=True)
    access_token_encrypted = db.Column(db.Text, nullable=True)
    refresh_token_encrypted = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # cascade: user_id is NOT NULL — linked identities die with the account.
    user = db.relationship('User', backref=db.backref(
        'oauth_identities', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'provider_email': self.provider_email,
            'provider_display_name': self.provider_display_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
        }

    def __repr__(self):
        return f'<OAuthIdentity {self.provider}:{self.provider_user_id}>'
