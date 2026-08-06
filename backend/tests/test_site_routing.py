"""Phase 1 proving tests.

Managed sites are published at a real hostname (<slug>.<base_domain>) instead
of localhost:<port>: SiteDomainService resolves the host, and WordPressService
provisions a primary Domain row + nginx reverse-proxy vhost.
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


def _mk_app(db, user_id, name='blog', port=8300):
    from app.models import Application
    a = Application(name=name, app_type='docker', user_id=user_id,
                    root_path=f'/srv/{name}', port=port)
    db.session.add(a)
    db.session.commit()
    return a


# ── site domain resolution ──────────────────────────────────────────────────

def test_subdomain_for_uses_testing_base_domain(app):
    from app.services.site_domain_service import SiteDomainService
    # TestingConfig pins SITES_BASE_DOMAIN = lvh.me.
    assert SiteDomainService.base_domain() == 'lvh.me'
    assert SiteDomainService.subdomain_for('My Blog!') == 'my-blog.lvh.me'
    assert SiteDomainService.site_url('my-blog.lvh.me') == 'http://my-blog.lvh.me'


def test_subdomain_none_when_base_domain_unset(app, monkeypatch):
    from app.services.site_domain_service import SiteDomainService
    monkeypatch.setitem(app.config, 'SITES_BASE_DOMAIN', '')
    assert SiteDomainService.base_domain() == ''
    # No base domain -> provisioning falls back to the legacy localhost URL.
    assert SiteDomainService.subdomain_for('blog') is None


def test_runtime_setting_overrides_config(app):
    from app import db
    from app.models.system_settings import SystemSettings
    from app.services.site_domain_service import SiteDomainService
    SystemSettings.set('sites_base_domain', 'apps.example.com')
    db.session.commit()
    assert SiteDomainService.base_domain() == 'apps.example.com'
    assert SiteDomainService.subdomain_for('Shop') == 'shop.apps.example.com'


# ── routing provisioning ────────────────────────────────────────────────────

def test_provision_routing_creates_primary_domain_and_docker_vhost(app, monkeypatch, wp_extension_package):
    from app import db
    from app.models.domain import Domain
    from app.services import nginx_service
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db)
    app_row = _mk_app(db, user.id, name='blog', port=8300)

    captured = {}

    def fake_create_site(cls, **kw):
        captured.update(kw)
        return {'success': True}

    monkeypatch.setattr(nginx_service.NginxService, 'create_site', classmethod(fake_create_site))
    monkeypatch.setattr(nginx_service.NginxService, 'enable_site', classmethod(lambda cls, name: {'success': True}))

    res = WordPressService._provision_routing(app_row, 'blog.lvh.me')
    assert res['warning'] is None
    assert res['domain'] == 'blog.lvh.me'

    d = Domain.query.filter_by(application_id=app_row.id).first()
    assert d is not None
    assert d.name == 'blog.lvh.me'
    assert d.is_primary is True

    # Reverse-proxy vhost, not php-fpm: docker app_type + the container's port.
    assert captured['app_type'] == 'docker'
    assert captured['port'] == 8300
    assert 'blog.lvh.me' in captured['domains']


def test_provision_routing_warns_when_nginx_unavailable(app, monkeypatch, wp_extension_package):
    from app import db
    from app.models.domain import Domain
    from app.services import nginx_service
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'owner2')
    app_row = _mk_app(db, user.id, name='shop', port=8400)

    monkeypatch.setattr(nginx_service.NginxService, 'create_site',
                        classmethod(lambda cls, **kw: {'success': False, 'error': 'nginx not installed'}))

    res = WordPressService._provision_routing(app_row, 'shop.lvh.me')
    # Domain still recorded; the nginx failure is a warning, never an exception.
    assert Domain.query.filter_by(name='shop.lvh.me').first() is not None
    assert res['warning'] and 'nginx' in res['warning']


def test_canonical_site_url_prefers_primary_domain(app, wp_extension_package):
    from app import db
    from app.models.domain import Domain
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'owner3')
    app_row = _mk_app(db, user.id, name='acme', port=8500)

    # No domain yet -> legacy localhost URL.
    assert WordPressService._canonical_site_url(app_row) == 'http://localhost:8500'

    db.session.add(Domain(name='acme.lvh.me', is_primary=True, application_id=app_row.id))
    db.session.commit()
    assert WordPressService._canonical_site_url(app_row) == 'http://acme.lvh.me'
