"""Email bounce / complaint suppression state (plan 33 Phase 4, roadmap #24).

One row per email address that a provider reported a bounce or complaint for.
A hard-bouncing address auto-mutes after ``MUTE_THRESHOLD`` consecutive hard
bounces (a spam complaint mutes immediately); a muted address is skipped by the
bus's email channel until an admin/user unmutes it. Fed by the signed inbound
webhook (``POST /api/v1/notifications/inbound/email``).
"""
from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin


class EmailBounceState(TimestampMixin, db.Model):
    __tablename__ = 'email_bounce_state'

    KIND_BOUNCE = 'bounce'
    KIND_COMPLAINT = 'complaint'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)

    consecutive_bounces = db.Column(db.Integer, default=0, nullable=False)
    total_events = db.Column(db.Integer, default=0, nullable=False)

    muted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    muted_at = db.Column(db.DateTime, nullable=True)

    last_kind = db.Column(db.String(20), nullable=True)
    last_reason = db.Column(db.String(500), nullable=True)
    last_event_at = db.Column(db.DateTime, nullable=True)


    def to_dict(self):
        return {
            'email': self.email,
            'muted': bool(self.muted),
            'consecutive_bounces': self.consecutive_bounces or 0,
            'total_events': self.total_events or 0,
            'last_kind': self.last_kind,
            'last_reason': self.last_reason,
            'last_event_at': self.last_event_at.isoformat() if self.last_event_at else None,
            'muted_at': self.muted_at.isoformat() if self.muted_at else None,
        }

    def __repr__(self):
        return f'<EmailBounceState {self.email} muted={self.muted} n={self.consecutive_bounces}>'
