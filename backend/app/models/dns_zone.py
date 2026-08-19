from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import TimestampMixin
import json


class DNSZone(JsonColumnMixin, TimestampMixin, db.Model):
    """DNS zone for a domain with provider integration."""
    __tablename__ = 'dns_zones'

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(256), nullable=False, unique=True)
    provider = db.Column(db.String(64))  # cloudflare, route53, digitalocean, manual
    provider_zone_id = db.Column(db.String(128))
    provider_config_json = db.Column(db.Text)  # legacy inline credentials (pre-unification)

    # Canonical credential link: the DNSProviderConfig (Settings -> Connections)
    # whose API token manages this zone. Supersedes the inline token in
    # provider_config_json; nullable so manual zones and not-yet-migrated rows work.
    dns_provider_config_id = db.Column(
        db.Integer, db.ForeignKey('dns_provider_configs.id'), nullable=True)

    status = db.Column(db.String(32), default='active')
    last_sync_at = db.Column(db.DateTime)


    records = db.relationship('DNSRecord', backref='zone', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def provider_config(self):
        return self._json_read('provider_config_json')

    @provider_config.setter
    def provider_config(self, v):
        self.provider_config_json = json.dumps(v)

    def to_dict(self):
        return {
            'id': self.id,
            'domain': self.domain,
            'provider': self.provider,
            'provider_zone_id': self.provider_zone_id,
            'dns_provider_config_id': self.dns_provider_config_id,
            'status': self.status,
            'record_count': self.records.count(),
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class DNSRecord(TimestampMixin, db.Model):
    """Individual DNS record within a zone."""
    __tablename__ = 'dns_records'

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey('dns_zones.id'), nullable=False)

    record_type = db.Column(db.String(10), nullable=False)  # A, AAAA, CNAME, MX, TXT, SRV, CAA
    name = db.Column(db.String(256), nullable=False)
    content = db.Column(db.Text, nullable=False)
    ttl = db.Column(db.Integer, default=3600)
    priority = db.Column(db.Integer)  # MX, SRV
    proxied = db.Column(db.Boolean, default=False)  # Cloudflare proxy

    provider_record_id = db.Column(db.String(128))


    def to_dict(self):
        return {
            'id': self.id,
            'zone_id': self.zone_id,
            'record_type': self.record_type,
            'name': self.name,
            'content': self.content,
            'ttl': self.ttl,
            'priority': self.priority,
            'proxied': self.proxied,
            'provider_record_id': self.provider_record_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
