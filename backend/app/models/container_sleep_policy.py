from datetime import datetime
from app import db


class ContainerSleepPolicy(db.Model):
    """Per-application auto-sleep policy: when enabled, an idle app is stopped
    after `idle_timeout_minutes` of no recorded activity, and can be woken on
    demand. One row per application."""
    __tablename__ = 'container_sleep_policies'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'),
                               nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    idle_timeout_minutes = db.Column(db.Integer, default=30, nullable=False)
    last_activity_at = db.Column(db.DateTime)
    asleep = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    application = db.relationship('Application', backref=db.backref('sleep_policy', uselist=False))

    def to_dict(self):
        return {
            'application_id': self.application_id,
            'enabled': self.enabled,
            'idle_timeout_minutes': self.idle_timeout_minutes,
            'last_activity_at': self.last_activity_at.isoformat() if self.last_activity_at else None,
            'asleep': self.asleep,
        }
