"""Plan 81 M2: DNS guarded doors, complete ledger, and restore adapter."""
import json

import pytest


class FakeRecordClient:
    def __init__(self, records=None, *, delete_result=None):
        self.records = records or {}
        self.delete_result = delete_result
        self.calls = []
        self._next_id = 1

    @staticmethod
    def _key(record_type, name):
        return record_type.upper(), name.lower().rstrip('.')

    def list_records(self, zone_id):
        return {'success': True, 'records': list(self.records.values())}

    def find_record_id(self, zone_id, record_type, name, caa=None):
        self.calls.append(('find', zone_id, record_type, name))
        row = self.records.get(self._key(record_type, name))
        return row.get('id') if row else None

    def upsert(self, zone_id, spec, record_id=None):
        self.calls.append(('upsert', zone_id, spec, record_id))
        record_id = record_id or f'R{self._next_id}'
        self._next_id += 1
        self.records[self._key(spec.record_type, spec.name)] = {
            'id': record_id,
            'type': spec.record_type,
            'name': spec.name,
            'content': spec.content,
            'ttl': spec.ttl,
            'priority': spec.priority,
            'proxied': spec.proxied,
        }
        return {'success': True, 'record_id': record_id, 'message': 'set'}

    def delete(self, zone_id, record_id=None, record_type=None, name=None):
        self.calls.append(('delete', zone_id, record_id, record_type, name))
        if self.delete_result is not None:
            return self.delete_result
        self.records.pop(self._key(record_type, name), None)
        return {'success': True, 'message': 'deleted'}


class RejectStaleIdClient(FakeRecordClient):
    """Models Cloudflare/DO: PUT to a deleted record id fails with not-found."""

    def upsert(self, zone_id, spec, record_id=None):
        live_ids = {row.get('id') for row in self.records.values()}
        if record_id is not None and record_id not in live_ids:
            self.calls.append(('stale-upsert', zone_id, spec, record_id))
            return {'success': False, 'error': 'record id not found'}
        return super().upsert(zone_id, spec, record_id=record_id)


def _config(db, provider):
    from app.models.email import DNSProviderConfig
    row = DNSProviderConfig(
        name=f'{provider}-connection', provider=provider,
        api_key='key', api_secret='secret',
    )
    db.session.add(row)
    db.session.commit()
    return row


@pytest.mark.parametrize(
    'provider', ['cloudflare', 'route53', 'digitalocean', 'godaddy'],
)
def test_provider_service_writes_all_providers_through_guarded_door(
        app, monkeypatch, provider):
    from app import db
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services import restore_point_service
    from app.services.dns_provider_service import DNSProviderService

    config = _config(db, provider)
    client = FakeRecordClient()
    scopes = []
    monkeypatch.setattr(
        DNSProviderService, 'record_client',
        classmethod(lambda cls, cfg: client),
    )
    monkeypatch.setattr(
        restore_point_service, 'auto_capture',
        lambda scope_type, scope_id, action, **kwargs:
            scopes.append((scope_type, scope_id, action)),
    )

    result = DNSProviderService.set_record(
        config.id, 'zone-1', 'MX', 'example.com', 'mail.example.com',
        ttl=120, priority=10, proxied=True,
    )

    assert result['success'] is True
    row = ManagedDnsRecord.query.one()
    assert (row.provider, row.dns_provider_config_id, row.provider_zone_id) == (
        provider, config.id, 'zone-1',
    )
    assert (row.ttl, row.priority, row.proxied) == (120, 10, True)
    assert scopes == [(
        'dns', f'{provider}:{config.id}:zone-1',
        'upsert MX example.com',
    )]


@pytest.mark.parametrize(
    'provider', ['cloudflare', 'route53', 'digitalocean', 'godaddy'],
)
def test_supported_clients_share_record_contract(provider):
    from app.services.dns import get_record_client
    from app.services.dns.base import DnsCredential

    client = get_record_client(DnsCredential(
        provider=provider, token='key', secret='secret',
    ))
    assert all(callable(getattr(client, method)) for method in (
        'list_records', 'find_record_id', 'upsert', 'delete',
    ))


