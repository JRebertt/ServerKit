"""Soft delete + Recycle Bin.

Deleting is the one action in a control panel that repeating cannot undo, so
records a person destroys by hand now leave a tombstone and the bin hands them
back. These tests pin the parts that are easy to get subtly wrong: that the
tombstone stays out of every read path, that a deleted name can be REUSED (the
partial unique index), and that purge is the only thing that really destroys.
"""
import pytest

from app import db
from app.models import Application, Domain
from app.models.saved_view import SavedView
from app.services import recycle_bin_service, saved_view_service


@pytest.fixture
def app_with_domain(app):
    with app.app_context():
        application = Application(name='shop', app_type='docker', port=8001, user_id=1)
        db.session.add(application)
        db.session.flush()
        domain = Domain(name='shop.example.com', application_id=application.id)
        db.session.add(domain)
        db.session.commit()
        yield {'app_id': application.id, 'domain_id': domain.id}


# ---- the mixin -------------------------------------------------------------

def test_soft_delete_keeps_the_row_but_hides_it(app, app_with_domain):
    with app.app_context():
        domain = Domain.query.get(app_with_domain['domain_id'])
        domain.soft_delete(user_id=7)
        db.session.commit()

        assert Domain.query.get(app_with_domain['domain_id']) is not None
        assert Domain.query_active().filter_by(name='shop.example.com').first() is None
        assert Domain.query_deleted().count() == 1
        assert domain.is_active is False
        assert domain.deleted_by_id == 7


def test_a_deleted_name_can_be_reused(app, app_with_domain):
    """The partial unique index is the whole point: a plain UNIQUE would make
    deleting a domain permanently burn its name."""
    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.commit()

        again = Domain(name='shop.example.com', application_id=app_with_domain['app_id'])
        db.session.add(again)
        db.session.commit()          # must not raise IntegrityError

        assert Domain.query_active().filter_by(name='shop.example.com').count() == 1
        assert Domain.query.filter_by(name='shop.example.com').count() == 2


def test_restore_is_idempotent(app, app_with_domain, monkeypatch):
    # Domain now has an on_restore hook that rewrites the vhost; stub the nginx
    # side so this test stays about restore semantics.
    from app.services import domain_restore
    monkeypatch.setattr(domain_restore.SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, a: {'nginx': {}, 'warning': None}))

    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert err is None and item['label'] == 'shop.example.com'
        # restoring an already-live record is a no-op, not an error
        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert err is None
        assert Domain.query_active().count() == 1


# ---- the bin ---------------------------------------------------------------

def test_bin_lists_across_types_newest_first(app, app_with_domain):
    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        view = SavedView(user_id=1, page='domains', name='Mine', slug='mine', state={})
        db.session.add(view)
        db.session.commit()
        view.soft_delete()
        db.session.commit()

        items = recycle_bin_service.list_deleted()
        kinds = {i['kind'] for i in items}
        assert kinds == {'domain', 'saved_view'}
        stamps = [i['deleted_at'] for i in items]
        assert stamps == sorted(stamps, reverse=True)


def test_purge_is_the_only_destructive_path(app, app_with_domain):
    with app.app_context():
        domain_id = app_with_domain['domain_id']
        # not in the bin yet -> refuse
        ok, err = recycle_bin_service.purge('domain', domain_id)
        assert ok is False and 'not in the recycle bin' in err

        Domain.query.get(domain_id).soft_delete()
        db.session.commit()
        ok, err = recycle_bin_service.purge('domain', domain_id)
        assert ok is True and err is None
        assert Domain.query.get(domain_id) is None


def test_purge_expired_respects_the_retention_window(app, app_with_domain):
    from datetime import datetime, timedelta
    with app.app_context():
        domain = Domain.query.get(app_with_domain['domain_id'])
        domain.soft_delete()
        domain.deleted_at = datetime.utcnow() - timedelta(days=45)
        db.session.commit()

        assert recycle_bin_service.purge_expired(retention_days=90) == {}
        assert recycle_bin_service.purge_expired(retention_days=30) == {'domain': 1}


def test_unknown_kind_raises(app):
    with app.app_context():
        with pytest.raises(KeyError):
            recycle_bin_service.restore('nope', 1)


