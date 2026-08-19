from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
import json


class CloudProvider(db.Model):
    """Cloud provider configuration (DigitalOcean, Hetzner, Vultr, Linode)."""
    __tablename__ = 'cloud_providers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    provider_type = db.Column(db.String(32), nullable=False)  # digitalocean, hetzner, vultr, linode
    api_key_encrypted = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    servers = db.relationship('CloudServer', backref='provider', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'provider_type': self.provider_type,
            'is_active': self.is_active,
            'server_count': self.servers.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CloudServer(JsonColumnMixin, db.Model):
    """A cloud server provisioned through ServerKit."""
    __tablename__ = 'cloud_servers'

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('cloud_providers.id'), nullable=False)
    external_id = db.Column(db.String(128))  # provider's server ID
    name = db.Column(db.String(128), nullable=False)
    hostname = db.Column(db.String(256))

    # Specs
    region = db.Column(db.String(64))
    size = db.Column(db.String(64))
    image = db.Column(db.String(128))  # OS image
    ip_address = db.Column(db.String(45))
    ipv6_address = db.Column(db.String(64))

    # Status
    STATUS_CREATING = 'creating'
    STATUS_ACTIVE = 'active'
    STATUS_OFF = 'off'
    STATUS_DESTROYED = 'destroyed'
    STATUS_ERROR = 'error'
    status = db.Column(db.String(32), default=STATUS_CREATING)

    # Cost
    monthly_cost = db.Column(db.Float, default=0)
    currency = db.Column(db.String(3), default='USD')

    # Auto-install agent
    agent_installed = db.Column(db.Boolean, default=False)

    # SSH key
    ssh_key_id = db.Column(db.String(128))

    # Metadata
    metadata_json = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    destroyed_at = db.Column(db.DateTime)

    snapshots = db.relationship('CloudSnapshot', backref='server', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def server_metadata(self):
        return self._json_read('metadata_json')

    @server_metadata.setter
    def server_metadata(self, v):
        self.metadata_json = json.dumps(v)

    def to_dict(self):
        return {
            'id': self.id,
            'provider_id': self.provider_id,
            'provider_name': self.provider.name if self.provider else None,
            'provider_type': self.provider.provider_type if self.provider else None,
            'external_id': self.external_id,
            'name': self.name,
            'hostname': self.hostname,
            'region': self.region,
            'size': self.size,
            'image': self.image,
            'ip_address': self.ip_address,
            'ipv6_address': self.ipv6_address,
            'status': self.status,
            'monthly_cost': self.monthly_cost,
            'currency': self.currency,
            'agent_installed': self.agent_installed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CloudSnapshot(db.Model):
    """Snapshot of a cloud server."""
    __tablename__ = 'cloud_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey('cloud_servers.id'), nullable=False)
    external_id = db.Column(db.String(128))
    name = db.Column(db.String(128))
    size_gb = db.Column(db.Float)
    status = db.Column(db.String(32), default='creating')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'server_id': self.server_id,
            'external_id': self.external_id,
            'name': self.name,
            'size_gb': self.size_gb,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