def test_rrset_ownership_is_scoped_by_provider_connection(app):
    from app import db
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services.dns_ownership_service import DnsOwnershipService as O

    first = _config(db, 'cloudflare')
    second = _config(db, 'cloudflare')
    O.record_write(
        'cloudflare', 'shared-zone-id', 'A', 'WWW.Example.com.',
        provider_record_id='FIRST', content='1.1.1.1', config_id=first.id,
    )
    O.record_write(
        'cloudflare', 'shared-zone-id', 'A', 'www.example.com',
        provider_record_id='SECOND', content='2.2.2.2', config_id=second.id,
    )

    assert ManagedDnsRecord.query.count() == 2
    assert O.owns(
        'shared-zone-id', provider_record_id='FIRST',
        provider='cloudflare', config_id=first.id,
    )
    assert not O.owns(
        'shared-zone-id', provider_record_id='FIRST',
        provider='cloudflare', config_id=second.id,
    )


def test_change_log_keeps_complete_before_value(app, monkeypatch):
    from app import db
    from app.models.dns_change import DnsChange
    from app.services import restore_point_service
    from app.services.dns.base import DnsRecordSpec
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'cloudflare')
    client = FakeRecordClient()
    monkeypatch.setattr(restore_point_service, 'auto_capture', lambda *a, **k: None)
    O.guarded_upsert(
        client, provider='cloudflare', provider_zone_id='zone',
        spec=DnsRecordSpec('A', 'www.example.com', '1.1.1.1', 300,
                           priority=None, proxied=True),
        source='zone', config_id=config.id,
    )
    O.guarded_upsert(
        client, provider='cloudflare', provider_zone_id='zone',
        spec=DnsRecordSpec('A', 'www.example.com', '2.2.2.2', 60,
                           priority=None, proxied=False),
        source='zone', config_id=config.id,
    )

    change = DnsChange.query.filter_by(action='update').one()
    assert json.loads(change.before_json) == {
        'app_id': None,
        'content': '1.1.1.1',
        'name': 'www.example.com',
        'priority': None,
        'proxied': True,
        'record_type': 'A',
        'source': 'zone',
        'ttl': 300,
    }


def test_guarded_door_canonicalizes_embedded_mx_priority(app, monkeypatch):
    from app import db
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services import restore_point_service
    from app.services.dns.base import DnsRecordSpec
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'route53')
    monkeypatch.setattr(restore_point_service, 'auto_capture', lambda *a, **k: None)
    O.guarded_upsert(
        FakeRecordClient(), provider='route53', provider_zone_id='zone',
        spec=DnsRecordSpec('MX', 'example.com', '10 mail.example.com', 300),
        source='email', config_id=config.id,
    )

    row = ManagedDnsRecord.query.one()
    assert row.content == 'mail.example.com'
    assert row.priority == 10


def test_failed_delete_keeps_ownership_and_logs_preimage(app, monkeypatch):
    from app import db
    from app.models.dns_change import DnsChange
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services import restore_point_service
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'digitalocean')
    O.record_write(
        'digitalocean', 'example.com', 'MX', 'example.com',
        provider_record_id='77', content='mail.example.com', ttl=600,
        priority=10, proxied=False, source='email', config_id=config.id,
    )
    monkeypatch.setattr(restore_point_service, 'auto_capture', lambda *a, **k: None)
    result = O.guarded_delete(
        FakeRecordClient(delete_result={'success': False, 'error': 'timeout'}),
        provider='digitalocean', provider_zone_id='example.com',
        record_type='MX', name='example.com', provider_record_id='77',
        source='email', config_id=config.id,
    )

    assert result['success'] is False
    assert ManagedDnsRecord.query.filter_by(provider_record_id='77').one()
    change = DnsChange.query.filter_by(action='delete').one()
    assert change.result == 'error'
    assert json.loads(change.before_json)['priority'] == 10


