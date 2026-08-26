"""Provider-agnostic record clients for Route53, DigitalOcean, and GoDaddy.

Each client exposes the same record surface as :class:`CloudflareClient`:
``list_records``, ``find_record_id``, ``upsert``, and ``delete``.  The provider
connection service and restore-point replay can therefore use the ownership
door without knowing provider wire formats.
"""
import logging
from typing import Optional

import requests

from app.services.dns.base import DnsCredential, DnsRecordSpec
from app.services.dns.cloudflare import parse_caa_value

logger = logging.getLogger(__name__)


def _fqdn(value: str) -> str:
    return (value or '').strip().lower().rstrip('.')


def _relative_name(name: str, zone: str) -> str:
    name = _fqdn(name)
    zone = _fqdn(zone)
    if not zone or name == zone:
        return '@'
    if name.endswith('.' + zone):
        return name[:-len(zone) - 1]
    return name or '@'


def _absolute_name(name: str, zone: str) -> str:
    name = (name or '@').strip().rstrip('.')
    zone = _fqdn(zone)
    if name in ('', '@'):
        return zone
    if _fqdn(name) == zone or _fqdn(name).endswith('.' + zone):
        return _fqdn(name)
    return f'{name}.{zone}'.lower()


def _split_priority(spec: DnsRecordSpec):
    content = spec.content
    priority = spec.priority
    if spec.record_type in ('MX', 'SRV') and priority is None:
        head, _, rest = (content or '').strip().partition(' ')
        if head.isdigit() and rest.strip():
            priority, content = int(head), rest.strip()
    return content, priority


def _http_error(response, data, fallback='Provider request failed'):
    if isinstance(data, dict):
        return data.get('message') or data.get('error') or fallback
    return f'HTTP {getattr(response, "status_code", "?")}: {fallback}'


class Route53Client:
    """Normalized Route53 RRset client."""

    def __init__(self, credential: DnsCredential, client=None):
        self.cred = credential
        self._boto_client = client

    def _client(self):
        if self._boto_client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    'boto3 is required for Route53 integration. '
                    'Install with: pip install boto3'
                ) from exc
            self._boto_client = boto3.client(
                'route53',
                aws_access_key_id=self.cred.token,
                aws_secret_access_key=self.cred.secret,
            )
        return self._boto_client

    @staticmethod
    def _record_id(record_type: str, name: str) -> str:
        # Route53 has no per-record id. Its mutation identity is the RRset key.
        return f'{record_type.upper()}:{_fqdn(name)}'

    @staticmethod
    def _content(record_type, value):
        value = str(value or '')
        if record_type == 'TXT' and len(value) >= 2 and value[0] == value[-1] == '"':
            return value[1:-1]
        return value.rstrip('.') if record_type in ('CNAME', 'NS', 'PTR') else value

    def list_records(self, zone_id: str) -> dict:
        try:
            out = []
            kwargs = {'HostedZoneId': zone_id}
            while True:
                response = self._client().list_resource_record_sets(**kwargs)
                for rrset in response.get('ResourceRecordSets', []):
                    record_type = rrset.get('Type')
                    name = _fqdn(rrset.get('Name'))
                    ttl = rrset.get('TTL')
                    values = rrset.get('ResourceRecords') or []
                    for value in values:
                        content = self._content(record_type, value.get('Value'))
                        priority = None
                        if record_type in ('MX', 'SRV'):
                            head, _, rest = content.partition(' ')
                            if head.isdigit() and rest:
                                priority, content = int(head), rest
                        out.append({
                            'id': self._record_id(record_type, name),
                            'type': record_type,
                            'name': name,
                            'content': content,
                            'ttl': ttl,
                            'priority': priority,
                            'proxied': False,
                        })
                if not response.get('IsTruncated'):
                    break
                kwargs.update({
                    'StartRecordName': response['NextRecordName'],
                    'StartRecordType': response['NextRecordType'],
                })
                if response.get('NextRecordIdentifier'):
                    kwargs['StartRecordIdentifier'] = response['NextRecordIdentifier']
            return {'success': True, 'records': out}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def _find_rrset(self, zone_id, record_type, name):
        fqdn = f'{_fqdn(name)}.'
        response = self._client().list_resource_record_sets(
            HostedZoneId=zone_id,
            StartRecordName=fqdn,
            StartRecordType=record_type,
            MaxItems='1',
        )
        records = response.get('ResourceRecordSets', [])
        return next((
            item for item in records
            if _fqdn(item.get('Name')) == _fqdn(name)
            and item.get('Type') == record_type
        ), None)

    def find_record_id(self, zone_id: str, record_type: str, name: str,
                       caa: dict = None):
        del caa  # Route53 identity is the whole name+type RRset.
        rrset = self._find_rrset(zone_id, record_type, name)
        if rrset is None:
            return None
        return self._record_id(record_type, name)

    @staticmethod
    def _rrset(spec: DnsRecordSpec):
        content, priority = _split_priority(spec)
        if spec.record_type == 'TXT':
            content = f'"{content}"'
        elif spec.record_type == 'CAA':
            caa = parse_caa_value(content)
            content = f'{caa["flags"]} {caa["tag"]} "{caa["value"]}"'
        elif priority is not None:
            content = f'{priority} {content}'
        return {
            'Name': f'{_fqdn(spec.name)}.',
            'Type': spec.record_type,
            'TTL': spec.ttl,
            'ResourceRecords': [{'Value': content}],
        }

    def upsert(self, zone_id: str, spec: DnsRecordSpec,
               record_id: str = None) -> dict:
        try:
            self._client().change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': self._rrset(spec),
                }]},
            )
            return {
                'success': True,
                'record_id': self._record_id(spec.record_type, spec.name),
                'message': f'{spec.record_type} record set for {spec.name}',
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def delete(self, zone_id: str, *, record_id: str = None,
               record_type: str = None, name: str = None) -> dict:
        try:
            rrset = self._find_rrset(zone_id, record_type, name)
            if rrset is None:
                return {'success': True, 'message': 'Record not found (already deleted)'}
            self._client().change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={'Changes': [{
                    'Action': 'DELETE',
                    'ResourceRecordSet': rrset,
                }]},
            )
            return {'success': True, 'message': f'{record_type} record deleted for {name}'}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}


