"""Proving tests for Cloudflare Round 2 (plan 36): DNSSEC, Origin CA, redirect/
transform rules, the per-zone activity ledger, and token scope diagnostics.

Reconstructed after the 2026-07-08 data loss (migrations 073/074 survived; the
model/service/routes/client code + this suite did not). Mirrors the conventions of
``test_cloudflare_zone_settings.py``: Cloudflare HTTP is stubbed by monkeypatching
``requests`` on the shared client module, and the extension's ``CloudflareService``
is reached through the ``cloudflare_ops_bridge`` importlib helper.
"""
import types

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


def _make_cf_zone(domain='example.com', provider='cloudflare', zid='zoneABC', token='tok'):
    from app import db
    from app.models.dns_zone import DNSZone
    zone = DNSZone(domain=domain, provider=provider, provider_zone_id=zid)
    if token:
        zone.provider_config = {'api_token': token}
    db.session.add(zone)
    db.session.commit()
    return zone


# ── DNSSEC — client ───────────────────────────────────────────────────────────

def test_client_get_dnssec(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def cap(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(method=method, url=url)
        return _Resp({'success': True, 'result': {'status': 'active'}})
    monkeypatch.setattr(cf.requests, 'request', cap)
    res = _client().get_dnssec('zoneA')
    assert res['success'] is True
    assert seen['method'] == 'GET' and seen['url'].endswith('/zones/zoneA/dnssec')


def test_client_set_dnssec_patches_status(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def cap(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(method=method, url=url, json=json)
        return _Resp({'success': True, 'result': {'status': 'pending'}})
    monkeypatch.setattr(cf.requests, 'request', cap)
    _client().set_dnssec('zoneA', 'active')
    assert seen['method'] == 'PATCH'
    assert seen['url'].endswith('/zones/zoneA/dnssec')
    assert seen['json'] == {'status': 'active'}


# ── DNSSEC — service ──────────────────────────────────────────────────────────

def test_service_get_dnssec_normalizes(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True, 'result': {
                            'status': 'active', 'ds': 'DSRECORD', 'key_tag': 42,
                            'digest_type': 2}}))
    res = CloudflareService.get_dnssec(zone.id)
    assert res['success'] is True
    assert res['dnssec']['status'] == 'active'
    assert res['dnssec']['ds'] == 'DSRECORD'
    assert res['dnssec']['key_tag'] == 42


def test_service_set_dnssec_enables_and_records(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    from app.models.cf_ops_change import CfOpsChange
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True,
                                               'result': {'status': 'pending'}}))
    res = CloudflareService.set_dnssec(zone.id, True)
    assert res['success'] is True and res['dnssec']['status'] == 'pending'
    row = CfOpsChange.query.filter_by(provider_zone_id='zoneABC', product='dnssec').first()
    assert row is not None and row.action == 'enable' and row.result == 'ok'


def test_service_set_dnssec_error_records_failure(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    from app.models.cf_ops_change import CfOpsChange
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False,
                                               'errors': [{'message': 'zone is not full'}]}))
    res = CloudflareService.set_dnssec(zone.id, True)
    assert res['success'] is False and 'not full' in res['error']
    row = CfOpsChange.query.filter_by(provider_zone_id='zoneABC', product='dnssec').first()
    assert row is not None and row.result == 'error' and 'not full' in (row.error or '')


# ── Origin CA — client ────────────────────────────────────────────────────────

