from datetime import datetime

from app import db
from app.models.mixins import uuid_pk, TimestampMixin


class ExposedService(TimestampMixin, db.Model):
    """A service on a private (NAT'd) host published to the public internet
    over a WireGuard tunnel (roadmap Phase 2). The edge runs an nginx vhost
    for ``hostname`` that proxies to the private peer's WG IP; the private
    agent forwards that to the real local service on ``port``.
    See docs/REMOTE_ACCESS_ROADMAP.md.
    """
    __tablename__ = 'exposed_services'

    id = uuid_pk()
    tunnel_id = db.Column(db.String(36), db.ForeignKey('tunnels.id'), nullable=False, index=True)

    hostname = db.Column(db.String(255), nullable=False)   # e.g. jellyfin.example.com
    port = db.Column(db.Integer, nullable=False)           # service port on the private host (e.g. 8096)
    nginx_site_name = db.Column(db.String(120))            # the edge vhost we created

    require_auth = db.Column(db.Boolean, default=False)
    auth_username = db.Column(db.String(100))
    ssl_enabled = db.Column(db.Boolean, default=False)

    status = db.Column(db.String(20), default='pending', index=True)  # pending / published / error
    last_error = db.Column(db.Text)


    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    tunnel = db.relationship('Tunnel',
                             backref=db.backref('exposed_services', lazy='dynamic'))

    def url(self):
        if not self.hostname:
            return None
        return ('https://' if self.ssl_enabled else 'http://') + self.hostname

    def to_dict(self):
        return {
            'id': self.id,
            'tunnel_id': self.tunnel_id,
            'hostname': self.hostname,
            'port': self.port,
            'nginx_site_name': self.nginx_site_name,
            'require_auth': self.require_auth,
            'auth_username': self.auth_username,
            'ssl_enabled': self.ssl_enabled,
            'status': self.status,
            'last_error': self.last_error,
            'url': self.url(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return '<ExposedService %s -> tunnel %s :%s>' % (self.hostname, self.tunnel_id, self.port)