def test_dns_capture_reads_managed_ledger_not_zone_mirror(app):
    from app import db
    from app.models.dns_zone import DNSRecord, DNSZone
    from app.services.dns_ownership_service import DnsOwnershipService as O
    from app.services.restore_point_adapter_dns import capture

    config = _config(db, 'cloudflare')
    zone = DNSZone(
        domain='example.com', provider='cloudflare', provider_zone_id='zone',
        dns_provider_config_id=config.id,
    )
    db.session.add(zone)
    db.session.flush()
    db.session.add(DNSRecord(
        zone_id=zone.id, record_type='A', name='foreign.example.com',
        content='9.9.9.9', ttl=60,
    ))
    db.session.commit()

    scope = f'cloudflare:{config.id}:zone'
    assert capture(scope)['records'] == []

    O.record_write(
        'cloudflare', 'zone', 'A', 'owned.example.com',
        provider_record_id='OWNED', content='1.2.3.4', ttl=120,
        priority=None, proxied=True, source='zone', config_id=config.id,
    )
    payload = capture(scope)
    assert [row['name'] for row in payload['records']] == ['owned.example.com']
    assert payload['records'][0]['ttl'] == 120
    assert payload['records'][0]['proxied'] is True


def test_dns_restore_round_trip_uses_guarded_calls(app, monkeypatch):
    from app import db
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services import restore_point_adapter_dns as adapter
    from app.services import restore_point_service
    from app.services.dns.base import DnsRecordSpec
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'cloudflare')
    client = FakeRecordClient()
    monkeypatch.setattr(restore_point_service, 'auto_capture', lambda *a, **k: None)
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    scope = f'cloudflare:{config.id}:zone'

    O.guarded_upsert(
        client, provider='cloudflare', provider_zone_id='zone',
        spec=DnsRecordSpec('A', 'www.example.com', '1.1.1.1', 300,
                           proxied=True),
        source='zone', config_id=config.id,
    )
    checkpoint = adapter.capture(scope)
    O.guarded_upsert(
        client, provider='cloudflare', provider_zone_id='zone',
        spec=DnsRecordSpec('A', 'www.example.com', '2.2.2.2', 60),
        source='zone', config_id=config.id,
    )
    O.guarded_upsert(
        client, provider='cloudflare', provider_zone_id='zone',
        spec=DnsRecordSpec('TXT', 'extra.example.com', 'remove-me', 60),
        source='zone', config_id=config.id,
    )

    result = adapter.restore(scope, checkpoint)
    assert result['success'] is True
    rows = ManagedDnsRecord.query.order_by(ManagedDnsRecord.record_type).all()
    assert [(row.record_type, row.content) for row in rows] == [
        ('A', '1.1.1.1'),
    ]
    assert rows[0].ttl == 300 and rows[0].proxied is True
    assert ('TXT', 'extra.example.com') not in client.records


def test_dns_restore_refuses_provider_only_target(app, monkeypatch):
    from app import db
    from app.services import restore_point_adapter_dns as adapter

    config = _config(db, 'cloudflare')
    client = FakeRecordClient(records={
        ('A', 'foreign.example.com'): {
            'id': 'FOREIGN', 'type': 'A', 'name': 'foreign.example.com',
            'content': '9.9.9.9', 'ttl': 300, 'priority': None,
            'proxied': False,
        },
    })
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    scope = f'cloudflare:{config.id}:zone'
    payload = {
        'provider': 'cloudflare',
        'config_id': config.id,
        'provider_zone_id': 'zone',
        'records': [{
            'record_type': 'A', 'name': 'foreign.example.com',
            'content': '1.2.3.4', 'ttl': 60, 'priority': None,
            'proxied': False, 'source': 'restore', 'app_id': None,
        }],
    }

    result = adapter.restore(scope, payload)
    assert result['success'] is False and result['conflict'] is True
    assert not any(call[0] == 'upsert' for call in client.calls)
    assert client.records[('A', 'foreign.example.com')]['content'] == '9.9.9.9'