def test_client_origin_ca_uses_service_key_header(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def cap(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(method=method, url=url, headers=headers, json=json)
        return _Resp({'success': True, 'result': {'id': 'c1', 'certificate': 'PEM'}})
    monkeypatch.setattr(cf.requests, 'request', cap)
    res = _client().create_origin_certificate(csr='CSR', hostnames=['a.example.com'],
                                              service_key='v1.0-SVCKEY')
    assert res['success'] is True
    assert seen['method'] == 'POST' and seen['url'].endswith('/certificates')
    assert seen['headers']['X-Auth-User-Service-Key'] == 'v1.0-SVCKEY'
    assert 'Authorization' not in seen['headers']
    assert seen['json']['csr'] == 'CSR' and seen['json']['hostnames'] == ['a.example.com']


def test_client_origin_ca_falls_back_to_token(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def cap(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(headers=headers, params=params)
        return _Resp({'success': True, 'result': []})
    monkeypatch.setattr(cf.requests, 'request', cap)
    _client().list_origin_certificates('zoneA')
    assert seen['headers']['Authorization'] == 'Bearer tok'
    assert 'X-Auth-User-Service-Key' not in seen['headers']
    assert seen['params'] == {'zone_id': 'zoneA'}


def test_client_revoke_origin_certificate(monkeypatch):
    from app.services.dns import cloudflare as cf
    seen = {}

    def cap(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(method=method, url=url)
        return _Resp({'success': True, 'result': {'id': 'c1'}})
    monkeypatch.setattr(cf.requests, 'request', cap)
    _client().revoke_origin_certificate('c1')
    assert seen['method'] == 'DELETE' and seen['url'].endswith('/certificates/c1')


# ── Origin CA — service ───────────────────────────────────────────────────────

def test_issue_origin_cert_returns_cert_and_warns_unproxied(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    from app.models.cf_ops_change import CfOpsChange
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'POST' and url.endswith('/certificates'):
            # the CSR is generated panel-side and sent; the key is NOT
            assert 'csr' in (json or {}) and 'key' not in (json or {})
            return _Resp({'success': True, 'result': {
                'id': 'cert1', 'certificate': 'CERTPEM', 'expires_on': '2027-01-01'}})
        return _Resp({'success': False})

    def get(url, headers=None, params=None, timeout=None):
        # DNS records lookup for the proxied-hostname warning: grey-cloud record
        return _Resp({'success': True, 'result': [
            {'id': 'r', 'type': 'A', 'name': 'app.example.com',
             'content': '1.2.3.4', 'proxied': False}]})
    monkeypatch.setattr(cf.requests, 'request', req)
    monkeypatch.setattr(cf.requests, 'get', get)

    res = CloudflareService.issue_origin_certificate(
        zone.id, ['app.example.com'], validity_days=5475, install=False)
    assert res['success'] is True
    assert res['certificate'] == 'CERTPEM' and res['certificate_id'] == 'cert1'
    assert res['proxy_only'] is True
    assert any('not proxied' in w for w in res['warnings'])
    row = CfOpsChange.query.filter_by(provider_zone_id='zoneABC', product='origin_ca').first()
    assert row is not None and row.action == 'issue' and row.result == 'ok'


def test_issue_origin_cert_validates_hostnames(app):
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.issue_origin_certificate(zone.id, [], install=False)


def test_issue_origin_cert_validates_validity(app):
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.issue_origin_certificate(
            zone.id, ['a.example.com'], validity_days=999, install=False)


def test_issue_origin_cert_scope_error_raises_400_not_502(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False, 'errors': [
                            {'message': 'You do not have permission to use Origin CA'}]}))
    with pytest.raises(CloudflareError):
        CloudflareService.issue_origin_certificate(
            zone.id, ['a.example.com'], install=False)


def test_list_origin_certificates_maps(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True, 'result': [
                            {'id': 'c1', 'hostnames': ['a.example.com'],
                             'expires_on': '2027-01-01', 'requested_validity': 5475}]}))
    res = CloudflareService.list_origin_certificates(zone.id)
    assert res['success'] is True and res['proxy_only'] is True
    assert res['certificates'][0]['id'] == 'c1'
    assert res['certificates'][0]['hostnames'] == ['a.example.com']


def test_list_origin_certificates_scope_error_raises(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False, 'errors': [
                            {'message': 'Authentication error'}]}))
    with pytest.raises(CloudflareError):
        CloudflareService.list_origin_certificates(zone.id)


def test_revoke_origin_certificate_records(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    from app.models.cf_ops_change import CfOpsChange
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True, 'result': {'id': 'c1'}}))
    res = CloudflareService.revoke_origin_certificate(zone.id, 'c1')
    assert res['success'] is True and res['certificate_id'] == 'c1'
    row = CfOpsChange.query.filter_by(provider_zone_id='zoneABC', product='origin_ca',
                                      action='revoke').first()
    assert row is not None and row.result == 'ok'


def test_install_origin_cert_uses_upload_seam(app, monkeypatch):
    from app.services import advanced_ssl_service as adv
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    captured = {}

    def fake_upload(domain, cert_pem, key_pem, chain_pem=None):
        captured.update(domain=domain, cert=cert_pem, key=key_pem)
        return {'domain': domain, 'cert_path': f'/etc/ssl/serverkit/{domain}/cert.pem',
                'key_path': f'/etc/ssl/serverkit/{domain}/key.pem'}
    monkeypatch.setattr(adv.AdvancedSSLService, 'upload_custom_cert',
                        staticmethod(fake_upload))
    out = CloudflareService._install_origin_cert(['app.example.com'], 'CERTPEM', 'KEYPEM')
    assert out['success'] is True
    assert captured['domain'] == 'app.example.com'
    assert captured['cert'] == 'CERTPEM' and captured['key'] == 'KEYPEM'


