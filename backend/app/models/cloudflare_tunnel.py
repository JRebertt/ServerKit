from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin


class CloudflareTunnel(TimestampMixin, db.Model):
    """A Cloudflare Tunnel (cloudflared / cfd_tunnel) ServerKit created.

    Distinct from the WireGuard remote-access ``Tunnel`` model — this is a
    Cloudflare-managed tunnel that exposes a local service through Cloudflare's
    edge. Records the connector token (encrypted at rest) so the install command
    can be shown without re-fetching, and which connection owns it.
    """
    __tablename__ = 'cloudflare_tunnels'
    __table_args__ = (
        db.UniqueConstraint('account_id', 'tunnel_id', name='uq_cf_tunnel_account_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    tunnel_id = db.Column(db.String(64), nullable=False, index=True)   # Cloudflare tunnel id
    name = db.Column(db.String(128), nullable=False)
    account_id = db.Column(db.String(64), nullable=False)
    dns_provider_config_id = db.Column(
        db.Integer, db.ForeignKey('dns_provider_configs.id'), nullable=True)
    token_encrypted = db.Column(db.Text)     # cloudflared connector token (encrypted)


    def to_dict(self):
        # Never serialize the token here — it's revealed only at creation time and
        # re-fetched on demand via the install endpoint.
        return {
            'id': self.id,
            'tunnel_id': self.tunnel_id,
            'name': self.name,
            'account_id': self.account_id,
            'dns_provider_config_id': self.dns_provider_config_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
