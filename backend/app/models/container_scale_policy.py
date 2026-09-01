from datetime import datetime
from app import db


class ContainerScalePolicy(db.Model):
    """Per-application horizontal auto-scaling policy. When enabled, the named
    compose service is scaled between min/max replicas based on average CPU,
    with a cooldown between actions. Requires a scale-capable service (no fixed
    host port or container_name). One row per application."""
    __tablename__ = 'container_scale_policies'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'),
                               nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    service_name = db.Column(db.String(100))         # compose service to scale
    min_replicas = db.Column(db.Integer, default=1, nullable=False)
    max_replicas = db.Column(db.Integer, default=3, nullable=False)
    cpu_high_percent = db.Column(db.Integer, default=75, nullable=False)
    cpu_low_percent = db.Column(db.Integer, default=25, nullable=False)
    cooldown_seconds = db.Column(db.Integer, default=300, nullable=False)
    current_replicas = db.Column(db.Integer, default=1, nullable=False)
    last_scaled_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    application = db.relationship('Application', backref=db.backref('scale_policy', uselist=False))

    def to_dict(self):
        return {
            'application_id': self.application_id,
            'enabled': self.enabled,
            'service_name': self.service_name,
            'min_replicas': self.min_replicas,
            'max_replicas': self.max_replicas,
            'cpu_high_percent': self.cpu_high_percent,
            'cpu_low_percent': self.cpu_low_percent,
            'cooldown_seconds': self.cooldown_seconds,
            'current_replicas': self.current_replicas,
            'last_scaled_at': self.last_scaled_at.isoformat() if self.last_scaled_at else None,
        }
