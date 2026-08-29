"""Phase 5 proving tests — wildcard HTTPS for managed subdomains.

A one-time setup creates the *.<base> + <base> A records via a connected DNS
provider and issues a wildcard cert, after which managed subdomain vhosts serve
TLS from it.
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


def _mk_app(db, user_id, name='blog', port=8300, host='blog.lvh.me'):
    from app.models import Application
    from app.models.domain import Domain
    a = Application(name=name, app_type='docker', user_id=user_id, root_path=f'/srv/{name}', port=port)
    db.session.add(a)
    db.session.commit()
    db.session.add(Domain(name=host, is_primary=True, application_id=a.id))
    db.session.commit()
    return a


def _mk_provider(db, provider='cloudflare'):
    from app.models.email import DNSProviderConfig
    c = DNSProviderConfig(name='cf', provider=provider, api_key='tok', api_secret='sec')
    db.session.add(c)
    db.session.commit()
    return c


# ── SiteDomainService HTTPS helpers ─────────────────────────────────────────

def test_https_helpers(app):
    from app import db
    from app.models.system_settings import SystemSettings
    from app.services.site_domain_service import SiteDomainService

    assert SiteDomainService.https_enabled() is False
    # Testing base domain is lvh.me.
    assert SiteDomainService.covers('blog.lvh.me') is True
    assert SiteDomainService.covers('lvh.me') is True
    assert SiteDomainService.covers('other.com') is False
    fc, key = SiteDomainService.wildcard_cert_paths()
    assert fc == '/etc/letsencrypt/live/lvh.me/fullchain.pem'
    assert key == '/etc/letsencrypt/live/lvh.me/privkey.pem'

    SystemSettings.set('sites_https_enabled', True, value_type='boolean')
    db.session.commit()
    assert SiteDomainService.https_enabled() is True


# ── nginx SSL config generation (pure) ──────────────────────────────────────

def test_with_ssl_builds_redirect_and_443():
    from app.services.nginx_service import NginxService
    http = NginxService.DOCKER_SITE_TEMPLATE.format(name='blog', domains='blog.lvh.me', port=8300)
    out = NginxService._with_ssl(http, 'blog.lvh.me', '/c/fullchain.pem', '/c/privkey.pem')
    assert 'return 301 https://$server_name$request_uri;' in out   # HTTP->HTTPS redirect
    assert 'listen 443 ssl http2;' in out                          # app block now on 443
    assert 'ssl_certificate /c/fullchain.pem;' in out
    assert 'ssl_certificate_key /c/privkey.pem;' in out
    assert 'proxy_pass http://127.0.0.1:8300;' in out              # proxy preserved
    assert out.count('listen 80;') == 1                            # only the redirect block on :80


# ── issue_wildcard_cert command construction ────────────────────────────────

def test_issue_wildcard_cert_route53(monkeypatch):
    import app.services.advanced_ssl_service as mod
    from app.utils.system import PackageManager
    from app.services.advanced_ssl_service import AdvancedSSLService

    monkeypatch.setattr(PackageManager, 'is_available', staticmethod(lambda: False))
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = 'Congratulations'
        stderr = ''

    def fake_run(cmd, **kw):
        captured['cmd'] = list(cmd)
        captured['kw'] = kw
        return FakeProc()

    # certbot writes /etc/letsencrypt as root — the privileged door is the
    # contract, and its returncode decides success.
    monkeypatch.setattr(mod, 'run_privileged', fake_run)

    res = AdvancedSSLService.issue_wildcard_cert('example.com', 'route53',
                                                 {'api_key': 'AK', 'api_secret': 'SK'},
                                                 email='ops@example.com')
    assert res['success'] is True
    assert res['certificate_path'] == '/etc/letsencrypt/live/example.com/fullchain.pem'
    cmd = captured['cmd']
    assert '--dns-route53' in cmd
    assert 'example.com' in cmd and '*.example.com' in cmd
    assert '--email' in cmd and 'ops@example.com' in cmd
    # sudo's env_reset would strip a plain env= kwarg, so the AWS credentials
    # travel as `env A=B` argv entries in front of certbot instead.
    assert cmd[0] == 'env'
    assert 'AWS_ACCESS_KEY_ID=AK' in cmd
    assert 'AWS_SECRET_ACCESS_KEY=SK' in cmd
    assert 'env' not in captured['kw']


# ── setup orchestration ─────────────────────────────────────────────────────

def test_setup_creates_records_issues_cert_persists(app, monkeypatch):
    from app import db
    from app.models.system_settings import SystemSettings
    from app.services.dns_provider_service import DNSProviderService
    from app.services.advanced_ssl_service import AdvancedSSLService
    from app.services.sites_https_service import SitesHttpsService
    from app.services.site_domain_service import SiteDomainService

    provider = _mk_provider(db)
    SystemSettings.set('server_public_ip', '203.0.113.9', value_type='string')
    db.session.commit()

    created = []
    monkeypatch.setattr(DNSProviderService, 'ensure_a_record',
                        classmethod(lambda cls, host, ip: (created.append(host),
                                                           {'created': True, 'record': {'name': host, 'value': ip}})[1]))
    cert_calls = {}

    def fake_cert(domain, provider_name, creds, email=None):
        cert_calls.update({'domain': domain, 'provider': provider_name, 'creds': creds, 'email': email})
        return {'success': True, 'certificate_path': f'/etc/letsencrypt/live/{domain}/fullchain.pem'}

    monkeypatch.setattr(AdvancedSSLService, 'issue_wildcard_cert', staticmethod(fake_cert))

    res = SitesHttpsService.setup(provider.id, email='ops@x.com')
    assert res['success'] is True
    assert res['https_enabled'] is True
    assert set(created) == {'*.lvh.me', 'lvh.me'}          # wildcard + apex
    assert cert_calls['domain'] == 'lvh.me'
    assert cert_calls['provider'] == 'cloudflare'
    assert cert_calls['creds'] == {'api_token': 'tok'}     # reuses the connected provider's token
    assert cert_calls['email'] == 'ops@x.com'
    assert SiteDomainService.https_enabled() is True       # persisted


def test_setup_requires_provider(app):
    from app.services.sites_https_service import SitesHttpsService
    res = SitesHttpsService.setup(None)
    assert res['success'] is False
    assert 'provider' in res['error'].lower()


def test_setup_cert_failure_does_not_enable_https(app, monkeypatch):
    from app import db
    from app.models.system_settings import SystemSettings
    from app.services.dns_provider_service import DNSProviderService
    from app.services.advanced_ssl_service import AdvancedSSLService
    from app.services.sites_https_service import SitesHttpsService
    from app.services.site_domain_service import SiteDomainService

    provider = _mk_provider(db)
    SystemSettings.set('server_public_ip', '1.2.3.4', value_type='string')
    db.session.commit()
    monkeypatch.setattr(DNSProviderService, 'ensure_a_record',
                        classmethod(lambda cls, h, ip: {'created': True, 'record': {}}))
    monkeypatch.setattr(AdvancedSSLService, 'issue_wildcard_cert',
                        staticmethod(lambda *a, **k: {'success': False, 'error': 'dns plugin missing'}))

    res = SitesHttpsService.setup(provider.id)
    assert res['success'] is False
    assert 'dns plugin missing' in res['error']
    assert SiteDomainService.https_enabled() is False


def test_setup_warns_without_server_ip(app, monkeypatch):
    from app import db
    from app.services.advanced_ssl_service import AdvancedSSLService
    from app.services.sites_https_service import SitesHttpsService
    from app.services.site_domain_service import SiteDomainService

    provider = _mk_provider(db)
    monkeypatch.setattr(SiteDomainService, 'server_ip', classmethod(lambda cls: None))
    monkeypatch.setattr(AdvancedSSLService, 'issue_wildcard_cert',
                        staticmethod(lambda *a, **k: {'success': True, 'certificate_path': '/x'}))

    res = SitesHttpsService.setup(provider.id)
    assert res['success'] is True
    assert res['warning'] and 'manually' in res['warning'].lower()


# ── vhost wiring ────────────────────────────────────────────────────────────

def test_write_vhost_uses_wildcard_cert_when_https_enabled(app, monkeypatch, wp_extension_package):
    from app import db
    from app.models.system_settings import SystemSettings
    from app.services import nginx_service
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db)
    app_row = _mk_app(db, user.id, host='blog.lvh.me')   # covered by the lvh.me wildcard
    SystemSettings.set('sites_https_enabled', True, value_type='boolean')
    db.session.commit()

    captured = {}
    monkeypatch.setattr(nginx_service.NginxService, 'create_site',
                        classmethod(lambda cls, **kw: captured.update(kw) or {'success': True}))
    monkeypatch.setattr(nginx_service.NginxService, 'enable_site', classmethod(lambda cls, name: {'success': True}))

    WordPressService._write_app_vhost(app_row)
    assert captured['ssl_cert'] == '/etc/letsencrypt/live/lvh.me/fullchain.pem'
    assert captured['ssl_key'] == '/etc/letsencrypt/live/lvh.me/privkey.pem'


def test_write_vhost_no_wildcard_for_custom_domain(app, monkeypatch, wp_extension_package):
    from app import db
    from app.models.domain import Domain
    from app.models.system_settings import SystemSettings
    from app.services import nginx_service
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o2')
    app_row = _mk_app(db, user.id, name='shop', host='blog.lvh.me')
    db.session.add(Domain(name='myshop.com', is_primary=True, application_id=app_row.id))   # not under base
    db.session.commit()
    SystemSettings.set('sites_https_enabled', True, value_type='boolean')
    db.session.commit()

    captured = {}
    monkeypatch.setattr(nginx_service.NginxService, 'create_site',
                        classmethod(lambda cls, **kw: captured.update(kw) or {'success': True}))
    monkeypatch.setattr(nginx_service.NginxService, 'enable_site', classmethod(lambda cls, name: {'success': True}))

    WordPressService._write_app_vhost(app_row)
    assert captured['ssl_cert'] is None   # a non-covered domain blocks the wildcard