# ── SSL list: custom certs surfaced with Origin CA badge ──────────────────────

def _write_origin_cert(directory, domain):
    import os
    from datetime import datetime, timedelta
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'CloudFlare, Inc.'),
        x509.NameAttribute(NameOID.COMMON_NAME, 'CloudFlare Origin SSL Certificate Authority'),
    ])
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)])
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow() - timedelta(days=1))
            .not_valid_after(datetime.utcnow() + timedelta(days=365))
            .sign(key, hashes.SHA256()))
    cert_dir = os.path.join(directory, domain)
    os.makedirs(cert_dir, exist_ok=True)
    with open(os.path.join(cert_dir, 'cert.pem'), 'wb') as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))


def test_ssl_list_certificates_includes_origin_ca_badge(app, monkeypatch, tmp_path):
    from app.services import ssl_service as sslmod
    _write_origin_cert(str(tmp_path), 'app.example.com')
    monkeypatch.setattr(sslmod.SSLService, 'SERVERKIT_CERTS_DIR', str(tmp_path))
    # Force the certbot branch to yield nothing so only the serverkit walk runs.
    monkeypatch.setattr(sslmod, 'run_privileged',
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout='', stderr=''))
    certs = sslmod.SSLService.list_certificates()
    origin = next((c for c in certs if c.get('name') == 'app.example.com'), None)
    assert origin is not None
    assert origin['source'] == 'custom'
    assert origin['badge'] == 'Origin CA (proxy-only)'


# ── Redirect + Transform rules ────────────────────────────────────────────────

def test_rules_unknown_slug_raises(app):
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.list_rules(zone.id, 'bogus')


def test_rules_list_empty_when_no_ruleset(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda method, url, **k:
                            _Resp({'success': True, 'result': []})
                            if url.endswith('/rulesets') else _Resp({'success': False}))
    res = CloudflareService.list_rules(zone.id, 'redirect')
    assert res['success'] is True and res['ruleset_id'] is None and res['rules'] == []
    assert any(p['key'] == 'force_www' for p in res['presets'])


