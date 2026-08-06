"""Phase 3 proving tests — custom-domain attach + auto-DNS.

Attaching a user-owned domain auto-creates its A record via a connected DNS
provider (or returns the record to add manually), then migrates the site to it
by reusing the URL-swap tool.
"""
from app.services import wordpress_bridge


def _mk_user(db, username='owner'):
    from app.models import User
    from werkzeug.security import generate_password_hash
    u = User(email=f'{username}@test.local', username=username,
             password_hash=generate_password_hash('x'),
             role=User.ROLE_ADMIN, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def _mk_site_app(db, user_id, name='blog', port=8300, host='old.lvh.me'):
    from app.models import Application
    from app.models.domain import Domain
    a = Application(name=name, app_type='docker', user_id=user_id,
                    root_path=f'/srv/{name}', port=port)
    db.session.add(a)
    db.session.commit()
    db.session.add(Domain(name=host, is_primary=True, application_id=a.id))
    db.session.commit()
    return a


def _mk_provider(db, name='cf', provider='cloudflare'):
    from app.models.email import DNSProviderConfig
    c = DNSProviderConfig(name=name, provider=provider, api_key='k')
    db.session.add(c)
    db.session.commit()
    return c


# ── DNS zone matching + record upsert ───────────────────────────────────────

def test_find_zone_longest_suffix_match(app, monkeypatch):
    from app import db
    from app.services.dns_provider_service import DNSProviderService

    _mk_provider(db)
    monkeypatch.setattr(DNSProviderService, 'list_zones',
                        classmethod(lambda cls, pid: {'success': True, 'zones': [
                            {'id': 'z1', 'name': 'example.com'},
                            {'id': 'z2', 'name': 'sub.example.com'},
                        ]}))

    _, zone = DNSProviderService.find_zone_for_domain('blog.sub.example.com')
    assert zone['id'] == 'z2'      # longest suffix wins
    _, zone = DNSProviderService.find_zone_for_domain('blog.example.com')
    assert zone['id'] == 'z1'
    cfg, zone = DNSProviderService.find_zone_for_domain('nope.org')
    assert cfg is None and zone is None


def test_ensure_a_record_auto_creates(app, monkeypatch):
    from app import db
    from app.services.dns_provider_service import DNSProviderService

    _mk_provider(db)
    monkeypatch.setattr(DNSProviderService, 'list_zones',
                        classmethod(lambda cls, pid: {'success': True, 'zones': [{'id': 'z1', 'name': 'example.com'}]}))
    captured = {}

    def fake_set(cls, pid, zid, rtype, name, value, ttl=3600, **kwargs):
        captured.update({'zid': zid, 'rtype': rtype, 'name': name, 'value': value})
        return {'success': True}

    monkeypatch.setattr(DNSProviderService, 'set_record', classmethod(fake_set))

    res = DNSProviderService.ensure_a_record('blog.example.com', '203.0.113.5')
    assert res['created'] is True
    assert captured == {'zid': 'z1', 'rtype': 'A', 'name': 'blog.example.com', 'value': '203.0.113.5'}


def test_ensure_a_record_no_provider_returns_manual_record(app):
    from app.services.dns_provider_service import DNSProviderService
    res = DNSProviderService.ensure_a_record('blog.example.com', '1.2.3.4')
    assert res['created'] is False
    assert res['reason'] == 'no_provider'
    assert res['record'] == {'type': 'A', 'name': 'blog.example.com', 'value': '1.2.3.4'}


def test_ensure_a_record_no_ip(app):
    from app.services.dns_provider_service import DNSProviderService
    res = DNSProviderService.ensure_a_record('blog.example.com', None)
    assert res['created'] is False
    assert res['reason'] == 'no_server_ip'


# ── attach orchestration ────────────────────────────────────────────────────

def test_attach_auto_dns_and_migrate(app, monkeypatch, wp_extension_package):
    from app import db
    from app.services.dns_provider_service import DNSProviderService
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db)
    app_row = _mk_site_app(db, user.id, host='old.lvh.me')

    monkeypatch.setattr(DNSProviderService, 'ensure_a_record',
                        classmethod(lambda cls, host, ip: {'created': True, 'provider': 'cf',
                                                           'zone': 'example.com',
                                                           'record': {'type': 'A', 'name': host, 'value': ip}}))
    captured = {}

    def fake_change(cls, a, new_url, keep_old_redirect=True):
        captured['url'] = new_url
        return {'success': True, 'new_url': new_url, 'old_url': 'http://old.lvh.me', 'replacements': 3}

    monkeypatch.setattr(WordPressService, 'change_site_url', classmethod(fake_change))

    res = WordPressService.attach_custom_domain(app_row, 'blog.example.com')
    assert res['success'] is True
    assert res['domain'] == 'blog.example.com'
    assert res['url'] == 'http://blog.example.com'
    assert captured['url'] == 'http://blog.example.com'   # migrated over http (no SSL)
    assert res['dns']['created'] is True
    assert res['warning'] is None


