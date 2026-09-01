from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin


class CloudflareWorker(TimestampMixin, db.Model):
    """A Cloudflare Worker (edge script) ServerKit uploaded.

    Cloudflare is the source of truth for what's deployed; this table records the
    source we pushed (so it can be viewed and re-deployed) and which connection it
    belongs to. Keyed by ``(account_id, name)`` — a script name is unique per
    account.
    """
    __tablename__ = 'cloudflare_workers'
    __table_args__ = (
        db.UniqueConstraint('account_id', 'name', name='uq_cf_worker_account_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)   # script name
    account_id = db.Column(db.String(64), nullable=False)
    dns_provider_config_id = db.Column(
        db.Integer, db.ForeignKey('dns_provider_configs.id'), nullable=True, index=True)
    source = db.Column(db.Text)                                    # JS module we uploaded
    compatibility_date = db.Column(db.String(20))


    def to_dict(self, include_source=False):
        d = {
            'id': self.id,
            'name': self.name,
            'account_id': self.account_id,
            'dns_provider_config_id': self.dns_provider_config_id,
            'compatibility_date': self.compatibility_date,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_source:
            d['source'] = self.source
        return d
