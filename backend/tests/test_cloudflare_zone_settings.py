"""Proving tests for Cloudflare zone settings (Phase 1 of the Cloudflare ops roadmap).

Covers the generic v4 ``request`` helper on the shared client (envelope
normalization), the zone-settings methods, and ``CloudflareService`` orchestration
— credential/zone resolution guards, settings indexing, and the recommended
hardening preset's per-setting reporting.

Cloudflare HTTP is stubbed by monkeypatching ``requests.request`` on the client's
imported ``requests`` module (the generic helper uses ``requests.request``).
"""
import pytest

# The zone-ops backend lives in the standalone serverkit-cloudflare-ops repo
# since the plan 52 Ph2 cutover; every test here runs against the extension
# mounted from the sibling checkout (module skips when it is absent).
@pytest.fixture(autouse=True)
def _mounted_cf(cf_extension):
    yield



class _Resp:
    def __init__(self, js, status=200):
        self._js = js
        self.status_code = status

    def json(self):
        return self._js


def _client(token='tok'):
    from app.services.dns import cloudflare as cf
    from app.services.dns.base import DnsCredential
    return cf.CloudflareClient(DnsCredential(provider='cloudflare', token=token))


# ── generic request() envelope normalization ─────────────────────────────────

def test_request_passes_success_through(monkeypatch):
    from app.services.dns import cloudflare as cf
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True,
                                               'result': [{'id': 'ssl', 'value': 'full'}]}))
    res = _client().get_zone_settings('zoneA')
    assert res['success'] is True and res['result'][0]['id'] == 'ssl'


def test_request_extracts_first_error(monkeypatch):
    from app.services.dns import cloudflare as cf
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False,
                                               'errors': [{'message': 'Invalid zone'}]}))
    res = _client().get_zone_setting('zoneA', 'ssl')
    assert res['success'] is False and res['error'] == 'Invalid zone'


def test_request_handles_transport_error(monkeypatch):
    from app.services.dns import cloudflare as cf

    def boom(*a, **k):
        raise RuntimeError('network down')
    monkeypatch.setattr(cf.requests, 'request', boom)
    res = _client().get_zone_settings('zoneA')
    assert res['success'] is False and 'network down' in res['error']


def test_request_handles_non_json(monkeypatch):
    from app.services.dns import cloudflare as cf

    class _Bad(_Resp):
        def json(self):
            raise ValueError('no json')
    monkeypatch.setattr(cf.requests, 'request', lambda *a, **k: _Bad({}, status=502))
    res = _client().get_zone_settings('zoneA')
    assert res['success'] is False and '502' in res['error']