def test_dns_validate_restore_surfaces_foreign_conflict(app, monkeypatch):
    from app import db
    from app.services import restore_point_adapter_dns as adapter

    config = _config(db, 'cloudflare')
    client = FakeRecordClient(records={
        ('A', 'foreign.example.com'): {
            'id': 'FOREIGN', 'type': 'A', 'name': 'foreign.example.com',
            'content': '9.9.9.9', 'ttl': 300, 'priority': None,
            'proxied': False,
        },
    })
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    scope = f'cloudflare:{config.id}:zone'
    payload = {
        'provider': 'cloudflare', 'config_id': config.id,
        'provider_zone_id': 'zone',
        'records': [{
            'record_type': 'A', 'name': 'foreign.example.com',
            'content': '1.2.3.4', 'ttl': 60, 'priority': None,
            'proxied': False, 'source': 'restore', 'app_id': None,
        }],
    }

    refusals = adapter.validate_restore(scope, payload, {'records': []})
    assert len(refusals) == 1
    assert 'provider-only DNS record A foreign.example.com' in refusals[0]


def test_restore_point_preview_disables_foreign_dns_restore(app, monkeypatch):
    from app import db
    from app.services import restore_point_adapter_dns as adapter
    from app.services import restore_point_service as service
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'cloudflare')
    scope = f'cloudflare:{config.id}:zone'
    O.record_write(
        'cloudflare', 'zone', 'A', 'foreign.example.com',
        provider_record_id='FORMERLY-OURS', content='1.2.3.4', ttl=60,
        source='zone', config_id=config.id,
    )
    monkeypatch.setitem(service.ADAPTERS, 'dns', adapter)
    point = service.capture('dns', scope, 'manual')
    O.record_delete(
        'zone', provider_record_id='FORMERLY-OURS', provider='cloudflare',
        config_id=config.id,
    )

    client = FakeRecordClient(records={
        ('A', 'foreign.example.com'): {
            'id': 'FOREIGN', 'type': 'A', 'name': 'foreign.example.com',
            'content': '9.9.9.9', 'ttl': 300, 'priority': None,
            'proxied': False,
        },
    })
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)

    preview = service.preview(point.id)
    assert preview['can_restore'] is False
    assert 'provider-only DNS record' in preview['refusals'][0]


def test_dns_restore_repairs_provider_when_ledger_already_matches(app, monkeypatch):
    from app import db
    from app.services import restore_point_adapter_dns as adapter
    from app.services import restore_point_service
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'cloudflare')
    client = RejectStaleIdClient()  # provider record drifted away / was deleted
    monkeypatch.setattr(restore_point_service, 'auto_capture', lambda *a, **k: None)
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    scope = f'cloudflare:{config.id}:zone'
    O.record_write(
        'cloudflare', 'zone', 'A', 'www.example.com',
        provider_record_id='STALE', content='1.1.1.1', ttl=300,
        proxied=True, source='zone', config_id=config.id,
    )
    checkpoint = adapter.capture(scope)

    result = adapter.restore(scope, checkpoint)
    assert result['success'] is True
    assert any(call[0] == 'upsert' for call in client.calls)
    assert not any(call[0] == 'stale-upsert' for call in client.calls)
    assert client.records[('A', 'www.example.com')]['content'] == '1.1.1.1'


