"""ProxyStack model — per-server managed reverse-proxy state.

ServerKit treats the reverse proxy as a first-class managed service. Host
Nginx remains the *default* (and the better choice for PHP/WordPress), but a
server may opt into a Dockerized proxy (Traefik or Caddy) deployed as a
Compose stack. This table records that choice + the on-disk compose path and
config snippet for one server. It is intentionally keyed 1:1 on server_id
(unique) — a server runs at most one managed proxy stack at a time.
"""
from datetime import datetime

from app import db
from app.models.mixins import uuid_pk, TimestampMixin
from app.models.json_column_mixin import JsonColumnMixin


class ProxyStack(TimestampMixin, JsonColumnMixin, db.Model):
    """One managed reverse-proxy stack per server."""
    __tablename__ = 'proxy_stacks'

    # Proxy types this table understands. 'nginx' means "host nginx, no
    # Docker stack" — the default. The other two deploy a Compose stack.
    PROXY_NGINX = 'nginx'
    PROXY_TRAEFIK = 'traefik'
    PROXY_CADDY = 'caddy'

    id = uuid_pk()

    # 1:1 with a server. Unique so get_or_create never creates duplicates;
    # indexed for the per-server lookup the API does on every request.
    server_id = db.Column(
        db.String(36),
        db.ForeignKey('servers.id'),
        nullable=False,
        index=True,
        unique=True,
    )

    proxy_type = db.Column(db.String(20), nullable=False, default=PROXY_NGINX)
    # stopped | running | error | unknown
    status = db.Column(db.String(20), nullable=False, default='unknown')

    # Where the compose stack lives on disk (None for host-nginx).
    compose_path = db.Column(db.String(512))

    # JSON list of docker network names the proxy attaches to.
    networks = db.Column(db.Text)

    # Operator-supplied raw config appended to the generated proxy config.
    custom_snippet = db.Column(db.Text)

    last_regenerated_at = db.Column(db.DateTime)


    def networks_list(self):
        """Decode the networks JSON column to a list (empty on missing/bad)."""
        return self._json_read('networks', [], expect=list)

    def to_dict(self):
        return {
            'id': self.id,
            'server_id': self.server_id,
            'proxy_type': self.proxy_type,
            'status': self.status,
            'compose_path': self.compose_path,
            'networks': self.networks_list(),
            'custom_snippet': self.custom_snippet,
            'last_regenerated_at': self.last_regenerated_at.isoformat() if self.last_regenerated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<ProxyStack server={self.server_id} type={self.proxy_type}>'
