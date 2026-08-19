from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin, SerializableMixin


class CloudflareTunnel(SerializableMixin, TimestampMixin, db.Model):
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