def test_attach_manual_dns_surfaces_record(app, monkeypatch, wp_extension_package):
    from app import db
    from app.services.dns_provider_service import DNSProviderService
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o2')
    app_row = _mk_site_app(db, user.id, name='shop', host='old.lvh.me')

    monkeypatch.setattr(DNSProviderService, 'ensure_a_record',
                        classmethod(lambda cls, host, ip: {'created': False, 'reason': 'no_provider',
                                                           'record': {'type': 'A', 'name': host, 'value': ip},
                                                           'message': 'add this record manually'}))
    monkeypatch.setattr(WordPressService, 'change_site_url',
                        classmethod(lambda cls, a, new_url, keep_old_redirect=True: {'success': True, 'new_url': new_url}))

    res = WordPressService.attach_custom_domain(app_row, 'shop.example.org')
    assert res['success'] is True
    assert res['dns']['created'] is False
    assert 'manually' in res['warning'].lower()


def test_attach_with_ssl_migrates_https(app, monkeypatch, wp_extension_package):
    from app import db
    import app.services.ssl_service as ssl_mod
    import app.services.nginx_service as nginx_mod
    from app.services.dns_provider_service import DNSProviderService
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o3')
    app_row = _mk_site_app(db, user.id, name='sec', host='old.lvh.me')

    monkeypatch.setattr(DNSProviderService, 'ensure_a_record',
                        classmethod(lambda cls, host, ip: {'created': True, 'provider': 'cf', 'record': {}}))
    monkeypatch.setattr(ssl_mod.SSLService, 'obtain_certificate',
                        classmethod(lambda cls, domains, email, **k: {'success': True, 'certificate_path': '/x'}))
    monkeypatch.setattr(nginx_mod.NginxService, 'create_site', classmethod(lambda cls, **kw: {'success': True}))
    monkeypatch.setattr(nginx_mod.NginxService, 'enable_site', classmethod(lambda cls, name: {'success': True}))
    captured = {}
    monkeypatch.setattr(WordPressService, 'change_site_url',
                        classmethod(lambda cls, a, new_url, keep_old_redirect=True: (captured.update({'url': new_url}),
                                                                                     {'success': True, 'new_url': new_url})[1]))

    res = WordPressService.attach_custom_domain(app_row, 'secure.example.com', issue_ssl=True)
    assert res['success'] is True
    assert res['ssl']['success'] is True
    assert captured['url'] == 'https://secure.example.com'   # https once the cert is obtained


def test_attach_without_migrate_sets_primary_domain(app, monkeypatch, wp_extension_package):
    from app import db
    import app.services.nginx_service as nginx_mod
    from app.models.domain import Domain
    from app.services.dns_provider_service import DNSProviderService
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o4')
    app_row = _mk_site_app(db, user.id, name='nomig', host='old.lvh.me')

    monkeypatch.setattr(DNSProviderService, 'ensure_a_record',
                        classmethod(lambda cls, host, ip: {'created': True, 'record': {}}))
    monkeypatch.setattr(nginx_mod.NginxService, 'create_site', classmethod(lambda cls, **kw: {'success': True}))
    monkeypatch.setattr(nginx_mod.NginxService, 'enable_site', classmethod(lambda cls, name: {'success': True}))
    called = {'change': False}
    monkeypatch.setattr(WordPressService, 'change_site_url',
                        classmethod(lambda cls, *a, **k: called.update({'change': True}) or {'success': True}))

    res = WordPressService.attach_custom_domain(app_row, 'nomig.example.com', migrate=False)
    assert res['success'] is True
    assert called['change'] is False
    assert Domain.query.filter_by(name='nomig.example.com', is_primary=True).first() is not None