def test_rules_add_creates_phase_ruleset(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    seen = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/rulesets'):
            return _Resp({'success': True, 'result': []})
        if method == 'PUT' and url.endswith('/phases/http_request_dynamic_redirect/entrypoint'):
            seen.update(json=json)
            return _Resp({'success': True, 'result': {'id': 'rsNew'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.add_rule(zone.id, 'redirect', description='d',
                                     expression='(http.host eq "example.com")',
                                     action='redirect')
    assert res['success'] is True
    assert seen['json']['rules'][0]['action'] == 'redirect'


def test_rules_add_rejects_bad_action(app):
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.add_rule(zone.id, 'redirect', description='d',
                                   expression='x', action='block')


def test_rules_preset_force_www_builds_expression(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    from app.models.cf_ops_change import CfOpsChange
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    seen = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/rulesets'):
            return _Resp({'success': True, 'result': [
                {'id': 'rs1', 'phase': 'http_request_dynamic_redirect', 'kind': 'zone'}]})
        if method == 'POST' and url.endswith('/rulesets/rs1/rules'):
            seen.update(json=json)
            return _Resp({'success': True, 'result': {'id': 'rs1'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.apply_rule_preset(zone.id, 'redirect', 'force_www')
    assert res['success'] is True
    assert 'http.host eq "example.com"' in seen['json']['expression']
    assert seen['json']['action'] == 'redirect'
    assert 'www.example.com' in seen['json']['action_parameters']['from_value']['target_url']['expression']
    row = CfOpsChange.query.filter_by(provider_zone_id='zoneABC', product='redirect').first()
    assert row is not None and row.action == 'add-rule'


def test_rules_preset_transform_strip_tracking(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    seen = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'GET' and url.endswith('/rulesets'):
            return _Resp({'success': True, 'result': []})
        if method == 'PUT' and url.endswith('/phases/http_request_transform/entrypoint'):
            seen.update(json=json)
            return _Resp({'success': True, 'result': {'id': 'rsT'}})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.apply_rule_preset(zone.id, 'transform', 'strip_tracking')
    assert res['success'] is True
    assert seen['json']['rules'][0]['action'] == 'rewrite'
    assert 'utm_' in seen['json']['rules'][0]['action_parameters']['uri']['query']['expression']


def test_rules_update_validates_action(app):
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService, CloudflareError = _cfb.cloudflare_service(), _cfb.cloudflare_error()
    zone = _make_cf_zone()
    with pytest.raises(CloudflareError):
        CloudflareService.update_rule(zone.id, 'redirect', 'rs1', 'r1', {'action': 'block'})


def test_rules_delete_calls_delete(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    deleted = {}

    def stub(method, url, headers=None, json=None, params=None, timeout=None):
        if method == 'DELETE':
            deleted.update(url=url)
            return _Resp({'success': True})
        return _Resp({'success': False})
    monkeypatch.setattr(cf.requests, 'request', stub)
    res = CloudflareService.delete_rule(zone.id, 'transform', 'rs1', 'r1')
    assert res['success'] is True
    assert deleted['url'].endswith('/rulesets/rs1/rules/r1')


# ── Activity ledger ───────────────────────────────────────────────────────────

def test_activity_records_success_and_lists(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True,
                                               'result': {'id': 'ssl', 'value': 'strict'}}))
    CloudflareService.update_setting(zone.id, 'ssl', 'strict')
    res = CloudflareService.list_activity(zone.id)
    assert res['success'] is True
    assert any(c['product'] == 'settings' and c['action'] == 'update'
               for c in res['changes'])


def test_activity_records_failure_row(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': False,
                                               'errors': [{'message': 'nope'}]}))
    CloudflareService.update_setting(zone.id, 'ssl', 'strict')
    res = CloudflareService.list_activity(zone.id, result='error')
    assert any(c['result'] == 'error' and c['product'] == 'settings'
               for c in res['changes'])


def test_activity_filters_by_product(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()
    monkeypatch.setattr(cf.requests, 'request',
                        lambda *a, **k: _Resp({'success': True, 'result': {}}))
    CloudflareService.update_setting(zone.id, 'ssl', 'strict')
    CloudflareService.set_dnssec(zone.id, True)
    res = CloudflareService.list_activity(zone.id, product='dnssec')
    assert res['changes'] and all(c['product'] == 'dnssec' for c in res['changes'])


# ── Scope diagnostics ─────────────────────────────────────────────────────────

def test_scope_check_classifies_per_product(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        # account resolution
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': True, 'result': {'account': {'id': 'acct1'}}})
        if url.endswith('/zones/zoneABC/settings'):
            return _Resp({'success': True, 'result': []})
        if url.endswith('/zones/zoneABC/dnssec'):
            return _Resp({'success': False, 'errors': [{'message': 'permission denied'}]})
        if url.endswith('/zones/zoneABC/rulesets'):
            return _Resp({'success': True, 'result': []})
        if url.endswith('/certificates'):
            return _Resp({'success': True, 'result': []})
        if url.endswith('/accounts/acct1/workers/scripts'):
            return _Resp({'success': True, 'result': []})
        if url.endswith('/accounts/acct1/cfd_tunnel'):
            return _Resp({'success': False, 'errors': [{'message': 'insufficient scope'}]})
        if url.endswith('/accounts/acct1/r2/buckets'):
            return _Resp({'success': True, 'result': {'buckets': []}})
        return _Resp({'success': False, 'errors': [{'message': 'boom'}]})

    def get(url, headers=None, params=None, timeout=None):
        # list_records (dns probe) uses requests.get
        return _Resp({'success': True, 'result': []})
    monkeypatch.setattr(cf.requests, 'request', req)
    monkeypatch.setattr(cf.requests, 'get', get)

    res = CloudflareService.scope_check(zone.id)
    p = res['products']
    assert p['settings'] == 'ok'
    assert p['dns'] == 'ok'
    assert p['dnssec'] == 'missing_scope'
    assert p['waf'] == 'ok'
    assert p['tunnels'] == 'missing_scope'
    assert p['storage'] == 'ok'


def test_scope_check_account_unresolved_marks_missing(app, monkeypatch):
    from app.services.dns import cloudflare as cf
    from app.services import cloudflare_ops_bridge as _cfb
    CloudflareService = _cfb.cloudflare_service()
    zone = _make_cf_zone()

    def req(method, url, headers=None, json=None, params=None, timeout=None):
        if url.endswith('/zones/zoneABC'):
            return _Resp({'success': False, 'errors': [{'message': 'no access'}]})
        if url.endswith('/zones/zoneABC/settings'):
            return _Resp({'success': True, 'result': []})
        return _Resp({'success': True, 'result': []})

    monkeypatch.setattr(cf.requests, 'request', req)
    monkeypatch.setattr(cf.requests, 'get', lambda *a, **k: _Resp({'success': True, 'result': []}))
    res = CloudflareService.scope_check(zone.id)
    p = res['products']
    assert p['workers'] == 'missing_scope'
    assert p['tunnels'] == 'missing_scope'
    assert p['storage'] == 'missing_scope'
