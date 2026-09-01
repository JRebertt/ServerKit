"""Base domains that managed sites can be published under.

ServerKit publishes a managed site at ``<slug>.<base_domain>``. Historically
there was exactly one base domain (the ``sites_base_domain`` setting); this
model lets an operator register several — e.g. ``example.com`` and ``toto.com`` —
each with its own DNS provider connection and wildcard certificate, so a new
site can choose which one to live under (``a.example.com`` vs ``a.toto.com``).

Exactly one row is the default, used when a create request doesn't name a base.
On upgrade the legacy single setting is lazily materialised into the default row
(see SiteBaseDomainService.ensure_seeded); a fresh/dev install with no rows keeps
falling back to the ``sites_base_domain`` setting / ``SITES_BASE_DOMAIN`` config.
"""
from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin


class SiteBaseDomain(TimestampMixin, db.Model):
    __tablename__ = 'site_base_domains'

    DNS_MODES = ('wildcard', 'per-site')

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(253), nullable=False, unique=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    # wildcard: one *.<domain> record covers every site; per-site: each site gets
    # its own A record auto-created via the provider.
    dns_mode = db.Column(db.String(20), nullable=False, default='wildcard')
    # True once a *.<domain> wildcard certificate exists, so its sites serve TLS.
    https_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # The connected DNS provider that owns this domain's zone — used to create the
    # wildcard record and issue the wildcard cert. Nullable: a domain may be
    # registered before HTTPS is set up, or have its DNS managed manually.
    dns_provider_config_id = db.Column(
        db.Integer,
        db.ForeignKey('dns_provider_configs.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'domain': self.domain,
            'is_default': self.is_default,
            'dns_mode': self.dns_mode if self.dns_mode in self.DNS_MODES else 'wildcard',
            'https_enabled': bool(self.https_enabled),
            'dns_provider_config_id': self.dns_provider_config_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
