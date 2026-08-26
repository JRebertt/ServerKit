"""Proving tests for the shared Cloudflare client (DNS unification #2).

Both the provider layer (DNSProviderService) and the zone layer (DNSZoneService)
now talk to Cloudflare through ``app.services.dns.cloudflare.CloudflareClient``.
These tests pin the behavior that used to be duplicated (and had drifted):

* auth header shape — scoped token vs global key,
* CAA structured ``data`` (never a flat ``content``),
* MX priority parsed out of the value,
* idempotent upsert — PUT an existing record instead of POSTing a duplicate,
* delete by id (no lookup) vs by name (lookup-then-delete),
* and the zone path capturing ``provider_record_id`` after a create.

Requests are stubbed by monkeypatching the ``requests`` object the client
imported; ``requests`` is a shared module, so this also covers the provider
layer's delegations.
"""


class _Resp:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


def _client(token='tok', email=None):
    from app.services.dns import cloudflare as cf
    from app.services.dns.base import DnsCredential
    return cf.CloudflareClient(DnsCredential(provider='cloudflare', token=token, email=email))


# ── auth headers ─────────────────────────────────────────────────────────────

def test_headers_scoped_token_vs_global_key():
    bearer = _client(token='tok')._headers()
    assert bearer['Authorization'] == 'Bearer tok'
    assert 'X-Auth-Email' not in bearer

    gk = _client(token='globalkey', email='a@b.com')._headers()
    assert gk['X-Auth-Email'] == 'a@b.com' and gk['X-Auth-Key'] == 'globalkey'
    assert 'Authorization' not in gk


# ── payload wire format ──────────────────────────────────────────────────────

def test_payload_a_record_carries_proxied_not_data():
    from app.services.dns.base import DnsRecordSpec
    p = _client()._payload(DnsRecordSpec('A', 'www.example.com', '1.2.3.4', proxied=True))
    assert p['content'] == '1.2.3.4' and p['proxied'] is True
    assert 'data' not in p


def test_payload_caa_uses_structured_data():
    from app.services.dns.base import DnsRecordSpec
    p = _client()._payload(DnsRecordSpec('CAA', 'example.com', '0 issue "letsencrypt.org"'))
    assert p['data'] == {'flags': 0, 'tag': 'issue', 'value': 'letsencrypt.org'}
    assert 'content' not in p and 'proxied' not in p


def test_payload_mx_priority_parsed_from_value():
    from app.services.dns.base import DnsRecordSpec
    p = _client()._payload(DnsRecordSpec('MX', 'example.com', '10 mail.example.com'))
    assert p['priority'] == 10 and p['content'] == 'mail.example.com'


def test_payload_mx_explicit_priority_wins():
    from app.services.dns.base import DnsRecordSpec
    p = _client()._payload(DnsRecordSpec('MX', 'example.com', 'mail.example.com', priority=20))
    assert p['priority'] == 20 and p['content'] == 'mail.example.com'


# ── upsert (idempotent) ──────────────────────────────────────────────────────

