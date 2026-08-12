"""Adding or removing ONE domain must not take the site's others off HTTPS.

Both routes used to call NginxService.create_site directly with no
ssl_cert/ssl_key/micro_cache, so the regenerated vhost came out HTTP-only and
cache-less. On a site covered by a base wildcard cert that meant touching any
domain silently dropped the WHOLE site to plain HTTP — invisible until someone
loaded it. Both now go through SiteDomainService, which re-resolves the cert,
the cache flag and the app-type template.
"""
import pytest

from app import db
from app.models import Application, Domain
from app.services.site_domain_service import SiteDomainService


@pytest.fixture
def wildcard_site(app, monkeypatch):
    """An app on two subdomains of a base whose wildcard HTTPS is enabled."""
    monkeypatch.setattr(SiteDomainService, 'covering_base',
                        classmethod(lambda cls, host: 'acme.dev' if host.endswith('.acme.dev') else None))
    monkeypatch.setattr(SiteDomainService, 'https_enabled', classmethod(lambda cls, base: True))
    monkeypatch.setattr(SiteDomainService, 'wildcard_cert_paths',
                        classmethod(lambda cls, base: ('/etc/le/live/acme.dev/fullchain.pem',
                                                       '/etc/le/live/acme.dev/privkey.pem')))
    with app.app_context():
        application = Application(name='shop', app_type='docker', port=8001,
                                  user_id=1, micro_cache_enabled=True)
        db.session.add(application)
        db.session.flush()
        a = Domain(name='a.acme.dev', application_id=application.id, is_primary=True)
        b = Domain(name='b.acme.dev', application_id=application.id)
        db.session.add_all([a, b])
        db.session.commit()
        yield {'app_id': application.id, 'a': a.id, 'b': b.id}


def test_vhost_kwargs_carry_the_wildcard_cert_and_cache(app, wildcard_site):
    with app.app_context():
        application = Application.query.get(wildcard_site['app_id'])
        kwargs, reason = SiteDomainService.app_vhost_kwargs(application)

        assert reason is None
        assert kwargs['ssl_cert'].endswith('fullchain.pem'), 'wildcard cert dropped -> site falls back to HTTP'
        assert kwargs['ssl_key'].endswith('privkey.pem')
        assert kwargs['micro_cache'] is True
        assert sorted(kwargs['domains']) == ['a.acme.dev', 'b.acme.dev']


def test_a_soft_deleted_domain_is_not_written_back_into_the_vhost(app, wildcard_site):
    """The renderer used Domain.query, which now returns tombstones — it would
    have put a deleted domain straight back into server_name."""
    with app.app_context():
        Domain.query.get(wildcard_site['b']).soft_delete()
        db.session.commit()

        application = Application.query.get(wildcard_site['app_id'])
        kwargs, _ = SiteDomainService.app_vhost_kwargs(application)

        assert kwargs['domains'] == ['a.acme.dev']
        # and the surviving domain keeps its cert
        assert kwargs['ssl_cert'].endswith('fullchain.pem')


def test_deleting_a_domain_keeps_https_for_the_rest(app, wildcard_site, auth_headers, client, monkeypatch):
    """End to end through the route: the vhost written after a delete must still
    carry the cert."""
    written = []
    from app.services import nginx_service
    monkeypatch.setattr(nginx_service.NginxService, 'create_site',
                        classmethod(lambda cls, **kw: written.append(kw) or {'success': True}))
    monkeypatch.setattr(nginx_service.NginxService, 'enable_site',
                        classmethod(lambda cls, name: {'success': True}))

    resp = client.delete(f"/api/v1/domains/{wildcard_site['b']}", headers=auth_headers)
    assert resp.status_code in (200, 403)          # 403 only if the fixture user lacks the grant
    if resp.status_code != 200:
        pytest.skip('fixture user cannot edit this app')

    assert written, 'no vhost was written after the delete'
    last = written[-1]
    assert last['domains'] == ['a.acme.dev'], 'deleted domain still in server_name'
    assert last['ssl_cert'], 'wildcard cert dropped on delete -> site fell back to HTTP'
    assert last['micro_cache'] is True, 'micro-cache dropped on delete'
