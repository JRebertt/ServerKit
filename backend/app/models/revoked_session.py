"""Persistent session-family revocations (access and refresh share an id)."""
from datetime import datetime
from app import db


class RevokedSession(db.Model):
    __tablename__ = 'revoked_sessions'

    session_id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    revoked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship('User', backref=db.backref('revoked_sessions', lazy='dynamic'))
