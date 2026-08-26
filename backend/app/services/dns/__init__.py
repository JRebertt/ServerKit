"""Shared, provider-agnostic DNS client layer.

Both ``DNSProviderService`` (provider/credentials layer) and ``DNSZoneService``
(zone/records layer) build a :class:`DnsCredential` + :class:`DnsRecordSpec` and
talk to a provider through :func:`get_client`, so the API wire format for a given
provider lives in exactly one module.
"""
from app.services.dns.base import DnsCredential, DnsRecordSpec
from app.services.dns.cloudflare import CloudflareClient
from app.services.dns.providers import (
    DigitalOceanClient,
    GoDaddyClient,
    Route53Client,
    get_record_client,
)

__all__ = [
    'DnsCredential', 'DnsRecordSpec', 'CloudflareClient', 'Route53Client',
    'DigitalOceanClient', 'GoDaddyClient', 'get_client', 'get_record_client',
]


def get_client(credential: DnsCredential):
    """Return the API client for ``credential.provider``.

    This legacy factory remains Cloudflare-only because DNS cutover currently
    has Cloudflare-specific snapshot semantics. Record-management callers use
    ``get_record_client`` for the four-provider contract.
    """
    if credential.provider == 'cloudflare':
        return CloudflareClient(credential)
    raise ValueError(f'No shared DNS client for provider: {credential.provider}')
