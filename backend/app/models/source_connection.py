from datetime import datetime

from app import db
from app.models.mixins import EncryptedSecret, SerializableMixin


class SourceConnection(SerializableMixin, db.Model):
    """External source-code provider connection for repository imports.

    The ``provider`` column is a plain string and accepts any supported
    provider value (e.g. ``'github'`` or ``'gitlab'``); there is no enum or
    allow-list to extend.
    """

    __tablename__ = 'source_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    provider = db.Column(db.String(40), nullable=False, index=True)
    provider_account_id = db.Column(db.String(120), nullable=True, index=True)
    provider_username = db.Column(db.String(120), nullable=True)
    display_name = db.Column(db.String(180), nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    access_token_encrypted = db.Column(db.Text, nullable=False)
    access_token = EncryptedSecret('access_token_encrypted', legacy_plaintext=True)
    scope = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    # cascade: user_id is NOT NULL — a user's git credentials die with the account.
    user = db.relationship('User', backref=db.backref(
        'source_connections', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'provider', name='uq_source_connection_user_provider'),
    )

    # Serialization comes from SerializableMixin; these columns stay out
    # of API payloads (parity with the deleted hand-written to_dict).
    __serialize_exclude__ = ('user_id',)
