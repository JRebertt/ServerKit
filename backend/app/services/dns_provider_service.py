"""DNS Provider service for managing DKIM/SPF/DMARC records via Cloudflare, Route53, DigitalOcean and GoDaddy."""
import logging
from typing import Dict, List, Optional

import requests

from app import db
from app.models.email import DNSProviderConfig
from app.utils.crypto import encrypt_secret, decrypt_secret_safe, is_encrypted

logger = logging.getLogger(__name__)


class DNSProviderService:
    """Service for managing DNS records via Cloudflare and Route53 APIs."""

    @classmethod
    def list_providers(cls) -> List[Dict]:
        """List all configured DNS providers (secrets masked)."""
        providers = DNSProviderConfig.query.all()
        return [p.to_dict(mask_secrets=True) for p in providers]

    @classmethod
    def get_provider(cls, provider_id: int) -> Optional[DNSProviderConfig]:
        """Get a DNS provider config by ID."""
        return DNSProviderConfig.query.get(provider_id)

    @classmethod
    def add_provider(cls, name: str, provider: str, api_key: str,
                     api_secret: str = None, api_email: str = None,
                     is_default: bool = False) -> Dict:
        """Add a new DNS provider configuration."""
        if provider not in ('cloudflare', 'route53', 'digitalocean', 'godaddy'):
            return {'success': False, 'error': 'Provider must be cloudflare, route53, digitalocean or godaddy'}
        try:
            if is_default:
                # Unset other defaults
                DNSProviderConfig.query.filter_by(is_default=True).update({'is_default': False})

            config = DNSProviderConfig(
                name=name,
                provider=provider,
                api_key=encrypt_secret(api_key) if api_key else api_key,
                api_secret=encrypt_secret(api_secret) if api_secret else api_secret,
                api_email=api_email,
                is_default=is_default,
            )
            db.session.add(config)
            db.session.commit()
            return {'success': True, 'provider': config.to_dict(), 'message': 'DNS provider added'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def remove_provider(cls, provider_id: int) -> Dict:
        """Remove a DNS provider configuration."""
        try:
            config = DNSProviderConfig.query.get(provider_id)
            if not config:
                return {'success': False, 'error': 'Provider not found'}
            db.session.delete(config)
            db.session.commit()
            return {'success': True, 'message': 'DNS provider removed'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    # ── Secret access (decrypt with plaintext fallback for legacy rows) ──

    @staticmethod
    def _api_key(config: DNSProviderConfig) -> str:
        return decrypt_secret_safe(config.api_key)

    @staticmethod
    def _api_secret(config: DNSProviderConfig) -> str:
        return decrypt_secret_safe(config.api_secret)

    @classmethod
    def decrypted_credentials(cls, config: DNSProviderConfig) -> Dict:
        """Decrypted credentials for a DNS provider — the safe way for any caller
        OUTSIDE this service to get usable creds. Never read ``config.api_key``
        directly; it's encrypted at rest."""
        return {
            'api_key': cls._api_key(config),
            'api_secret': cls._api_secret(config),
            'api_email': config.api_email,
        }

    @classmethod
    def encrypt_legacy_secrets(cls) -> int:
        """One-time, idempotent: encrypt any DNS-provider secrets still stored in
        plaintext (rows created before encryption-at-rest landed)."""
        changed = 0
        for config in DNSProviderConfig.query.all():
            dirty = False
            if config.api_key and not is_encrypted(config.api_key):
                config.api_key = encrypt_secret(config.api_key)
                dirty = True
            if config.api_secret and not is_encrypted(config.api_secret):
                config.api_secret = encrypt_secret(config.api_secret)
                dirty = True
            if dirty:
                changed += 1
        if changed:
            db.session.commit()
        return changed

    @classmethod
    def test_connection(cls, provider_id: int) -> Dict:
        """Test DNS provider API connection."""
        config = DNSProviderConfig.query.get(provider_id)
        if not config:
            return {'success': False, 'error': 'Provider not found'}

        if config.provider == 'cloudflare':
            return cls._test_cloudflare(config)
        elif config.provider == 'route53':
            return cls._test_route53(config)
        elif config.provider == 'digitalocean':
            return cls._test_digitalocean(config)
        elif config.provider == 'godaddy':
            return cls._test_godaddy(config)
        return {'success': False, 'error': 'Unknown provider'}

    @classmethod
    def list_zones(cls, provider_id: int) -> Dict:
        """List DNS zones from the provider."""
        config = DNSProviderConfig.query.get(provider_id)
        if not config:
            return {'success': False, 'error': 'Provider not found'}

        if config.provider == 'cloudflare':
            return cls._cloudflare_list_zones(config)
        elif config.provider == 'route53':
            return cls._route53_list_zones(config)
        elif config.provider == 'digitalocean':
            return cls._digitalocean_list_zones(config)
        elif config.provider == 'godaddy':
            return cls._godaddy_list_zones(config)
        return {'success': False, 'error': 'Unknown provider'}

    @classmethod
    def set_record(cls, provider_id: int, zone_id: str, record_type: str,
                   name: str, value: str, ttl: int = 3600,
                   proxied: bool = False, priority: int = None,
                   source: str = 'provider') -> Dict:
        """Create or update through the common client + ownership door."""
        config = DNSProviderConfig.query.get(provider_id)
        if not config:
            return {'success': False, 'error': 'Provider not found'}
        return cls._guarded_set_record(
            config, zone_id, record_type, name, value, ttl,
            proxied=proxied, priority=priority, source=source,
        )

    @classmethod
    def delete_record(cls, provider_id: int, zone_id: str, record_type: str, name: str) -> Dict:
        """Delete through the common client + ownership door."""
        config = DNSProviderConfig.query.get(provider_id)
        if not config:
            return {'success': False, 'error': 'Provider not found'}
        return cls._guarded_delete_record(config, zone_id, record_type, name)

    @classmethod
    def deploy_email_records(cls, provider_id: int, zone_id: str, domain: str,
                             selector: str, dkim_public_key: str,
                             server_ip: str = None) -> Dict:
        """Deploy DKIM, SPF, and DMARC records for an email domain."""
        results = {}

        # Deploy DKIM record
        dkim_name = f'{selector}._domainkey.{domain}'
        dkim_value = f'v=DKIM1; k=rsa; p={dkim_public_key}'
        results['dkim'] = cls.set_record(provider_id, zone_id, 'TXT', dkim_name, dkim_value, source='email')

        # Deploy SPF record
        spf_value = 'v=spf1 mx a ~all'
        if server_ip:
            spf_value = f'v=spf1 mx a ip4:{server_ip} ~all'
        results['spf'] = cls.set_record(provider_id, zone_id, 'TXT', domain, spf_value, source='email')

        # Deploy DMARC record
        dmarc_name = f'_dmarc.{domain}'
        dmarc_value = f'v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}; pct=100'
        results['dmarc'] = cls.set_record(provider_id, zone_id, 'TXT', dmarc_name, dmarc_value, source='email')

        # Deploy MX record
        results['mx'] = cls.set_record(provider_id, zone_id, 'MX', domain, f'10 mail.{domain}', source='email')

        all_ok = all(r.get('success') for r in results.values())
        return {
            'success': all_ok,
            'results': results,
            'message': 'All DNS records deployed' if all_ok else 'Some records failed',
        }

    @classmethod
    def find_zone_for_domain(cls, domain: str):
        """Find a connected provider + zone that authoritatively covers ``domain``.

        Picks the longest matching zone suffix across every configured provider
        (so ``blog.example.com`` matches a zone ``example.com``). Returns
        ``(config, zone_dict)`` or ``(None, None)`` when nothing manages it.
        """
        domain = (domain or '').strip().lower().rstrip('.')
        best = None  # (config, zone, zone_name_length)
        for config in DNSProviderConfig.query.all():
            zres = cls.list_zones(config.id)
            if not zres.get('success'):
                continue
            for zone in zres.get('zones', []):
                zname = (zone.get('name') or '').strip().lower().rstrip('.')
                if zname and (domain == zname or domain.endswith('.' + zname)):
                    if best is None or len(zname) > best[2]:
                        best = (config, zone, len(zname))
        return (best[0], best[1]) if best else (None, None)

    @classmethod
    def ensure_a_record(cls, domain: str, ip: str) -> Dict:
        """Upsert an ``A`` record ``domain -> ip`` via whichever connected provider
        manages the zone. Degrades to manual instructions (``created: False`` with
        the record to add) when there's no server IP, no provider, or an API error
        — so the caller can always show the user what to do.
        """
        domain = (domain or '').strip().lower().rstrip('.')
        record = {'type': 'A', 'name': domain, 'value': ip}
        if not domain:
            return {'created': False, 'reason': 'no_domain', 'record': record}
        if not ip:
            return {'created': False, 'reason': 'no_server_ip', 'record': record,
                    'message': 'Set the server public IP in Settings to auto-create DNS records.'}
        config, zone = cls.find_zone_for_domain(domain)
        if not config:
            return {'created': False, 'reason': 'no_provider', 'record': record,
                    'message': f'No connected DNS provider manages {domain} — add this record manually.'}
        res = cls.set_record(config.id, zone['id'], 'A', domain, ip, source='auto-dns')
        if res.get('success'):
            return {'created': True, 'provider': config.name, 'zone': zone.get('name'), 'record': record}
        # A foreign record we won't clobber surfaces as its own reason so the caller
        # can tell the user "you already have a record here" rather than a vague error.
        reason = 'foreign_record' if res.get('conflict') else 'api_error'
        return {'created': False, 'reason': reason, 'error': res.get('error'),
                'provider': config.name, 'record': record}

    @staticmethod
    def parse_caa_value(value: str) -> Dict:
        """Parse a BIND-style CAA value (``0 issue "letsencrypt.org"``) into the
        ``{flags, tag, value}`` object that Cloudflare/DigitalOcean expect. The
        CA value is returned unquoted. Delegates to the shared Cloudflare client
        so the CAA wire format is defined in exactly one place."""
        from app.services.dns.cloudflare import parse_caa_value as _parse
        return _parse(value)

    @classmethod
    def record_client(cls, config: DNSProviderConfig):
        """Build the normalized record client for a connected provider."""
        from app.services.dns import get_record_client
        from app.services.dns.base import DnsCredential
        return get_record_client(DnsCredential.from_provider_config(config))

    @classmethod
    def _guarded_set_record(cls, config, zone_id, record_type, name, value,
                            ttl=3600, *, proxied=False, priority=None,
                            source='provider'):
        from app.services.dns.base import DnsRecordSpec
        from app.services.dns_ownership_service import DnsOwnershipService

        spec = DnsRecordSpec(
            record_type=record_type, name=name, content=value, ttl=ttl,
            priority=priority, proxied=proxied,
        )
        try:
            result = DnsOwnershipService.guarded_upsert(
                cls.record_client(config), provider=config.provider,
                provider_zone_id=zone_id, spec=spec, source=source,
                config_id=config.id, allow_foreign=False,
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            return {'success': False, 'error': str(exc)}

        if result.get('success'):
            return {
                'success': True,
                'message': result.get(
                    'message', f'{record_type} record set for {name}',
                ),
            }
        output = {'success': False, 'error': result.get('error', 'Unknown error')}
        if result.get('conflict'):
            output['conflict'] = True
        return output

    @classmethod
    def _guarded_delete_record(cls, config, zone_id, record_type, name,
                               *, source='provider'):
        from app.services.dns_ownership_service import DnsOwnershipService
        try:
            return DnsOwnershipService.guarded_delete(
                cls.record_client(config), provider=config.provider,
                provider_zone_id=zone_id, record_type=record_type, name=name,
                source=source, config_id=config.id,
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            return {'success': False, 'error': str(exc)}

    @classmethod
    def ensure_caa_record(cls, domain: str, ca: str = 'letsencrypt.org') -> Dict:
        """Ensure a CAA record authorizing ``ca`` (default Let's Encrypt) exists at
        the apex of whichever connected provider zone covers ``domain``. CAA is
        evaluated by walking up to the zone apex, so an apex ``0 issue "<ca>"``
        record protects the domain and all subdomains.

        Idempotent (re-applying the same authorization is a harmless upsert) and
        degrades to manual instructions (``created: False`` + the record to add)
        when no connected provider manages the domain — so the caller can always
        tell the user what to do. Never raises.
        """
        domain = (domain or '').strip().lower().rstrip('.')
        value = f'0 issue "{ca}"'
        record = {'type': 'CAA', 'name': domain, 'value': value}
        if not domain:
            return {'created': False, 'reason': 'no_domain', 'record': record}
        try:
            config, zone = cls.find_zone_for_domain(domain)
        except Exception as e:  # provider listing blew up — fall back to manual
            return {'created': False, 'reason': 'api_error', 'error': str(e), 'record': record}
        if not config:
            return {'created': False, 'reason': 'no_provider', 'record': record,
                    'message': f'No connected DNS provider manages {domain} — add '
                               f'this CAA record manually: {domain} CAA {value}'}

        apex = (zone.get('name') or domain).strip().lower().rstrip('.')
        record = {'type': 'CAA', 'name': apex, 'value': value}
        res = cls.set_record(config.id, zone['id'], 'CAA', apex, value, source='caa')
        if res.get('success'):
            return {'created': True, 'provider': config.name, 'zone': apex, 'record': record}
        return {'created': False, 'reason': 'api_error', 'error': res.get('error'),
                'provider': config.name, 'record': record}

    # ── Cloudflare Implementation ──

    # The Cloudflare API calls live in the shared CloudflareClient so the
    # provider layer (here) and the zone layer (DNSZoneService) share one
    # implementation — auth, the CAA `data` wire format, and idempotent upsert
    # are defined once rather than maintained in two places.

    @classmethod
    def _cloudflare_client(cls, config: DNSProviderConfig):
        from app.services.dns import CloudflareClient
        from app.services.dns.base import DnsCredential
        return CloudflareClient(DnsCredential.from_provider_config(config))

    @classmethod
    def _test_cloudflare(cls, config: DNSProviderConfig) -> Dict:
        """Test Cloudflare API connection."""
        return cls._cloudflare_client(config).verify()

    @classmethod
    def _cloudflare_list_zones(cls, config: DNSProviderConfig) -> Dict:
        """List Cloudflare zones."""
        return cls._cloudflare_client(config).list_zones()

    @classmethod
    def _cloudflare_set_record(cls, config: DNSProviderConfig, zone_id: str,
                                record_type: str, name: str, value: str, ttl: int,
                                proxied: bool = False, priority: int = None,
                                source: str = 'provider') -> Dict:
        return cls._guarded_set_record(
            config, zone_id, record_type, name, value, ttl,
            proxied=proxied, priority=priority, source=source,
        )

    @classmethod
    def _cloudflare_delete_record(cls, config: DNSProviderConfig, zone_id: str,
                                   record_type: str, name: str) -> Dict:
        """Delete a Cloudflare DNS record ServerKit owns (by type+name); a foreign
        record with that name is left untouched."""
        return cls._guarded_delete_record(config, zone_id, record_type, name)

    @staticmethod
    def _host_relative_to_zone(name: str, zone: str) -> str:
        """Compute a record host relative to its zone (``@`` for the apex).

        ``name`` is a FQDN (e.g. ``mail.example.com``), ``zone`` the managing
        zone (e.g. ``example.com``); returns ``mail`` here, or ``@`` when the
        name *is* the apex. Used by DigitalOcean/GoDaddy which address records
        by zone + host rather than by FQDN.
        """
        name = (name or '').strip().lower().rstrip('.')
        zone = (zone or '').strip().lower().rstrip('.')
        if not zone or name == zone:
            return '@'
        if name.endswith('.' + zone):
            return name[: -len(zone) - 1]
        return name or '@'

    # ── Route53 Implementation ──

    @classmethod
    def _get_route53_client(cls, config: DNSProviderConfig):
        """Get a boto3 Route53 client."""
        try:
            import boto3
        except ImportError:
            raise RuntimeError('boto3 is required for Route53 integration. Install with: pip install boto3')

        return boto3.client(
            'route53',
            aws_access_key_id=cls._api_key(config),
            aws_secret_access_key=cls._api_secret(config),
        )

    @classmethod
    def _test_route53(cls, config: DNSProviderConfig) -> Dict:
        """Test Route53 API connection."""
        try:
            client = cls._get_route53_client(config)
            client.list_hosted_zones(MaxItems='1')
            return {'success': True, 'message': 'Route53 connection successful'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _route53_list_zones(cls, config: DNSProviderConfig) -> Dict:
        """List Route53 hosted zones."""
        try:
            client = cls._get_route53_client(config)
            resp = client.list_hosted_zones()
            zones = [
                {
                    'id': z['Id'].replace('/hostedzone/', ''),
                    'name': z['Name'].rstrip('.'),
                    'status': 'active',
                }
                for z in resp.get('HostedZones', [])
            ]
            return {'success': True, 'zones': zones}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _route53_set_record(cls, config: DNSProviderConfig, zone_id: str,
                             record_type: str, name: str, value: str, ttl: int) -> Dict:
        return cls._guarded_set_record(
            config, zone_id, record_type, name, value, ttl,
        )

    @classmethod
    def _route53_delete_record(cls, config: DNSProviderConfig, zone_id: str,
                                record_type: str, name: str) -> Dict:
        return cls._guarded_delete_record(config, zone_id, record_type, name)

    # ── DigitalOcean Implementation ──

    @classmethod
    def _digitalocean_headers(cls, config: DNSProviderConfig) -> Dict:
        """Build DigitalOcean API headers (single-token auth)."""
        return {
            'Authorization': f'Bearer {cls._api_key(config)}',
            'Content-Type': 'application/json',
        }

    @classmethod
    def _test_digitalocean(cls, config: DNSProviderConfig) -> Dict:
        """Test DigitalOcean API connection."""
        try:
            resp = requests.get(
                'https://api.digitalocean.com/v2/domains?per_page=1',
                headers=cls._digitalocean_headers(config),
                timeout=15,
            )
            if resp.status_code == 200:
                return {'success': True, 'message': 'DigitalOcean connection successful'}
            data = resp.json()
            return {'success': False, 'error': data.get('message', f'HTTP {resp.status_code}')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _digitalocean_list_zones(cls, config: DNSProviderConfig) -> Dict:
        """List DigitalOcean domains as zones (zone id == domain name)."""
        try:
            resp = requests.get(
                'https://api.digitalocean.com/v2/domains?per_page=200',
                headers=cls._digitalocean_headers(config),
                timeout=15,
            )
            data = resp.json()
            if resp.status_code != 200:
                return {'success': False, 'error': data.get('message', 'Failed to list zones')}
            zones = [{'id': d['name'], 'name': d['name'], 'status': 'active'}
                     for d in data.get('domains', [])]
            return {'success': True, 'zones': zones}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _digitalocean_set_record(cls, config: DNSProviderConfig, zone_id: str,
                                  record_type: str, name: str, value: str, ttl: int) -> Dict:
        return cls._guarded_set_record(
            config, zone_id, record_type, name, value, ttl,
        )

    @classmethod
    def _digitalocean_delete_record(cls, config: DNSProviderConfig, zone_id: str,
                                     record_type: str, name: str) -> Dict:
        return cls._guarded_delete_record(config, zone_id, record_type, name)

    # ── GoDaddy Implementation ──

    @classmethod
    def _godaddy_headers(cls, config: DNSProviderConfig) -> Dict:
        """Build GoDaddy API headers (key+secret auth)."""
        return {
            'Authorization': f'sso-key {cls._api_key(config)}:{cls._api_secret(config)}',
            'Content-Type': 'application/json',
        }

    @classmethod
    def _test_godaddy(cls, config: DNSProviderConfig) -> Dict:
        """Test GoDaddy API connection."""
        try:
            resp = requests.get(
                'https://api.godaddy.com/v1/domains?limit=1',
                headers=cls._godaddy_headers(config),
                timeout=15,
            )
            if resp.status_code == 200:
                return {'success': True, 'message': 'GoDaddy connection successful'}
            data = resp.json()
            return {'success': False, 'error': data.get('message', f'HTTP {resp.status_code}')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _godaddy_list_zones(cls, config: DNSProviderConfig) -> Dict:
        """List GoDaddy domains as zones (zone id == domain name)."""
        try:
            resp = requests.get(
                'https://api.godaddy.com/v1/domains',
                headers=cls._godaddy_headers(config),
                timeout=15,
            )
            if resp.status_code != 200:
                data = resp.json()
                return {'success': False, 'error': data.get('message', 'Failed to list zones')}
            zones = [{'id': d['domain'], 'name': d['domain'],
                      'status': d.get('status', 'active')}
                     for d in resp.json()]
            return {'success': True, 'zones': zones}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _godaddy_set_record(cls, config: DNSProviderConfig, zone_id: str,
                             record_type: str, name: str, value: str, ttl: int) -> Dict:
        return cls._guarded_set_record(
            config, zone_id, record_type, name, value, ttl,
        )

    @classmethod
    def _godaddy_delete_record(cls, config: DNSProviderConfig, zone_id: str,
                                record_type: str, name: str) -> Dict:
        return cls._guarded_delete_record(config, zone_id, record_type, name)