class DigitalOceanClient:
    """Normalized DigitalOcean domain-record client."""

    API_BASE = 'https://api.digitalocean.com/v2'

    def __init__(self, credential: DnsCredential):
        self.cred = credential

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.cred.token or ""}',
            'Content-Type': 'application/json',
        }

    def _raw_records(self, zone_id, record_type=None):
        params = '?per_page=200'
        if record_type:
            params += f'&type={record_type}'
        response = requests.get(
            f'{self.API_BASE}/domains/{zone_id}/records{params}',
            headers=self._headers(), timeout=15,
        )
        data = response.json()
        if response.status_code != 200:
            raise RuntimeError(_http_error(response, data))
        return data.get('domain_records', [])

    @staticmethod
    def _normalize(zone_id, record):
        content = record.get('data', '')
        priority = record.get('priority')
        if record.get('type') == 'CAA':
            content = f'{record.get("flags", 0)} {record.get("tag", "issue")} "{content}"'
        return {
            'id': str(record.get('id')),
            'type': record.get('type'),
            'name': _absolute_name(record.get('name'), zone_id),
            'content': content,
            'ttl': record.get('ttl'),
            'priority': priority,
            'proxied': False,
        }

    def list_records(self, zone_id: str) -> dict:
        try:
            return {
                'success': True,
                'records': [self._normalize(zone_id, row) for row in self._raw_records(zone_id)],
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def find_record_id(self, zone_id: str, record_type: str, name: str,
                       caa: dict = None):
        host = _relative_name(name, zone_id)
        for row in self._raw_records(zone_id, record_type):
            if row.get('name') != host:
                continue
            if caa is not None and (
                row.get('tag') != caa['tag']
                or str(row.get('data', '')).strip('"').rstrip('.').lower()
                   != caa['value'].rstrip('.').lower()
            ):
                continue
            return str(row.get('id'))
        return None

    @staticmethod
    def _payload(zone_id, spec):
        content, priority = _split_priority(spec)
        payload = {
            'type': spec.record_type,
            'name': _relative_name(spec.name, zone_id),
            'data': content,
            'ttl': spec.ttl,
        }
        if priority is not None:
            payload['priority'] = priority
        if spec.record_type == 'CAA':
            caa = parse_caa_value(content)
            payload.update(data=caa['value'], flags=caa['flags'], tag=caa['tag'])
        return payload

    def upsert(self, zone_id: str, spec: DnsRecordSpec,
               record_id: str = None) -> dict:
        try:
            base = f'{self.API_BASE}/domains/{zone_id}/records'
            if record_id is None:
                caa = parse_caa_value(spec.content) if spec.record_type == 'CAA' else None
                record_id = self.find_record_id(
                    zone_id, spec.record_type, spec.name, caa=caa,
                )
            payload = self._payload(zone_id, spec)
            if record_id:
                response = requests.put(
                    f'{base}/{record_id}', headers=self._headers(),
                    json=payload, timeout=15,
                )
            else:
                response = requests.post(
                    base, headers=self._headers(), json=payload, timeout=15,
                )
            data = response.json()
            if response.status_code not in (200, 201):
                return {'success': False, 'error': _http_error(response, data)}
            result_id = (data.get('domain_record') or {}).get('id') or record_id
            return {
                'success': True,
                'record_id': str(result_id) if result_id is not None else None,
                'message': f'{spec.record_type} record set for {spec.name}',
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def delete(self, zone_id: str, *, record_id: str = None,
               record_type: str = None, name: str = None) -> dict:
        try:
            ids = [record_id] if record_id else []
            if not ids:
                host = _relative_name(name, zone_id)
                ids = [
                    str(row['id']) for row in self._raw_records(zone_id, record_type)
                    if row.get('name') == host
                ]
            if not ids:
                return {'success': True, 'message': 'Record not found (already deleted)'}
            for item_id in ids:
                response = requests.delete(
                    f'{self.API_BASE}/domains/{zone_id}/records/{item_id}',
                    headers=self._headers(), timeout=15,
                )
                if response.status_code == 404:
                    continue
                if response.status_code not in (200, 204):
                    try:
                        data = response.json()
                    except ValueError:
                        data = {}
                    return {'success': False, 'error': _http_error(response, data)}
            return {'success': True, 'message': f'{record_type} record deleted for {name}'}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}


class GoDaddyClient:
    """Normalized GoDaddy record-set client."""

    API_BASE = 'https://api.godaddy.com/v1'

    def __init__(self, credential: DnsCredential):
        self.cred = credential

    def _headers(self):
        return {
            'Authorization': f'sso-key {self.cred.token or ""}:{self.cred.secret or ""}',
            'Content-Type': 'application/json',
        }

    @staticmethod
    def _record_id(record_type, name):
        return f'{record_type.upper()}:{name}'

    def _raw_records(self, zone_id, record_type=None, name=None):
        url = f'{self.API_BASE}/domains/{zone_id}/records'
        if record_type:
            url += f'/{record_type}'
            if name is not None:
                url += f'/{name}'
        response = requests.get(url, headers=self._headers(), timeout=15)
        data = response.json()
        if response.status_code != 200:
            raise RuntimeError(_http_error(response, data))
        return data or []

    @staticmethod
    def _normalize(zone_id, row):
        content = row.get('data', '')
        priority = row.get('priority')
        if row.get('type') == 'CAA':
            content = f'{row.get("flags", 0)} {row.get("tag", "issue")} "{content}"'
        return {
            'id': GoDaddyClient._record_id(row.get('type'), row.get('name')),
            'type': row.get('type'),
            'name': _absolute_name(row.get('name'), zone_id),
            'content': content,
            'ttl': row.get('ttl'),
            'priority': priority,
            'proxied': False,
        }

    def list_records(self, zone_id: str) -> dict:
        try:
            return {
                'success': True,
                'records': [self._normalize(zone_id, row) for row in self._raw_records(zone_id)],
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def find_record_id(self, zone_id: str, record_type: str, name: str,
                       caa: dict = None):
        del caa  # GoDaddy PUT addresses/replaces the whole name+type RRset.
        host = _relative_name(name, zone_id)
        rows = self._raw_records(zone_id, record_type, host)
        return self._record_id(record_type, host) if rows else None

    @staticmethod
    def _payload(spec):
        content, priority = _split_priority(spec)
        row = {'data': content, 'ttl': spec.ttl}
        if priority is not None:
            row['priority'] = priority
        if spec.record_type == 'CAA':
            caa = parse_caa_value(content)
            row.update(data=caa['value'], flags=caa['flags'], tag=caa['tag'])
        return row

    def upsert(self, zone_id: str, spec: DnsRecordSpec,
               record_id: str = None) -> dict:
        try:
            host = _relative_name(spec.name, zone_id)
            response = requests.put(
                f'{self.API_BASE}/domains/{zone_id}/records/{spec.record_type}/{host}',
                headers=self._headers(), json=[self._payload(spec)], timeout=15,
            )
            if response.status_code not in (200, 201, 204):
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                return {'success': False, 'error': _http_error(response, data)}
            return {
                'success': True,
                'record_id': self._record_id(spec.record_type, host),
                'message': f'{spec.record_type} record set for {spec.name}',
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def delete(self, zone_id: str, *, record_id: str = None,
               record_type: str = None, name: str = None) -> dict:
        try:
            host = _relative_name(name, zone_id)
            response = requests.delete(
                f'{self.API_BASE}/domains/{zone_id}/records/{record_type}/{host}',
                headers=self._headers(), timeout=15,
            )
            if response.status_code in (200, 204, 404):
                message = ('Record not found (already deleted)'
                           if response.status_code == 404
                           else f'{record_type} record deleted for {name}')
                return {'success': True, 'message': message}
            try:
                data = response.json()
            except ValueError:
                data = {}
            return {'success': False, 'error': _http_error(response, data)}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}


def get_record_client(credential: DnsCredential, *, route53_client=None):
    """Build a normalized record client for every supported provider."""
    provider = (credential.provider or '').lower()
    if provider == 'cloudflare':
        from app.services.dns.cloudflare import CloudflareClient
        return CloudflareClient(credential)
    if provider == 'route53':
        return Route53Client(credential, client=route53_client)
    if provider == 'digitalocean':
        return DigitalOceanClient(credential)
    if provider == 'godaddy':
        return GoDaddyClient(credential)
    raise ValueError(f'No DNS record client for provider: {credential.provider}')