def test_legacy_dns_attributes_remain_unknown_and_restore_refuses_to_guess(
        app, monkeypatch):
    from app import db
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services import restore_point_adapter_dns as adapter

    config = _config(db, 'cloudflare')
    db.session.add(ManagedDnsRecord(
        provider='cloudflare', dns_provider_config_id=config.id,
        provider_zone_id='zone', provider_record_id='OLD',
        record_type='A', name='legacy.example.com', content='1.2.3.4',
        ttl=None, priority=None, proxied=None, source='zone',
    ))
    db.session.commit()
    scope = f'cloudflare:{config.id}:zone'
    payload = adapter.capture(scope)
    record = payload['records'][0]
    assert record['ttl'] is None
    assert record['priority'] is None
    assert record['proxied'] is None

    client = FakeRecordClient()  # live record is also gone; no safe hydration
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    refusals = adapter.validate_restore(scope, payload, payload)
    assert any('unknown legacy TTL' in refusal for refusal in refusals)
    assert any('unknown legacy proxy state' in refusal for refusal in refusals)

    result = adapter.restore(scope, payload)
    assert result['success'] is False and result['refused'] is True
    assert not any(call[0] == 'upsert' for call in client.calls)


def test_legacy_dns_attributes_hydrate_from_live_provider(app, monkeypatch):
    from app import db
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services import restore_point_adapter_dns as adapter
    from app.services import restore_point_service

    config = _config(db, 'cloudflare')
    db.session.add(ManagedDnsRecord(
        provider='cloudflare', dns_provider_config_id=config.id,
        provider_zone_id='zone', provider_record_id='OLD',
        record_type='A', name='legacy.example.com', content='1.2.3.4',
        ttl=None, priority=None, proxied=None, source='zone',
    ))
    db.session.commit()
    scope = f'cloudflare:{config.id}:zone'
    payload = adapter.capture(scope)
    client = FakeRecordClient(records={
        ('A', 'legacy.example.com'): {
            'id': 'OLD', 'type': 'A', 'name': 'legacy.example.com',
            'content': '9.9.9.9', 'ttl': 120, 'priority': None,
            'proxied': True,
        },
    })
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    monkeypatch.setattr(restore_point_service, 'auto_capture', lambda *a, **k: None)

    assert adapter.validate_restore(scope, payload, payload) == []
    result = adapter.restore(scope, payload)
    assert result['success'] is True
    row = ManagedDnsRecord.query.one()
    assert row.ttl == 120 and row.proxied is True
    live = client.records[('A', 'legacy.example.com')]
    assert live['content'] == '1.2.3.4'
    assert live['ttl'] == 120 and live['proxied'] is True


@pytest.mark.parametrize('provider', ['route53', 'godaddy'])
def test_dns_restore_refuses_delete_of_synthetic_id_replacement(
        app, monkeypatch, provider):
    from app import db
    from app.services import restore_point_adapter_dns as adapter
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, provider)
    zone_id = 'zone'
    synthetic_id = 'A:old.example.com'
    O.record_write(
        provider, zone_id, 'A', 'old.example.com',
        provider_record_id=synthetic_id, content='1.1.1.1', ttl=300,
        proxied=False, source='zone', config_id=config.id,
    )
    client = FakeRecordClient(records={
        ('A', 'old.example.com'): {
            'id': synthetic_id, 'type': 'A', 'name': 'old.example.com',
            'content': '9.9.9.9', 'ttl': 300, 'priority': None,
            'proxied': False,
        },
    })
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    scope = f'{provider}:{config.id}:{zone_id}'
    empty_target = {
        'provider': provider, 'config_id': config.id,
        'provider_zone_id': zone_id, 'records': [],
    }

    refusals = adapter.validate_restore(scope, empty_target, empty_target)
    assert any('provider-only replacement' in item for item in refusals)
    result = adapter.restore(scope, empty_target)
    assert result['success'] is False and result['refused'] is True
    assert not any(call[0] == 'delete' for call in client.calls)


