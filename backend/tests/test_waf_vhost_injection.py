"""WAF include placement inside the vhost (#117 bug class).

_inject_include used to insert after the *first* ``server {`` — on an SSL
vhost that is the HTTP->HTTPS redirect block from SSL_REDIRECT_TEMPLATE, so
ModSecurity was wired into a server that only issues 301s while the real
HTTPS server stayed unprotected (and apply() still reported wired).
The micro-cache injector guards this exact trap (nginx_service.py); these
tests pin the same guarantee for the WAF include.
"""
import pytest

from app.services.waf_service import WafService


SSL_VHOST = '''server {
    listen 80;
    listen [::]:80;
    server_name shop.example.com;
    return 301 https://$server_name$request_uri;
}
server {
    listen 443 ssl;
    server_name shop.example.com;

    location / {
        proxy_pass http://127.0.0.1:8003;
    }
}
'''

PLAIN_VHOST = '''server {
    listen 80;
    server_name blog.example.com;

    location / {
        proxy_pass http://127.0.0.1:8004;
    }
}
'''


@pytest.fixture
def plain_write(monkeypatch):
    """Route _write_file to a plain filesystem write (no sudo/tee)."""
    def _write(path, content):
        with open(path, 'w') as fh:
            fh.write(content)
        return {'success': True}
    monkeypatch.setattr(WafService, '_write_file',
                        classmethod(lambda cls, p, c: _write(p, c)))


def _server_blocks(content):
    """Split rendered vhost text into per-server-block chunks."""
    import re
    starts = [m.start() for m in re.finditer(r'server\s*\{', content)]
    starts.append(len(content))
    return [content[starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]


def test_ssl_vhost_include_lands_in_https_block(tmp_path, plain_write):
    vhost = tmp_path / 'shop.example.com'
    vhost.write_text(SSL_VHOST)

    result = WafService._inject_include(str(vhost), '/etc/nginx/waf/shop.conf')
    assert result['success']

    redirect_block, https_block = _server_blocks(vhost.read_text())
    assert 'include /etc/nginx/waf/shop.conf;' not in redirect_block
    assert 'include /etc/nginx/waf/shop.conf;' in https_block
    # The redirect block still redirects.
    assert 'return 301' in redirect_block


def test_plain_vhost_include_lands_in_only_block(tmp_path, plain_write):
    vhost = tmp_path / 'blog.example.com'
    vhost.write_text(PLAIN_VHOST)

    assert WafService._inject_include(str(vhost), '/etc/nginx/waf/blog.conf')['success']
    assert 'include /etc/nginx/waf/blog.conf;' in vhost.read_text()


def test_reapply_is_idempotent_and_stays_in_https_block(tmp_path, plain_write):
    vhost = tmp_path / 'shop.example.com'
    vhost.write_text(SSL_VHOST)

    WafService._inject_include(str(vhost), '/etc/nginx/waf/shop.conf')
    WafService._inject_include(str(vhost), '/etc/nginx/waf/shop-v2.conf')

    content = vhost.read_text()
    assert content.count('include /etc/nginx/waf/') == 1
    redirect_block, https_block = _server_blocks(content)
    assert 'shop-v2.conf' in https_block
    assert 'waf' not in redirect_block


def test_drift_expected_render_includes_waf_for_enforcing_policy(app, monkeypatch):
    """An enforcing WAF policy's include must appear in drift's EXPECTED
    render — byte-comparing the wired vhost against the bare template read
    every WAF'd app as permanently drifted, and one repair click then
    regenerated the vhost without the include: silently unprotected while
    the DB still said enforcing (plan 82 §F.1)."""
    from app import db
    from app.services import drift_service
    from app.services.nginx_service import NginxService
    from app.services.site_domain_service import SiteDomainService
    from app.services.waf_service import WafService
    from factories import make_application

    a = make_application(db, name='waf-drift-app')
    policy = WafService.get_or_create_policy(a.id)
    policy.mode = 'block'
    db.session.commit()

    monkeypatch.setattr(SiteDomainService, 'app_vhost_kwargs',
                        classmethod(lambda cls, app_, force_type=None:
                                    ({'name': app_.name}, None)))
    monkeypatch.setattr(NginxService, 'render_site_config',
                        classmethod(lambda cls, **kw:
                                    {'success': True, 'config': PLAIN_VHOST}))

    expected = drift_service._nginx_render_expected(a.id)
    (content,) = expected.values()
    assert f'include {WafService.include_path_for(a.id)};' in content

    # Without a policy (or with mode off) the template is expected as-is.
    policy.mode = 'off'
    db.session.commit()
    (content,) = drift_service._nginx_render_expected(a.id).values()
    assert 'include /etc/nginx' not in content


def test_drift_repair_rewires_waf(app, monkeypatch):
    """Repair regenerates the vhost from the template; for an enforcing
    policy it must re-run WafService.apply so the include comes back."""
    from app import db
    from app.services import drift_service
    from app.services.nginx_service import NginxService
    from app.services.site_domain_service import SiteDomainService
    from app.services.waf_service import WafService
    from factories import make_application

    a = make_application(db, name='waf-repair-app')
    policy = WafService.get_or_create_policy(a.id)
    policy.mode = 'detect'
    db.session.commit()

    applied = []
    monkeypatch.setattr(SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, app_, force_type=None:
                                    {'nginx': {'success': True}, 'warning': None}))
    monkeypatch.setattr(NginxService, 'reload',
                        classmethod(lambda cls: {'success': True}))
    monkeypatch.setattr(WafService, 'apply',
                        classmethod(lambda cls, app_id: applied.append(app_id)
                                    or {'success': True}))

    result = drift_service._nginx_repair(a.id)
    assert result['success']
    assert applied == [a.id]

    # No policy -> no apply call.
    applied.clear()
    b = make_application(db, name='no-waf-app')
    assert drift_service._nginx_repair(b.id)['success']
    assert applied == []


def test_app_block_with_location_level_redirect_still_selected(tmp_path, plain_write):
    # A serving block that happens to contain a 301 inside a location must
    # not be mistaken for the redirect-only wrapper.
    vhost = tmp_path / 'site'
    vhost.write_text('''server {
    listen 80;
    server_name site.example.com;

    location /old {
        return 301 /new;
    }
    location / {
        proxy_pass http://127.0.0.1:8005;
    }
}
''')
    assert WafService._inject_include(str(vhost), '/etc/nginx/waf/site.conf')['success']
    assert 'include /etc/nginx/waf/site.conf;' in vhost.read_text()