# ---- saved views ------------------------------------------------------------

def test_deleting_a_view_sends_it_to_the_bin(app):
    with app.app_context():
        view, err = saved_view_service.create_view(1, 'domains', 'SSL expiring', {'sorts': []})
        assert err is None
        saved_view_service.delete_view(1, view['id'])

        assert saved_view_service.list_views(1, 'domains') == []
        assert any(i['kind'] == 'saved_view' for i in recycle_bin_service.list_deleted())


def test_view_slug_is_derived_and_deduped(app):
    with app.app_context():
        a, _ = saved_view_service.create_view(1, 'domains', 'SSL expiring', {})
        b, _ = saved_view_service.create_view(1, 'services', 'SSL expiring', {})
        assert a['slug'] == 'ssl-expiring'
        assert b['slug'] == 'ssl-expiring'          # different page, no clash

        assert saved_view_service.get_by_slug(1, 'domains', 'ssl-expiring')['id'] == a['id']
        assert saved_view_service.get_by_slug(1, 'domains', 'nope') is None


def test_a_deleted_view_frees_its_name_and_slug(app):
    with app.app_context():
        first, _ = saved_view_service.create_view(1, 'domains', 'Triage', {})
        saved_view_service.delete_view(1, first['id'])

        again, err = saved_view_service.create_view(1, 'domains', 'Triage', {})
        assert err is None
        assert again['slug'] == 'triage'            # not 'triage-2'
        assert saved_view_service.get_by_slug(1, 'domains', 'triage')['id'] == again['id']


# ---- domain restore hooks ---------------------------------------------------

def test_restoring_a_domain_rewrites_the_vhost(app, app_with_domain, monkeypatch):
    """Deleting tore the domain out of the app's vhost; restoring must put it
    back, or the record is 'restored' while still not being served."""
    from app.services import domain_restore

    calls = []
    monkeypatch.setattr(domain_restore.SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, a: calls.append(a) or {'nginx': {}, 'warning': None}))

    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert err is None and item is not None
        assert len(calls) == 1
        assert calls[0].id == app_with_domain['app_id']


def test_restore_is_refused_when_the_name_was_taken_again(app, app_with_domain):
    """Deleting frees the name (the unique index covers live rows only), so the
    conflict is reachable — and must be a readable refusal, not an
    IntegrityError at commit."""
    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.commit()
        db.session.add(Domain(name='shop.example.com',
                              application_id=app_with_domain['app_id']))
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert item is None
        assert 'added again' in err
        # still tombstoned — a refused restore must not half-apply
        assert Domain.query.get(app_with_domain['domain_id']).deleted_at is not None


def test_restore_is_refused_when_the_app_is_gone(app, app_with_domain):
    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.query(Application).filter_by(id=app_with_domain['app_id']).delete()
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert item is None and 'no longer exists' in err


def test_restored_domain_does_not_become_a_second_primary(app, app_with_domain, monkeypatch):
    from app.services import domain_restore
    monkeypatch.setattr(domain_restore.SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, a: {'nginx': {}, 'warning': None}))

    with app.app_context():
        first = Domain.query.get(app_with_domain['domain_id'])
        first.is_primary = True
        first.soft_delete()
        db.session.add(Domain(name='new-primary.example.com', is_primary=True,
                              application_id=app_with_domain['app_id']))
        db.session.commit()

        recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        primaries = Domain.query_active().filter_by(
            application_id=app_with_domain['app_id'], is_primary=True).count()
        assert primaries == 1


def test_a_failing_vhost_rewrite_warns_but_keeps_the_restore(app, app_with_domain, monkeypatch):
    from app.services import domain_restore
    monkeypatch.setattr(domain_restore.SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, a: {'nginx': None, 'warning': 'nginx -t failed'}))

    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        # The row IS back; only the side effect failed. Say so, don't roll back.
        assert item is not None
        assert 'nginx -t failed' in err
        assert Domain.query.get(app_with_domain['domain_id']).deleted_at is None