def test_upsert_posts_when_absent(monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services.dns.base import DnsRecordSpec
    monkeypatch.setattr(cf.requests, 'get',
                        lambda url, headers=None, timeout=None: _Resp({'result': []}))
    seen = {}
    monkeypatch.setattr(cf.requests, 'post',
                        lambda url, headers=None, json=None, timeout=None:
                            (seen.update(verb='post', url=url) or
                             _Resp({'success': True, 'result': {'id': 'NEW'}})))
    monkeypatch.setattr(cf.requests, 'put',
                        lambda *a, **k: (seen.update(verb='put') or _Resp({'success': False})))

    res = _client().upsert('zoneABC', DnsRecordSpec('A', 'www.example.com', '1.2.3.4'))
    assert res['success'] is True and res['record_id'] == 'NEW'
    assert seen['verb'] == 'post' and seen['url'].endswith('/zones/zoneABC/dns_records')


def test_upsert_puts_existing_match_by_name(monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services.dns.base import DnsRecordSpec
    monkeypatch.setattr(cf.requests, 'get',
                        lambda url, headers=None, timeout=None: _Resp({'result': [{'id': 'rec1'}]}))
    seen = {}
    monkeypatch.setattr(cf.requests, 'put',
                        lambda url, headers=None, json=None, timeout=None:
                            (seen.update(url=url) or _Resp({'success': True, 'result': {'id': 'rec1'}})))
    monkeypatch.setattr(cf.requests, 'post',
                        lambda *a, **k: (seen.update(verb='post') or _Resp({'success': False})))

    res = _client().upsert('z', DnsRecordSpec('A', 'www.example.com', '5.6.7.8'))
    assert res['record_id'] == 'rec1'
    assert seen.get('verb') != 'post' and seen['url'].endswith('/rec1')


def test_upsert_by_record_id_skips_lookup(monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services.dns.base import DnsRecordSpec
    counters = {'get': 0}
    monkeypatch.setattr(cf.requests, 'get',
                        lambda *a, **k: (counters.update(get=counters['get'] + 1) or _Resp({'result': []})))
    seen = {}
    monkeypatch.setattr(cf.requests, 'put',
                        lambda url, headers=None, json=None, timeout=None:
                            (seen.update(url=url) or _Resp({'success': True, 'result': {'id': 'rid'}})))

    res = _client().upsert('z', DnsRecordSpec('A', 'www.example.com', '1.2.3.4'), record_id='rid')
    assert res['success'] is True and counters['get'] == 0
    assert seen['url'].endswith('/rid')


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_by_record_id_skips_lookup(monkeypatch):
    from app.services.dns import cloudflare as cf
    counters = {'get': 0}
    monkeypatch.setattr(cf.requests, 'get',
                        lambda *a, **k: (counters.update(get=counters['get'] + 1) or _Resp({'result': []})))
    deleted = []
    monkeypatch.setattr(cf.requests, 'delete',
                        lambda url, headers=None, timeout=None: (deleted.append(url) or _Resp({'success': True})))

    res = _client().delete('z', record_id='rid')
    assert res['success'] is True and counters['get'] == 0
    assert deleted == ['https://api.cloudflare.com/client/v4/zones/z/dns_records/rid']


def test_delete_by_name_removes_all_matches(monkeypatch):
    from app.services.dns import cloudflare as cf
    monkeypatch.setattr(cf.requests, 'get',
                        lambda url, headers=None, timeout=None: _Resp({'result': [{'id': 'a'}, {'id': 'b'}]}))
    deleted = []
    monkeypatch.setattr(cf.requests, 'delete',
                        lambda url, headers=None, timeout=None: (deleted.append(url) or _Resp({'success': True})))

    res = _client().delete('z', record_type='A', name='www.example.com')
    assert res['success'] is True and len(deleted) == 2


def test_delete_missing_is_success(monkeypatch):
    from app.services.dns import cloudflare as cf
    monkeypatch.setattr(cf.requests, 'get',
                        lambda url, headers=None, timeout=None: _Resp({'result': []}))
    monkeypatch.setattr(cf.requests, 'delete',
                        lambda *a, **k: _Resp({'success': True}))
    res = _client().delete('z', record_type='A', name='gone.example.com')
    assert res['success'] is True and 'already deleted' in res['message']


def test_delete_stale_record_id_is_idempotent(monkeypatch):
    from app.services.dns import cloudflare as cf
    monkeypatch.setattr(
        cf.requests, 'delete',
        lambda *a, **k: _Resp({
            'success': False,
            'errors': [{'code': 81044, 'message': 'DNS record does not exist'}],
        }),
    )
    res = _client().delete('z', record_id='stale')
    assert res['success'] is True


# ── zone layer regression: capture provider_record_id on create ──────────────

def test_zone_create_record_persists_provider_record_id(app, monkeypatch):
    """DNSZoneService.create_record on a Cloudflare zone must store the id Cloudflare
    returns, so later updates/deletes address the record directly."""
    from app import db
    from app.models.dns_zone import DNSZone
    from app.services.dns_zone_service import DNSZoneService
    from app.services.dns import cloudflare as cf

    zone = DNSZone(domain='example.com', provider='cloudflare', provider_zone_id='zoneABC')
    zone.provider_config = {'api_token': 'tok'}
    db.session.add(zone)
    db.session.commit()

    monkeypatch.setattr(cf.requests, 'get',
                        lambda url, headers=None, timeout=None: _Resp({'result': []}))
    monkeypatch.setattr(cf.requests, 'post',
                        lambda url, headers=None, json=None, timeout=None:
                            _Resp({'success': True, 'result': {'id': 'CFREC'}}))

    rec = DNSZoneService.create_record(
        zone.id, {'record_type': 'A', 'name': 'www.example.com', 'content': '1.2.3.4'})
    assert rec.provider_record_id == 'CFREC'
