"""Provider-agnostic DNS primitives shared by both Cloudflare code paths.

A single :class:`~app.services.dns.cloudflare.CloudflareClient` is driven from
*both* layers that talk to Cloudflare:

* ``DNSProviderService`` — credentials in the ``DNSProviderConfig`` table
  (email DKIM/SPF/DMARC + WordPress custom-domain auto-DNS), and
* ``DNSZoneService`` — the ``/dns`` Zones page and Dynamic DNS.

Before this, each maintained its *own* Cloudflare request/payload code, so
wire-format fixes (e.g. CAA's structured ``data`` object) had to be made twice
and drifted apart. These dataclasses are the normalized inputs both callers
build, so the API specifics live in exactly one place.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class DnsCredential:
    """Normalized DNS-provider credential, decoupled from where it's stored."""

    provider: str
    token: Optional[str] = None       # bearer token / primary API key
    email: Optional[str] = None       # set => Cloudflare global-key auth mode
    secret: Optional[str] = None      # second secret (Route53 / GoDaddy)

    @classmethod
    def from_provider_config(cls, config) -> 'DnsCredential':
        """Build from a ``DNSProviderConfig`` row, decrypting secrets at point of
        use (never read ``config.api_key`` directly — it's encrypted at rest)."""
        from app.services.dns_provider_service import DNSProviderService
        creds = DNSProviderService.decrypted_credentials(config)
        return cls(
            provider=config.provider,
            token=creds.get('api_key'),
            email=creds.get('api_email'),
            secret=creds.get('api_secret'),
        )

    @classmethod
    def cloudflare_token(cls, token: str) -> 'DnsCredential':
        """Build a scoped-token Cloudflare credential (legacy zone-config path)."""
        return cls(provider='cloudflare', token=token)


@dataclass
class DnsRecordSpec:
    """A DNS record to create/update, independent of the provider wire format."""

    record_type: str
    name: str                          # FQDN (e.g. "www.example.com" or the apex)
    content: str
    ttl: int = 3600
    priority: Optional[int] = None     # MX / SRV
    proxied: Optional[bool] = False    # Cloudflare orange-cloud; None = legacy unknown

    @classmethod
    def from_record(cls, record) -> 'DnsRecordSpec':
        """Build from a ``DNSRecord`` ORM row."""
        return cls(
            record_type=record.record_type,
            name=record.name,
            content=record.content,
            ttl=record.ttl or 3600,
            priority=record.priority,
            proxied=bool(record.proxied),
        )
