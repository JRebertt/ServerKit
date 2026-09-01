"""Per-domain daily bandwidth rollups.

One row per (domain, day) aggregated from the nginx access logs by
``BandwidthService.aggregate`` (job kind ``bandwidth.aggregate``). ``app_id``
is a best-effort attribution via the Domain/Application tables and is
nullable so traffic to domains the panel no longer manages is still recorded.
"""
from datetime import datetime

from app import db


class SiteBandwidthDaily(db.Model):
    __tablename__ = 'site_bandwidth_daily'
    __table_args__ = (
        db.UniqueConstraint('domain', 'day', name='uq_site_bandwidth_domain_day'),
    )

    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(
        db.Integer,
        db.ForeignKey('applications.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    domain = db.Column(db.String(255), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False, index=True)
    bytes_sent = db.Column(db.BigInteger, nullable=False, default=0)
    requests = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'app_id': self.app_id,
            'domain': self.domain,
            'day': self.day.isoformat() if self.day else None,
            'bytes_sent': int(self.bytes_sent or 0),
            'requests': int(self.requests or 0),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<SiteBandwidthDaily {self.domain} {self.day}>'
