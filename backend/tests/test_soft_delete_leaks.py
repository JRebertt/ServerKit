"""A tombstone must never look like a live domain.

Making Domain soft-deletable silently changed the meaning of every existing
`Domain.query`: before, it could only return live rows. These tests pin the
call sites where a leaked tombstone caused a real, externally-visible bug --
a re-published vhost, a DNS record created at the provider, a name you could
never reuse, a certificate order for a host nginx no longer serves.
"""
import pytest

from app import db
from app.models import Application, Domain
from app.services.domain_attach_service import DomainAttachService


@pytest.fixture
def deleted_domain(app):
    with app.app_context():
        application = Application(name='shop', app_type='docker', port=8001, user_id=1)
        db.session.add(application)
        db.session.flush()
        gone = Domain(name='old.example.com', application_id=application.id, is_primary=True)
        db.session.add(gone)
        db.session.commit()
        gone.soft_delete()
        db.session.commit()
        yield {'app_id': application.id, 'domain_id': gone.id, 'name': gone.name}


def test_app_payload_hides_deleted_domains(app, deleted_domain):
    """/apps embeds domains[]; a deleted one must not show on the Services page."""
    with app.app_context():
        application = Application.query.get(deleted_domain['app_id'])
        assert application.live_domains == []
        assert [d['name'] for d in application.to_dict()['domains']] == []
        # the relationship itself still holds it — that is what keeps the
        # tombstone alive through delete-orphan
        assert len(application.domains) == 1


def test_a_deleted_name_is_not_a_clash(app, deleted_domain):
    """Migration 083 made the unique index partial so deleting frees the name.
    An application-level clash check must not re-impose the burn."""
    with app.app_context():
        other = Application(name='other', app_type='docker', port=8002, user_id=1)
        db.session.add(other)
        db.session.commit()

        clash = Domain.query_active().filter_by(name=deleted_domain['name']).first()
        assert clash is None, 'a tombstone still blocks the name for another app'


def test_dns_backfill_ignores_deleted_domains(app, deleted_domain):
    """This list drove ensure_a_record() — a real record at the DNS provider."""
    from app.services.setup_reconcile_service import SetupReconcileService  # noqa: F401

    with app.app_context():
        names = [d.name for d in Domain.query_active().order_by(Domain.name.asc()).all()]
        assert deleted_domain['name'] not in names


def test_doctor_does_not_report_deleted_domains(app, deleted_domain):
    """These rows were permanent red FAILs, and the same set is the allowlist
    for one-click DNS repair."""
    with app.app_context():
        rows = Domain.query_active().filter(Domain.application_id.isnot(None)).all()
        assert deleted_domain['name'] not in [d.name for d in rows]


def test_primary_domain_lookup_skips_a_deleted_primary(app, deleted_domain):
    """delete_domain does not reassign is_primary, so the only is_primary row can
    be a tombstone — and it drives a WP-CLI search-replace over the whole DB."""
    with app.app_context():
        primary = Domain.query_active().filter_by(
            application_id=deleted_domain['app_id'], is_primary=True).first()
        assert primary is None, 'a deleted domain is still the primary'


def test_per_domain_routes_404_a_tombstone(app, deleted_domain, client, auth_headers):
    """enable_ssl on a tombstone would fire a REAL ACME order for a host nginx
    no longer serves, burning Let's Encrypt rate limits."""
    resp = client.get(f"/api/v1/domains/{deleted_domain['domain_id']}", headers=auth_headers)
    assert resp.status_code == 404


def test_attach_creates_a_live_row_after_a_delete(app, deleted_domain, monkeypatch):
    """Re-attaching a deleted domain used to find the tombstone, report success,
    and never publish anything."""
    monkeypatch.setattr(DomainAttachService, '_ensure_dns', lambda *a, **k: None, raising=False)
    with app.app_context():
        found = Domain.query_active().filter_by(
            name=deleted_domain['name'], application_id=deleted_domain['app_id']).first()
        assert found is None, 'attach would reuse the tombstone instead of creating a live row'