def test_synthetic_mx_encoded_priority_is_same_owned_record(app, monkeypatch):
    from app import db
    from app.services import restore_point_adapter_dns as adapter
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'route53')
    O.record_write(
        'route53', 'zone', 'MX', 'example.com',
        provider_record_id='MX:example.com', content='10 mail.example.com.',
        ttl=300, priority=None, proxied=False, source='legacy',
        config_id=config.id,
    )
    client = FakeRecordClient(records={
        ('MX', 'example.com'): {
            'id': 'MX:example.com', 'type': 'MX', 'name': 'example.com',
            'content': 'mail.example.com', 'ttl': 300, 'priority': 10,
            'proxied': False,
        },
    })
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    scope = f'route53:{config.id}:zone'
    empty_target = {
        'provider': 'route53', 'config_id': config.id,
        'provider_zone_id': 'zone', 'records': [],
    }

    assert adapter.validate_restore(scope, empty_target, empty_target) == []
    result = adapter.restore(scope, empty_target)
    assert result['success'] is True
    assert any(call[0] == 'delete' for call in client.calls)


def test_dns_restore_forgets_stale_ledger_when_provider_already_absent(
        app, monkeypatch):
    from app import db
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.services import restore_point_adapter_dns as adapter
    from app.services.dns_ownership_service import DnsOwnershipService as O

    config = _config(db, 'cloudflare')
    O.record_write(
        'cloudflare', 'zone', 'A', 'gone.example.com',
        provider_record_id='STALE', content='1.1.1.1', ttl=300,
        proxied=False, source='zone', config_id=config.id,
    )
    client = FakeRecordClient()  # compliant delete treats missing id as success
    monkeypatch.setattr(adapter, '_client_for_scope', lambda *args: client)
    scope = f'cloudflare:{config.id}:zone'
    empty_target = {
        'provider': 'cloudflare', 'config_id': config.id,
        'provider_zone_id': 'zone', 'records': [],
    }

    result = adapter.restore(scope, empty_target)
    assert result['success'] is True
    assert ManagedDnsRecord.query.count() == 0


def test_digitalocean_delete_stale_record_id_is_idempotent(monkeypatch):
    from app.services.dns.base import DnsCredential
    from app.services.dns.providers import DigitalOceanClient
    from app.services.dns import providers

    class MissingResponse:
        status_code = 404

        @staticmethod
        def json():
            return {'id': 'not_found', 'message': 'record not found'}

    monkeypatch.setattr(
        providers.requests, 'delete', lambda *a, **k: MissingResponse(),
    )
    client = DigitalOceanClient(DnsCredential(
        provider='digitalocean', token='token',
    ))
    result = client.delete('example.com', record_id='stale')
    assert result['success'] is True


@pytest.mark.parametrize('provider', ['route53', 'godaddy'])
def test_rrset_providers_detect_different_caa_as_existing(monkeypatch, provider):
    """A typed RRset PUT would replace other values, so strict guards must see it."""
    from app.services.dns.base import DnsCredential
    from app.services.dns.providers import GoDaddyClient, Route53Client
    from app.services.dns import providers

    caa = {'flags': 0, 'tag': 'issue', 'value': 'letsencrypt.org'}
    if provider == 'route53':
        class FakeBoto:
            @staticmethod
            def list_resource_record_sets(**kwargs):
                return {'ResourceRecordSets': [{
                    'Name': 'example.com.', 'Type': 'CAA', 'TTL': 300,
                    'ResourceRecords': [{'Value': '0 issue "digicert.com"'}],
                }]}

        client = Route53Client(
            DnsCredential(provider='route53'), client=FakeBoto(),
        )
    else:
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return [{
                    'type': 'CAA', 'name': '@', 'data': 'digicert.com',
                    'flags': 0, 'tag': 'issue', 'ttl': 300,
                }]

        monkeypatch.setattr(
            providers.requests, 'get', lambda *a, **k: Response(),
        )
        client = GoDaddyClient(DnsCredential(
            provider='godaddy', token='key', secret='secret',
        ))

    assert client.find_record_id(
        'example.com', 'CAA', 'example.com', caa=caa,
    ) is not None
