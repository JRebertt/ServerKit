"""Proving tests — Cloudflare-aware auto-CAA on certificate issuance.

When a cert is issued for a domain whose zone is managed by a connected DNS
provider, ServerKit auto-creates a ``CAA 0 issue "letsencrypt.org"`` record at
the zone apex so issuance is pinned to our CA and CAA scanners are satisfied.
The Cloudflare API needs a *structured* ``data`` object for CAA (not the flat
``content`` string used by A/CNAME/TXT), which these tests pin down.
"""


def _mk_cloudflare_provider(db, api_key='tok'):
    from app.models.email import DNSProviderConfig
    c = DNSProviderConfig(name='cf', provider='cloudflare', api_key=api_key)
    db.session.add(c)
    db.session.commit()
    return c


class _Resp:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


# ── pure parsing ────────────────────────────────────────────────────────────

def test_parse_caa_value():
    from app.services.dns_provider_service import DNSProviderService as S
    assert S.parse_caa_value('0 issue "letsencrypt.org"') == {
        'flags': 0, 'tag': 'issue', 'value': 'letsencrypt.org'}
    assert S.parse_caa_value('128 issuewild "pki.goog"') == {
        'flags': 128, 'tag': 'issuewild', 'value': 'pki.goog'}
    assert S.parse_caa_value('0 iodef "mailto:a@b.com"') == {
        'flags': 0, 'tag': 'iodef', 'value': 'mailto:a@b.com'}


# ── ensure_caa_record ───────────────────────────────────────────────────────

def test_ensure_caa_record_no_provider_degrades(app):
    """With no connected provider, degrade to manual instructions (never raise)."""
    from app.services.dns_provider_service import DNSProviderService as S
    r = S.ensure_caa_record('panel.example.com')
    assert r['created'] is False and r['reason'] == 'no_provider'
    assert r['record'] == {'type': 'CAA', 'name': 'panel.example.com',
                           'value': '0 issue "letsencrypt.org"'}
    assert 'manually' in r['message']


def test_ensure_caa_record_writes_at_zone_apex(app, monkeypatch):
    """CAA is placed at the (lower-cased) zone apex, covering all subdomains."""
    from app.services.dns_provider_service import DNSProviderService as S
    calls = {}
    monkeypatch.setattr(S, 'find_zone_for_domain', classmethod(
        lambda cls, d: (type('C', (), {'id': 1, 'name': 'cf'})(),
                        {'id': 'zoneABC', 'name': 'Example.COM'})))
    monkeypatch.setattr(S, 'set_record', classmethod(
        lambda cls, pid, zid, rtype, name, value, ttl=3600, **kw:
            (calls.update(zid=zid, rtype=rtype, name=name, value=value) or {'success': True})))

    r = S.ensure_caa_record('panel.example.com')
    assert r['created'] is True and r['zone'] == 'example.com'
    assert calls == {'zid': 'zoneABC', 'rtype': 'CAA',
                     'name': 'example.com', 'value': '0 issue "letsencrypt.org"'}


# ── Cloudflare wire format (the actual bug this feature fixes) ───────────────

def test_cloudflare_caa_uses_structured_data(app, monkeypatch):
    """A CAA record must POST a `data` object to Cloudflare, never `content`."""
    from app import db
    from app.services import dns_provider_service as dps
    cfg = _mk_cloudflare_provider(db)

    captured = {}
    monkeypatch.setattr(dps.requests, 'get',
                        lambda url, headers=None, timeout=None: _Resp({'result': []}))

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['json'] = json
        return _Resp({'success': True})
    monkeypatch.setattr(dps.requests, 'post', fake_post)

    res = dps.DNSProviderService.set_record(
        cfg.id, 'zoneABC', 'CAA', 'example.com', '0 issue "letsencrypt.org"')
    assert res['success'] is True
    assert captured['json']['type'] == 'CAA'
    assert 'content' not in captured['json']
    assert captured['json']['data'] == {'flags': 0, 'tag': 'issue', 'value': 'letsencrypt.org'}


