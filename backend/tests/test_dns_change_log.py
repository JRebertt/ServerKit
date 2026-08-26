"""Proving tests for the DNS change log + failure notification (Phase 2).

Every record write ServerKit sends to a connected provider is recorded at the write
choke point (guarded_upsert / guarded_delete) — successes, foreign-record refusals,
and failures — and a real failure surfaces an admin notice.
"""


class FakeClient:
    def __init__(self, existing_id=None, upsert_result=None):
        self.existing_id = existing_id
        self.upsert_result = upsert_result or {'success': True, 'record_id': 'NEW'}

    def find_record_id(self, zone_id, record_type, name, caa=None):
        return self.existing_id

    def upsert(self, zone_id, spec, record_id=None):
        return self.upsert_result

    def delete(self, zone_id, record_id=None, record_type=None, name=None):
        return {'success': True}


def _spec(rtype='A', name='www.example.com', content='1.2.3.4'):
    from app.services.dns.base import DnsRecordSpec
    return DnsRecordSpec(rtype, name, content)


# ── recording ────────────────────────────────────────────────────────────────

def test_successful_write_logs_ok(app):
    from app.services.dns_ownership_service import DnsOwnershipService as O
    from app.models.dns_change import DnsChange
    O.guarded_upsert(FakeClient(upsert_result={'success': True, 'record_id': 'R1'}),
                     provider='cloudflare', provider_zone_id='z1', spec=_spec(),
                     source='zone', config_id=7)
    row = DnsChange.query.filter_by(provider_zone_id='z1', name='www.example.com').first()
    assert row.result == 'ok' and row.action == 'create'
    assert row.provider_record_id == 'R1' and row.source == 'zone'
    assert row.dns_provider_config_id == 7


def test_foreign_conflict_is_logged(app):
    from app.services.dns_ownership_service import DnsOwnershipService as O
    from app.models.dns_change import DnsChange
    O.guarded_upsert(FakeClient(existing_id='FOREIGN'), provider='cloudflare',
                     provider_zone_id='z1', spec=_spec(name='maria.example.com'),
                     source='auto-dns', allow_foreign=False)
    row = DnsChange.query.filter_by(provider_zone_id='z1', name='maria.example.com').first()
    assert row.result == 'conflict' and row.action == 'create'


def test_failed_write_logs_error_and_notifies(app, monkeypatch):
    from app.services.dns_ownership_service import DnsOwnershipService as O
    from app.services.dns_change_service import DnsChangeService
    from app.models.dns_change import DnsChange

    notified = {'n': 0}
    monkeypatch.setattr(DnsChangeService, '_notify_failure',
                        staticmethod(lambda row: notified.update(n=notified['n'] + 1)))

    O.guarded_upsert(FakeClient(upsert_result={'success': False, 'error': 'boom'}),
                     provider='cloudflare', provider_zone_id='z1', spec=_spec(), source='zone')
    row = DnsChange.query.filter_by(provider_zone_id='z1', name='www.example.com').first()
    assert row.result == 'error' and row.error == 'boom'
    assert notified['n'] == 1


def test_delete_is_logged(app):
    from app.services.dns_ownership_service import DnsOwnershipService as O
    from app.models.dns_change import DnsChange
    O.record_write('cloudflare', 'z1', 'A', 'www.example.com',
                   provider_record_id='R1', source='zone', config_id=3)
    O.guarded_delete(FakeClient(), provider_zone_id='z1', record_type='A',
                     name='www.example.com', provider_record_id='R1', source='zone', config_id=3)
    row = DnsChange.query.filter_by(provider_zone_id='z1', action='delete').first()
    assert row is not None and row.result == 'ok' and row.dns_provider_config_id == 3


# ── listing + filtering ──────────────────────────────────────────────────────

def test_list_filters_by_config_and_result(app):
    from app.services.dns_change_service import DnsChangeService as C
    C.record(provider='cloudflare', provider_zone_id='ZA', action='create',
             record_type='A', name='a.example.com', result='ok', config_id=1)
    C.record(provider='cloudflare', provider_zone_id='ZB', action='create',
             record_type='A', name='b.example.com', result='error', error='x', config_id=2)

    assert {c.name for c in C.list(config_id=1)} == {'a.example.com'}
    assert {c.name for c in C.list(result='error')} == {'b.example.com'}
    assert {c.name for c in C.list(provider_zone_id='ZB')} == {'b.example.com'}


# ── notify failure path is best-effort ───────────────────────────────────────

def test_notify_failure_never_raises(app, monkeypatch):
    from app.services.dns_change_service import DnsChangeService

    def boom(*a, **k):
        raise RuntimeError('notify down')
    # Even if the notifier blows up, recording the change must not raise.
    monkeypatch.setattr('app.plugins_sdk.notify.send', boom, raising=False)
    row = DnsChangeService.record(provider='cloudflare', provider_zone_id='z1',
                                  action='create', record_type='A', name='x.example.com',
                                  result='error', error='whatever')
    assert row is not None and row.result == 'error'


# ── API ──────────────────────────────────────────────────────────────────────

def test_changes_endpoint_returns_feed(app, client, auth_headers):
    from app.services.dns_change_service import DnsChangeService
    DnsChangeService.record(provider='cloudflare', provider_zone_id='Z', action='create',
                            record_type='A', name='www.example.com', result='ok', config_id=5)
    resp = client.get('/api/v1/dns/changes?config_id=5', headers=auth_headers)
    assert resp.status_code == 200
    names = [c['name'] for c in resp.get_json()['changes']]
    assert 'www.example.com' in names