def test_restoring_the_last_domain_re_enables_the_site(app, app_with_domain, monkeypatch):
    """The bug this hook shipped with.

    When the deleted domain was the app's LAST one, delete_domain ran
    disable_site() + delete_site() — the sites-enabled symlink is gone, not just
    the server_name. A bare NginxService.create_site rewrites the file and
    leaves it UNSERVED. Restore has to go through SiteDomainService.write_app_vhost,
    which calls enable_site as well.
    """
    from app.services import domain_restore
    from app.services.nginx_service import NginxService

    seen = {'create': 0, 'enable': 0}
    monkeypatch.setattr(NginxService, 'create_site',
                        classmethod(lambda cls, **kw: seen.__setitem__('create', seen['create'] + 1) or {'success': True}))
    monkeypatch.setattr(NginxService, 'enable_site',
                        classmethod(lambda cls, name: seen.__setitem__('enable', seen['enable'] + 1) or {'success': True}))

    assert domain_restore is not None        # hook module must be importable

    with app.app_context():
        # the app's ONLY domain — this is the disable_site + delete_site branch
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.commit()
        assert Domain.query_active().filter_by(
            application_id=app_with_domain['app_id']).count() == 0

        _, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert err is None

    assert seen['create'] >= 1, 'vhost was never written'
    assert seen['enable'] >= 1, 'vhost written but never enabled — the site stays unserved'


def test_restoring_a_view_is_refused_when_the_name_was_reused(app):
    """Deleting a view frees its name and slug, so either can be taken by the
    time you press Restore — that must be a refusal, not an IntegrityError."""
    with app.app_context():
        first, _ = saved_view_service.create_view(1, 'domains', 'Triage', {})
        saved_view_service.delete_view(1, first['id'])
        saved_view_service.create_view(1, 'domains', 'Triage', {})   # reuses name + slug

        item, err = recycle_bin_service.restore('saved_view', first['id'])
        assert item is None
        assert 'already have' in err
        assert SavedView.query.get(first['id']).deleted_at is not None


# ---- the restore notice ----------------------------------------------------

def test_restoring_an_https_domain_says_it_came_back_on_http(app, app_with_domain, monkeypatch):
    """on_restore_domain deliberately does not re-issue a certificate, so an
    ssl_enabled domain returns over plain HTTP. Silently is the problem: the
    row still reads ssl_enabled, so nothing tells the person who restored it."""
    from app.services import domain_restore

    monkeypatch.setattr(domain_restore.SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, a: {'nginx': {}, 'warning': None}))
    # No wildcard covers it, so nothing is serving HTTPS for this name.
    monkeypatch.setattr(domain_restore.SiteDomainService, 'covering_base',
                        classmethod(lambda cls, name: None))

    with app.app_context():
        domain = Domain.query.get(app_with_domain['domain_id'])
        domain.ssl_enabled = True
        domain.soft_delete()
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        # The restore SUCCEEDED — the notice must not land in the error slot.
        assert err is None
        assert 'HTTP' in item['notice']
        assert 'certificate was not re-issued' in item['notice']


def test_no_notice_when_a_wildcard_already_covers_the_domain(app, app_with_domain, monkeypatch):
    """app_vhost_kwargs re-attaches a covering wildcard, so HTTPS really is back
    and warning about it would be noise."""
    from app.services import domain_restore

    monkeypatch.setattr(domain_restore.SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, a: {'nginx': {}, 'warning': None}))
    monkeypatch.setattr(domain_restore.SiteDomainService, 'covering_base',
                        classmethod(lambda cls, name: 'example.com'))
    monkeypatch.setattr(domain_restore.SiteDomainService, 'https_enabled',
                        classmethod(lambda cls, base: True))

    with app.app_context():
        domain = Domain.query.get(app_with_domain['domain_id'])
        domain.ssl_enabled = True
        domain.soft_delete()
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert err is None
        assert 'notice' not in item


def test_a_plain_http_domain_restores_without_a_notice(app, app_with_domain, monkeypatch):
    from app.services import domain_restore

    monkeypatch.setattr(domain_restore.SiteDomainService, 'write_app_vhost',
                        classmethod(lambda cls, a: {'nginx': {}, 'warning': None}))

    with app.app_context():
        Domain.query.get(app_with_domain['domain_id']).soft_delete()
        db.session.commit()

        item, err = recycle_bin_service.restore('domain', app_with_domain['domain_id'])
        assert err is None
        assert 'notice' not in item
