"""Recycle-bin hooks for Domain.

Deleting a domain does two things: it tombstones the row, and it rewrites (or
tears down) the parent app's nginx vhost so traffic stops being served. Putting
the row back only undoes the first. These hooks undo the second, and refuse the
restore up front in the cases where putting the row back would be wrong.
"""
import logging

from app import db
from app.models import Application, Domain
from app.services.site_domain_service import SiteDomainService

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

    Mirrors what delete_domain does in reverse, over the same live-domain set
    -- which now includes this one again.
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

    # Rewrite through SiteDomainService, NOT a bare NginxService.create_site.
    # Three reasons, all of which were bugs in the first cut of this hook:
    #
    #  1. ENABLE. When the deleted domain was the app's LAST one, delete_domain
    #     ran disable_site() + delete_site() — the sites-enabled symlink is gone,
    #     not just the server_name. create_site alone rewrites the file and
    #     leaves it unserved. write_app_vhost calls enable_site.
    #  2. SSL / CACHE. app_vhost_kwargs re-attaches a covering wildcard cert and
    #     the micro-cache flag. A raw create_site drops both, so a restored site
    #     would silently fall back to plain HTTP.
    #  3. EVERY APP TYPE. delete_domain only touches nginx for docker apps, so
    #     php/static/flask/wordpress vhosts still list the deleted domain. The
    #     rewrite is idempotent, so running it for them repairs that asymmetry
    #     instead of preserving it.
    result = SiteDomainService.write_app_vhost(app)
    warning = (result or {}).get('warning')
    if warning:
        # Surfaced to the caller as a restore warning: the row IS back, it just
        # is not being served yet.
        raise RuntimeError(warning)

    # NOTE: the certificate is deliberately NOT re-issued. ssl_enabled may still
    # be True with cert files that expired or were cleaned up while the domain
    # sat in the bin, and silently talking to Let's Encrypt during a restore is
    # not something a "put it back" button should do. A covering wildcard is
    # re-attached above; a per-domain cert is re-enabled explicitly.