def test_update_zone_setting_patches_value(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def capture(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(method=method, url=url, json=json)
        return _Resp({'success': True, 'result': {'id': 'ssl', 'value': 'strict'}})
    monkeypatch.setattr(cf.requests, 'request', capture)
    res = _client().update_zone_setting('zoneA', 'ssl', 'strict')
    assert res['success'] is True
    assert seen['method'] == 'PATCH'
    assert seen['url'].endswith('/zones/zoneA/settings/ssl')
    assert seen['json'] == {'value': 'strict'}


# ── service: zone resolution guards ──────────────────────────────────────────

def _make_cf_zone(domain='example.com', provider='cloudflare', zid='zoneABC', token='tok'):
    from app import db
    from app.models.dns_zone import DNSZone
    zone = DNSZone(domain=domain, provider=provider, provider_zone_id=zid)
    if token:
        zone.provider_config = {'api_token': token}
    db.session.add(zone)
    db.session.commit()
    return zone


def test_service_rejects_non_cloudflare_zone(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone(provider='manual', token=None)
    with pytest.raises(CloudflareError):
        CloudflareService.get_settings(zone.id)


def test_service_rejects_missing_zone(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    with pytest.raises(CloudflareError):
        CloudflareService.get_settings(99999)


def test_service_rejects_zone_without_provider_zone_id(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone(zid=None)
    with pytest.raises(CloudflareError):
        CloudflareService.get_settings(zone.id)


# ── service: settings + preset ───────────────────────────────────────────────

def test_service_get_settings_indexes_by_id(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True, 'result': [
                            {'id': 'ssl', 'value': 'full', 'editable': True},
                            {'id': 'brotli', 'value': 'on', 'editable': True}]}))
    res = CloudflareService.get_settings(zone.id)
    assert res['success'] is True
    assert res['settings']['ssl']['value'] == 'full'
    assert res['zone']['domain'] == 'example.com'
    assert any(g['key'] == 'ssl' for g in res['groups'])


def test_service_update_setting_surfaces_provider_error(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False,
                                               'errors': [{'message': 'not editable on plan'}]}))
    res = CloudflareService.update_setting(zone.id, 'http3', 'on')
    assert res['success'] is False and 'not editable' in res['error']


def test_service_apply_preset_reports_each(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()

    def capture(method, url, headers=None, json=None, params=None, timeout=None):
        ok = not url.endswith('/http3')   # fail one to prove partial reporting
        return _Resp({'success': ok,
                      'errors': [] if ok else [{'message': 'not on plan'}],
                      'result': {}})
    monkeypatch.setattr(cf.requests, 'request', capture)
    res = CloudflareService.apply_recommended(zone.id)
    assert res['total'] == len(CloudflareService.RECOMMENDED_PRESET)
    assert res['applied'] == res['total'] - 1
    assert any(r['setting'] == 'http3' and not r['success'] for r in res['results'])


# ── cache purge (Phase 2) ────────────────────────────────────────────────────

def test_client_purge_cache_posts_payload(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def capture(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(method=method, url=url, json=json)
        return _Resp({'success': True, 'result': {'id': 'zoneA'}})
    monkeypatch.setattr(cf.requests, 'request', capture)
    res = _client().purge_cache('zoneA', {'purge_everything': True})
    assert res['success'] is True
    assert seen['method'] == 'POST'
    assert seen['url'].endswith('/zones/zoneA/purge_cache')
    assert seen['json'] == {'purge_everything': True}


def test_service_purge_everything(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    sent = {}
    monkeypatch.setattr(cf.requests, 'request',
                        lambda method, url, headers=None, json=None, params=None, timeout=None:
                            (sent.update(json=json) or _Resp({'success': True})))
    res = CloudflareService.purge_cache(zone.id, everything=True)
    assert res['success'] is True
    assert sent['json'] == {'purge_everything': True}


def test_service_purge_files_caps_at_30(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    sent = {}
    monkeypatch.setattr(cf.requests, 'request',
                        lambda method, url, headers=None, json=None, params=None, timeout=None:
                            (sent.update(json=json) or _Resp({'success': True})))
    urls = [f'https://example.com/{i}.css' for i in range(50)]
    res = CloudflareService.purge_cache(zone.id, files=urls)
    assert res['success'] is True
    assert len(sent['json']['files']) == 30


def test_service_purge_nothing_raises(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.purge_cache(zone.id)


def test_service_purge_surfaces_provider_error(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False,
                                               'errors': [{'message': 'rate limited'}]}))
    res = CloudflareService.purge_cache(zone.id, everything=True)
    assert res['success'] is False and 'rate limited' in res['error']


# ── WAF custom rules (Phase 3) ───────────────────────────────────────────────

def test_waf_list_no_ruleset_is_empty(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda method, url, **k:
                            _Resp({'success': True, 'result': []})
                            if url.endswith('/rulesets') else _Resp({'success': False}))
    res = CloudflareService.list_waf_rules(zone.id)
    assert res['success'] is True
    assert res['ruleset_id'] is None and res['rules'] == []
    assert any(p['key'] == 'lock_wp_admin' for p in res['presets'])


def test_waf_list_surfaces_listing_error(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False,
                                               'errors': [{'message': 'token lacks WAF scope'}]}))
    res = CloudflareService.list_waf_rules(zone.id)
    assert res['success'] is False and 'WAF scope' in res['error']


def test_waf_list_with_ruleset(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/rulesets'):
            return _Resp({'success': True, 'result': [
                {'id': 'rs1', 'phase': 'http_request_firewall_custom', 'kind': 'zone'}]})
        if url.endswith('/rulesets/rs1'):
            return _Resp({'success': True, 'result': {'id': 'rs1', 'rules': [
                {'id': 'r1', 'description': 'd', 'expression': 'e',
                 'action': 'block', 'enabled': True}]}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.list_waf_rules(zone.id)
    assert res['ruleset_id'] == 'rs1'
    assert res['rules'][0]['id'] == 'r1' and res['rules'][0]['action'] == 'block'


def test_waf_add_creates_phase_ruleset_when_absent(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    seen = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/rulesets'):
            return _Resp({'success': True, 'result': []})
        if method == 'PUT' and url.endswith('/phases/http_request_firewall_custom/entrypoint'):
            seen.update(json=json)
            return _Resp({'success': True, 'result': {'id': 'rsNew'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.add_waf_rule(zone.id, description='d',
                                         expression='ip.src eq 1.1.1.1', action='block')
    assert res['success'] is True
    assert seen['json']['rules'][0]['action'] == 'block'


def test_waf_add_posts_to_existing_ruleset(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    seen = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/rulesets'):
            return _Resp({'success': True, 'result': [
                {'id': 'rs1', 'phase': 'http_request_firewall_custom', 'kind': 'zone'}]})
        if method == 'POST' and url.endswith('/rulesets/rs1/rules'):
            seen.update(json=json, url=url)
            return _Resp({'success': True, 'result': {'id': 'rs1'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.add_waf_rule(zone.id, description='d',
                                         expression='x', action='log')
    assert res['success'] is True and seen['json']['action'] == 'log'


def test_waf_add_rejects_bad_action(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.add_waf_rule(zone.id, description='d', expression='x', action='nuke')


def test_waf_preset_lock_requires_valid_ip(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.apply_waf_preset(zone.id, 'lock_wp_admin', {'ip': 'not-an-ip'})


def test_waf_preset_lock_builds_safe_expression(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    seen = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/rulesets'):
            return _Resp({'success': True, 'result': [
                {'id': 'rs1', 'phase': 'http_request_firewall_custom', 'kind': 'zone'}]})
        if method == 'POST' and url.endswith('/rulesets/rs1/rules'):
            seen.update(json=json)
            return _Resp({'success': True, 'result': {'id': 'rs1'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.apply_waf_preset(zone.id, 'lock_wp_admin', {'ip': '203.0.113.7'})
    assert res['success'] is True
    assert 'ip.src ne 203.0.113.7' in seen['json']['expression']
    assert seen['json']['action'] == 'block'


def test_waf_update_validates_action(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.update_waf_rule(zone.id, 'rs1', 'r1', {'action': 'nuke'})


def test_waf_delete_calls_delete(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    deleted = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'DELETE':
            deleted.update(url=url)
            return _Resp({'success': True})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.delete_waf_rule(zone.id, 'rs1', 'r1')
    assert res['success'] is True
    assert deleted['url'].endswith('/rulesets/rs1/rules/r1')


# ── Workers (Phase 4) ────────────────────────────────────────────────────────

def test_upload_worker_module_is_multipart(monkeypatch):
    import json as _json
    from app.services.dns import cloudflare as cf
    seen = {}

    def put(url, headers=None, files=None, timeout=None):
        seen.update(url=url, headers=headers, files=files)
        return _Resp({'success': True, 'result': {'id': 'w'}})
    monkeypatch.setattr(cf.requests, 'put', put)
    res = _client().upload_worker_module('acct1', 'w', 'CODE', '2025-01-01')
    assert res['success'] is True
    assert seen['url'].endswith('/accounts/acct1/workers/scripts/w')
    # multipart upload must NOT carry a JSON Content-Type (requests sets the boundary)
    assert 'Content-Type' not in seen['headers']
    meta = _json.loads(seen['files']['metadata'][1])
    assert meta['main_module'] == 'worker.js' and meta['compatibility_date'] == '2025-01-01'
    assert 'worker.js' in seen['files']


def test_deploy_worker_validates_name(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.deploy_worker(zone.id, name='Bad Name!', code='x')


def test_deploy_worker_records_source(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    from app.models.cloudflare_worker import CloudflareWorker
    zone = _make_cf_zone()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        return _Resp({'success': False})

    def put(url, headers=None, files=None, timeout=None):
        return _Resp({'success': True, 'result': {'id': 'my-worker'}})
    monkeypatch.setattr(cf.requests, 'request', req)
    monkeypatch.setattr(cf.requests, 'put', put)

    res = CloudflareService.deploy_worker(zone.id, name='My-Worker', code='export default {}')
    assert res['success'] is True
    assert res['worker']['name'] == 'my-worker'          # lowercased
    rec = CloudflareWorker.query.filter_by(account_id='acct1', name='my-worker').first()
    assert rec is not None and rec.source == 'export default {}'


def test_list_workers_flags_managed(app, monkeypatch):
    from app import db
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    from app.models.cloudflare_worker import CloudflareWorker
    zone = _make_cf_zone()
    db.session.add(CloudflareWorker(account_id='acct1', name='managed-one', source='x'))
    db.session.commit()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if url.endswith('/accounts/acct1/workers/scripts'):
            return _Resp({'success': True, 'result': [
                {'id': 'managed-one', 'modified_on': '2026-01-01'},
                {'id': 'foreign', 'modified_on': '2026-01-02'}]})
        if url.endswith('/zones/zoneABC/workers/routes'):
            return _Resp({'success': True, 'result': [
                {'id': 'rt1', 'pattern': 'example.com/*', 'script': 'managed-one'}]})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.list_workers(zone.id)
    assert res['account_id'] == 'acct1'
    by_name = {w['name']: w for w in res['workers']}
    assert by_name['managed-one']['managed'] is True
    assert by_name['foreign']['managed'] is False
    assert res['routes'][0]['pattern'] == 'example.com/*'


def test_delete_worker_removes_local_row(app, monkeypatch):
    from app import db
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    from app.models.cloudflare_worker import CloudflareWorker
    zone = _make_cf_zone()
    db.session.add(CloudflareWorker(account_id='acct1', name='gone', source='x'))
    db.session.commit()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if method == 'DELETE' and url.endswith('/accounts/acct1/workers/scripts/gone'):
            return _Resp({'success': True})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.delete_worker(zone.id, 'gone')
    assert res['success'] is True
    assert CloudflareWorker.query.filter_by(account_id='acct1', name='gone').first() is None


# ── Tunnels (Phase 5) ────────────────────────────────────────────────────────

def test_client_list_tunnels_passes_is_deleted_false(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(params=params, url=url)
        return _Resp({'success': True, 'result': []})
    monkeypatch.setattr(cf.requests, 'request', req)
    _client().list_tunnels('acct1')
    assert seen['params'] == {'is_deleted': 'false'}
    assert seen['url'].endswith('/accounts/acct1/cfd_tunnel')


def test_client_create_tunnel_uses_cloudflare_config_src(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(json=json)
        return _Resp({'success': True, 'result': {'id': 't'}})
    monkeypatch.setattr(cf.requests, 'request', req)
    _client().create_tunnel('acct1', 'home')
    assert seen['json'] == {'name': 'home', 'config_src': 'cloudflare'}


def test_create_tunnel_requires_name(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.create_tunnel(zone.id, '   ')


def test_create_tunnel_stores_token_and_returns_install(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    from app.models.cloudflare_tunnel import CloudflareTunnel
    from app.utils.crypto import decrypt_secret_safe
    zone = _make_cf_zone()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if method == 'POST' and url.endswith('/accounts/acct1/cfd_tunnel'):
            return _Resp({'success': True, 'result': {'id': 'tun1', 'token': 'TOKEN123'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.create_tunnel(zone.id, 'home')
    assert res['success'] is True and res['token'] == 'TOKEN123'
    assert res['install'] == 'cloudflared service install TOKEN123'
    rec = CloudflareTunnel.query.filter_by(account_id='acct1', tunnel_id='tun1').first()
    assert rec is not None
    # Token stored encrypted at rest, recoverable via the safe decrypt.
    assert rec.token_encrypted != 'TOKEN123'
    assert decrypt_secret_safe(rec.token_encrypted) == 'TOKEN123'


def test_list_tunnels_flags_managed(app, monkeypatch):
    from app import db
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    from app.models.cloudflare_tunnel import CloudflareTunnel
    zone = _make_cf_zone()
    db.session.add(CloudflareTunnel(tunnel_id='tun1', name='mine', account_id='acct1'))
    db.session.commit()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if url.endswith('/accounts/acct1/cfd_tunnel'):
            return _Resp({'success': True, 'result': [
                {'id': 'tun1', 'name': 'mine', 'status': 'healthy', 'connections': [{}]},
                {'id': 'tun2', 'name': 'other', 'status': 'down'}]})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.list_tunnels(zone.id)
    by_id = {t['id']: t for t in res['tunnels']}
    assert by_id['tun1']['managed'] is True and by_id['tun1']['connections'] == 1
    assert by_id['tun2']['managed'] is False


def test_delete_tunnel_removes_local_row(app, monkeypatch):
    from app import db
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    from app.models.cloudflare_tunnel import CloudflareTunnel
    zone = _make_cf_zone()
    db.session.add(CloudflareTunnel(tunnel_id='tun1', name='mine', account_id='acct1'))
    db.session.commit()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if method == 'DELETE' and url.endswith('/accounts/acct1/cfd_tunnel/tun1'):
            return _Resp({'success': True})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.delete_tunnel(zone.id, 'tun1')
    assert res['success'] is True
    assert CloudflareTunnel.query.filter_by(account_id='acct1', tunnel_id='tun1').first() is None


def test_add_tunnel_hostname_sets_ingress_with_catchall(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    put_body = {}

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if method == 'GET' and url.endswith('/cfd_tunnel/tun1/configurations'):
            return _Resp({'success': True, 'result': {'config': {'ingress': [
                {'service': 'http_status:404'}]}}})
        if method == 'PUT' and url.endswith('/cfd_tunnel/tun1/configurations'):
            put_body.update(json or {})
            return _Resp({'success': True, 'result': {}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)
    # Isolate the ingress logic from the best-effort CNAME upsert.
    monkeypatch.setattr(CloudflareService, '_ensure_tunnel_cname',
                        lambda zone, client, hostname, tunnel_id: {'created': True, 'error': None})

    res = CloudflareService.add_tunnel_hostname(
        zone.id, 'tun1', 'App.Example.com', 'http://localhost:8080')
    assert res['success'] is True and res['dns']['created'] is True
    ingress = put_body['config']['ingress']
    assert ingress[0] == {'hostname': 'app.example.com', 'service': 'http://localhost:8080'}
    assert ingress[-1] == {'service': 'http_status:404'}   # required catch-all is last


# ── Developer platform: R2 / KV / D1 (Phase 6) ───────────────────────────────

def test_list_storage_aggregates_and_reports_errors(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if url.endswith('/r2/buckets'):
            return _Resp({'success': True, 'result': {'buckets': [
                {'name': 'assets', 'creation_date': 'x'}]}})
        if url.endswith('/storage/kv/namespaces'):
            return _Resp({'success': False, 'errors': [{'message': 'no kv scope'}]})
        if url.endswith('/d1/database'):
            return _Resp({'success': True, 'result': [{'uuid': 'db1', 'name': 'main'}]})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.list_storage(zone.id)
    assert res['success'] is True and res['account_id'] == 'acct1'
    assert res['r2'][0]['name'] == 'assets'
    assert res['d1'][0]['name'] == 'main'
    # A per-product scope error degrades that product only — not the whole tab.
    assert res['errors']['kv'] == 'no kv scope' and res['kv'] == []


def test_create_r2_bucket_validates_name(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.create_r2_bucket(zone.id, 'Bad_Bucket!')


def test_create_r2_bucket_creates(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    seen = {}

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if method == 'POST' and url.endswith('/r2/buckets'):
            seen.update(json=json)
            return _Resp({'success': True, 'result': {'name': 'my-assets'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.create_r2_bucket(zone.id, 'my-assets')
    assert res['success'] is True and res['bucket'] == 'my-assets'
    assert seen['json'] == {'name': 'my-assets'}


def test_create_kv_namespace_requires_title(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.create_kv_namespace(zone.id, '   ')


def test_create_d1_database_requires_name(app):
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.create_d1_database(zone.id, '')


def test_delete_r2_bucket_calls_delete(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb; CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    deleted = {}

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if method == 'DELETE' and url.endswith('/r2/buckets/assets'):
            deleted.update(url=url)
            return _Resp({'success': True})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', req)

    res = CloudflareService.delete_r2_bucket(zone.id, 'assets')
    assert res['success'] is True
    assert deleted['url'].endswith('/r2/buckets/assets')
