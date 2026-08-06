"""Tests for reconcile-on-connect (setup_reconcile_service): DNS backfill preview
correctness (wildcard vs per-site), the apply loop's idempotency, and the
WordPress url-fix detection matrix + apply."""
import pytest

from app.services.setup_reconcile_service import SetupReconcileService


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

def set_setting(key, value, vtype='string'):
    from app import db
    from app.models.system_settings import SystemSettings
    SystemSettings.set(key=key, value=value, value_type=vtype)
    db.session.commit()


@pytest.fixture
def owner(app):
    from werkzeug.security import generate_password_hash
    from app import db
    from app.models import User
    u = User(email='rec@test.local', username='recuser',
             password_hash=generate_password_hash('x'),
             role=User.ROLE_ADMIN, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def make_app_with_domain(owner, name, host, primary=True):
    from app import db
    from app.models.application import Application
    from app.models.domain import Domain
    a = Application(name=name, app_type='static', user_id=owner.id)
    db.session.add(a)
    db.session.flush()
    db.session.add(Domain(name=host, application_id=a.id, is_primary=primary))
    db.session.commit()
    return a


def add_provider():
    from app import db
    from app.models.email import DNSProviderConfig
    db.session.add(DNSProviderConfig(name='CF', provider='cloudflare', api_key='x'))
    db.session.commit()


# --------------------------------------------------------------------------- #
# DNS backfill — candidate enumeration by mode
# --------------------------------------------------------------------------- #

def test_wildcard_mode_yields_one_wildcard_record_and_skips_subdomains(app, owner):
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'wildcard')
    make_app_with_domain(owner, 'blog', 'blog.apps.example.com')

    cands = SetupReconcileService._dns_candidates()
    hosts = {c['host']: c for c in cands}
    assert '*.apps.example.com' in hosts
    assert hosts['*.apps.example.com']['mode'] == 'wildcard'
    # The subdomain is covered by the wildcard, so it isn't a separate candidate.
    assert 'blog.apps.example.com' not in hosts


def test_per_site_mode_yields_each_subdomain_and_no_wildcard(app, owner):
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'per-site')
    make_app_with_domain(owner, 'blog', 'blog.apps.example.com')
    make_app_with_domain(owner, 'shop', 'shop.apps.example.com')

    cands = SetupReconcileService._dns_candidates()
    hosts = {c['host']: c for c in cands}
    assert '*.apps.example.com' not in hosts
    assert hosts['blog.apps.example.com']['mode'] == 'per-site'
    assert hosts['shop.apps.example.com']['mode'] == 'per-site'


def test_custom_domain_outside_base_is_always_a_candidate(app, owner):
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'wildcard')
    make_app_with_domain(owner, 'store', 'store.acme.org')

    hosts = {c['host']: c for c in SetupReconcileService._dns_candidates()}
    assert hosts['store.acme.org']['mode'] == 'custom'


def test_dev_and_ip_hosts_are_skipped(app, owner):
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'per-site')
    make_app_with_domain(owner, 'dev', 'thing.lvh.me')
    make_app_with_domain(owner, 'ip', '203.0.113.9')

    hosts = {c['host'] for c in SetupReconcileService._dns_candidates()}
    assert 'thing.lvh.me' not in hosts
    assert '203.0.113.9' not in hosts


def test_preview_reports_readiness_and_provider_coverage(app, owner, monkeypatch):
    from app.services.dns_provider_service import DNSProviderService
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'per-site')
    set_setting('server_public_ip', '203.0.113.7')
    make_app_with_domain(owner, 'blog', 'blog.apps.example.com')
    add_provider()
    monkeypatch.setattr(DNSProviderService, 'find_zone_for_domain',
                        classmethod(lambda cls, d: ({'name': 'CF'}, {'id': 'z1'})))

    preview = SetupReconcileService.dns_backfill_preview()
    assert preview['ready'] is True
    assert preview['has_provider'] is True
    assert preview['server_ip'] == '203.0.113.7'
    item = next(i for i in preview['items'] if i['host'] == 'blog.apps.example.com')
    assert item['provider_covers_zone'] is True
    assert item['target_ip'] == '203.0.113.7'


def test_preview_not_ready_without_ip(app, owner):
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'per-site')
    make_app_with_domain(owner, 'blog', 'blog.apps.example.com')
    add_provider()
    preview = SetupReconcileService.dns_backfill_preview()
    assert preview['ready'] is False  # no server IP


# --------------------------------------------------------------------------- #
# DNS backfill — apply loop + idempotency (second run = no-ops)
# --------------------------------------------------------------------------- #

def test_apply_creates_then_is_idempotent(app, owner, monkeypatch):
    from app.services.dns_provider_service import DNSProviderService
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'per-site')
    set_setting('server_public_ip', '203.0.113.7')
    make_app_with_domain(owner, 'blog', 'blog.apps.example.com')
    make_app_with_domain(owner, 'shop', 'shop.apps.example.com')

    # Stateful fake provider: first ensure creates, later ones are no-ops.
    existing = set()

    def fake_ensure(cls, domain, ip):
        if domain in existing:
            return {'created': False, 'reason': 'exists', 'provider': 'CF'}
        existing.add(domain)
        return {'created': True, 'provider': 'CF',
                'record': {'type': 'A', 'name': domain, 'value': ip}}
    monkeypatch.setattr(DNSProviderService, 'ensure_a_record', classmethod(fake_ensure))

    first = SetupReconcileService.dns_backfill_apply()
    assert first['applied'] == 2
    assert {r['host'] for r in first['results']} == {
        'blog.apps.example.com', 'shop.apps.example.com'}

    second = SetupReconcileService.dns_backfill_apply()
    assert second['applied'] == 0                      # idempotent — no new writes
    assert all(r['created'] is False for r in second['results'])


