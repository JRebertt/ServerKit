from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin


class ManagedDnsRecord(TimestampMixin, db.Model):
    """Ledger of DNS records ServerKit created in an external provider zone.

    The single source of truth for "we own this record". It's written whenever the
    panel creates/updates a record through a connected provider — the /dns Zones
    page, Dynamic DNS, WordPress custom-domain auto-DNS, and email — and removed on
    delete.

    The never-touch-foreign guard and the live zone mirror read from here to tell
    ServerKit's own records apart from the user's pre-existing ones (their "Maria &
    Pedro" records), which the panel must never mutate.
    """
    __tablename__ = 'managed_dns_records'

    id = db.Column(db.Integer, primary_key=True)
    dns_provider_config_id = db.Column(
        db.Integer, db.ForeignKey('dns_provider_configs.id'), nullable=True)
    provider = db.Column(db.String(64), nullable=False)              # cloudflare, ...
    provider_zone_id = db.Column(db.String(128), nullable=False, index=True)
    provider_record_id = db.Column(db.String(128), index=True)       # set once known
    record_type = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(256), nullable=False)                 # FQDN
    content = db.Column(db.Text)
    source = db.Column(db.String(40))                                # zone|ddns|preset|wordpress|email
    app_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=True)


    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'provider_zone_id': self.provider_zone_id,
            'provider_record_id': self.provider_record_id,
            'record_type': self.record_type,
            'name': self.name,
            'content': self.content,
            'source': self.source,
            'app_id': self.app_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