def test_cloudflare_caa_does_not_clobber_other_ca(app, monkeypatch):
    """An existing CAA for a *different* CA must be left alone (POST a new one),
    not overwritten via PUT."""
    from app import db
    from app.services import dns_provider_service as dps
    cfg = _mk_cloudflare_provider(db)

    existing = {'result': [{'id': 'rec1', 'data': {'tag': 'issue', 'value': 'digicert.com'}}]}
    monkeypatch.setattr(dps.requests, 'get',
                        lambda url, headers=None, timeout=None: _Resp(existing))
    verb = {}
    monkeypatch.setattr(dps.requests, 'post',
                        lambda url, headers=None, json=None, timeout=None:
                            (verb.update(m='post') or _Resp({'success': True})))
    monkeypatch.setattr(dps.requests, 'put',
                        lambda url, headers=None, json=None, timeout=None:
                            (verb.update(m='put') or _Resp({'success': True})))

    dps.DNSProviderService.set_record(
        cfg.id, 'z', 'CAA', 'example.com', '0 issue "letsencrypt.org"')
    assert verb.get('m') == 'post'  # created alongside, did not PUT over digicert


# ── cert issuance hook ──────────────────────────────────────────────────────

def _skip_nginx_preflight(monkeypatch):
    """Wave through obtain_certificate's nginx-plugin preflight.

    These tests are about the CAA hook, not about the preflight (which has its
    own coverage in test_ssl_certbot_resolution.py). They mock run_privileged
    to simulate a successful certbot, but the preflight probes the real host
    for an nginx binary and an enabled certbot nginx plugin — neither of which
    exists on a dev box or CI runner — so without this it short-circuits and
    the certbot run under test never happens.
    """
    from app.services.ssl_service import SSLService
    monkeypatch.setattr(SSLService, '_preflight_nginx_plugin',
                        classmethod(lambda cls, certbot: None))


def test_obtain_certificate_invokes_caa_hook(app, monkeypatch):
    """A successful certbot run triggers ensure_caa_record and surfaces its result."""
    from app.services.ssl_service import SSLService
    from app.services.dns_provider_service import DNSProviderService

    _skip_nginx_preflight(monkeypatch)
    monkeypatch.setattr(SSLService, 'is_certbot_installed', classmethod(lambda cls: True))
    monkeypatch.setattr('app.services.ssl_service.run_privileged',
                        lambda *a, **k: type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})())
    sentinel = {'created': True, 'provider': 'cf', 'zone': 'example.com'}
    monkeypatch.setattr(DNSProviderService, 'ensure_caa_record',
                        classmethod(lambda cls, domain, ca='letsencrypt.org': sentinel))

    res = SSLService.obtain_certificate(['example.com'], 'admin@example.com')
    assert res['success'] is True
    assert res['caa'] == sentinel


def test_obtain_certificate_caa_failure_is_non_fatal(app, monkeypatch):
    """A CAA hiccup must never fail an otherwise-successful certificate."""
    from app.services.ssl_service import SSLService
    from app.services.dns_provider_service import DNSProviderService

    _skip_nginx_preflight(monkeypatch)
    monkeypatch.setattr(SSLService, 'is_certbot_installed', classmethod(lambda cls: True))
    monkeypatch.setattr('app.services.ssl_service.run_privileged',
                        lambda *a, **k: type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})())

    def boom(cls, domain, ca='letsencrypt.org'):
        raise RuntimeError('cloudflare down')
    monkeypatch.setattr(DNSProviderService, 'ensure_caa_record', classmethod(boom))

    res = SSLService.obtain_certificate(['example.com'], 'admin@example.com')
    assert res['success'] is True
    assert res['caa']['created'] is False and 'cloudflare down' in res['caa']['error']