def test_apply_without_ip_is_a_noop(app, owner):
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'per-site')
    make_app_with_domain(owner, 'blog', 'blog.apps.example.com')
    res = SetupReconcileService.dns_backfill_apply()
    assert res['applied'] == 0
    assert 'error' in res


def test_backfill_job_handler_runs_apply(app, owner, monkeypatch):
    from app.services.dns_provider_service import DNSProviderService
    set_setting('sites_base_domain', 'apps.example.com')
    set_setting('sites_dns_mode', 'per-site')
    set_setting('server_public_ip', '203.0.113.7')
    make_app_with_domain(owner, 'blog', 'blog.apps.example.com')
    monkeypatch.setattr(DNSProviderService, 'ensure_a_record',
                        classmethod(lambda cls, d, ip: {'created': True, 'provider': 'CF'}))
    summary = SetupReconcileService.run_dns_backfill_job(object())
    assert summary['applied'] == 1


# --------------------------------------------------------------------------- #
# WordPress url-fix — detection matrix (pure classifier)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('current,target,expected', [
    ('http://localhost:8300', 'https://blog.example.com', True),   # localhost → domain
    ('http://127.0.0.1:8300', 'https://blog.example.com', True),   # loopback → domain
    ('http://203.0.113.9', 'https://blog.example.com', True),      # stale IP → domain
    ('https://blog.example.com', 'https://blog.example.com', False),  # already correct
    ('https://old.example.com', 'https://blog.example.com', False),   # domain → domain: leave
    ('http://localhost:8300', 'http://localhost:9000', False),     # no real target
    ('http://localhost:8300', '', False),                          # no target
    (None, 'https://blog.example.com', False),                     # unknown current
])
def test_url_fix_needed_matrix(current, target, expected):
    assert SetupReconcileService.url_fix_needed(current, target) is expected


# --------------------------------------------------------------------------- #
# WordPress url-fix — preview + apply with a mocked WP service
# --------------------------------------------------------------------------- #

@pytest.fixture
def wp_site(app, owner):
    """A WordPressSite on an Application with a primary managed domain."""
    from app import db
    from app.models.application import Application
    from app.models.domain import Domain
    from app.models.wordpress_site import WordPressSite
    a = Application(name='wpblog', app_type='wordpress', user_id=owner.id,
                    root_path='/srv/sites/wpblog', port=8300)
    db.session.add(a)
    db.session.flush()
    db.session.add(Domain(name='blog.apps.example.com', application_id=a.id, is_primary=True))
    site = WordPressSite(application_id=a.id)
    db.session.add(site)
    db.session.commit()
    return site


class _FakeWP:
    """Stands in for the WordPress extension service (no wp-cli)."""
    current = 'http://localhost:8300'
    swapped = []

    @classmethod
    def _site_current_url(cls, app):
        return cls.current

    @classmethod
    def preview_url_change(cls, app, new_url):
        return {'success': True, 'current_url': cls.current, 'new_url': new_url,
                'pairs': [{'search': cls.current, 'replace': new_url, 'replacements': 12}],
                'total': 12}

    @classmethod
    def change_site_url(cls, app, new_url, keep_old_redirect=True):
        cls.swapped.append(new_url)
        cls.current = new_url  # now correct → not re-detected
        return {'success': True, 'old_url': 'http://localhost:8300', 'new_url': new_url}


def test_url_fix_preview_detects_localhost_site(app, wp_site, monkeypatch, wp_extension_package):
    import app.services.wordpress_bridge as bridge
    _FakeWP.current = 'http://localhost:8300'
    monkeypatch.setattr(bridge, 'wordpress_service', lambda: _FakeWP)

    preview = SetupReconcileService.url_fix_preview()
    assert preview['count'] == 1
    item = preview['items'][0]
    assert item['current_url'] == 'http://localhost:8300'
    assert item['new_url'].endswith('blog.apps.example.com')
    assert item['total'] == 12


def test_url_fix_apply_swaps_then_is_idempotent(app, wp_site, monkeypatch, wp_extension_package):
    import app.services.wordpress_bridge as bridge
    _FakeWP.current = 'http://localhost:8300'
    _FakeWP.swapped = []
    monkeypatch.setattr(bridge, 'wordpress_service', lambda: _FakeWP)

    first = SetupReconcileService.url_fix_apply()
    assert first['fixed'] == 1
    assert _FakeWP.swapped and _FakeWP.swapped[0].endswith('blog.apps.example.com')

    # Second run: the site is now on its target URL, so nothing is detected.
    second = SetupReconcileService.url_fix_apply()
    assert second['fixed'] == 0
