"""Recycle-bin hooks for Domain.

Deleting a domain does two things: it tombstones the row, and it rewrites (or
tears down) the parent app's nginx vhost so traffic stops being served. Putting
the row back only undoes the first. These hooks undo the second, and refuse the
restore up front in the cases where putting the row back would be wrong.
"""
import logging

from app import db
from app.models import Application, Domain
from app.services.nginx_service import NginxService

logger = logging.getLogger(__name__)


def pre_restore_domain(domain):
    """Return an error string to refuse the restore, or None to allow it.

    The one that actually happens: deleting a domain FREES its name (the unique
    index only covers live rows), so someone can re-add it. Clearing the
    tombstone would then leave two live rows with the same name and blow up on
    the index at commit — a 500 for what is really an explainable conflict.
    """
    clash = (Domain.query_active()
             .filter(Domain.name == domain.name, Domain.id != domain.id)
             .first())
    if clash:
        return (f'“{domain.name}” has been added again since this was deleted '
                f'(app #{clash.application_id}). Remove the current one first, '
                f'or leave this in the bin.')

    app = Application.query.get(domain.application_id)
    if app is None:
        return ('the application this domain belonged to no longer exists, '
                'so there is nothing to attach it back to')
    return None


def on_restore_domain(domain):
    """Re-serve the domain: rewrite the app's vhost from its LIVE domains.

    Mirrors what delete_domain does in reverse — same NginxService.create_site
    call over the same live-domain set, which now includes this one again.
    """
    app = Application.query.get(domain.application_id)
    if app is None:
        return

    # A restored domain must not create a second primary. The one that stayed
    # live keeps the role; this row comes back as an alias.
    if domain.is_primary:
        other_primary = (Domain.query_active()
                         .filter(Domain.application_id == app.id,
                                 Domain.is_primary.is_(True),
                                 Domain.id != domain.id)
                         .first())
        if other_primary:
            domain.is_primary = False
            db.session.commit()

    # Only Docker apps get a generated vhost (see delete_domain / create_domain);
    # anything else has no nginx state to put back.
    if app.app_type != 'docker' or not app.port:
        return

    domains = [d.name for d in
               Domain.query_active().filter_by(application_id=app.id).all()]
    if not domains:
        return

    result = NginxService.create_site(
        name=app.name,
        app_type='docker',
        domains=domains,
        root_path=app.root_path or '',
        port=app.port,
    )
    if not result or not result.get('success'):
        # Surfaced to the caller as a restore warning: the row IS back, it just
        # is not being served yet.
        raise RuntimeError((result or {}).get('error') or 'nginx config could not be written')
    NginxService.reload()

    # NOTE: the certificate is deliberately NOT re-issued. ssl_enabled may still
    # be True with cert files that expired or were cleaned up while the domain
    # sat in the bin, and silently talking to Let's Encrypt during a restore is
    # not something a "put it back" button should do. The domain returns on
    # HTTP; re-enable SSL explicitly.
