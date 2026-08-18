"""The Cloudflare-ops activity ledger — every zone-operations write ServerKit
makes (settings, DNSSEC, WAF, redirect/transform rules, Origin CA, Workers,
Tunnels, storage) is recorded here, keyed by ``provider_zone_id``.

The ops-layer sibling of :class:`DnsChangeService` (which covers DNS *record*
writes). Recording is best-effort and **never raises** — an audit write must not
break the operation it describes. The current user is captured opportunistically
from the JWT when called inside a request.
"""
import logging

from app import db
from app.models.cf_ops_change import CfOpsChange

logger = logging.getLogger(__name__)


class CfOpsChangeService:

    @staticmethod
    def _current_user_id():
        """Best-effort current user id (None outside a request context).

        Via rbac.get_current_user() so an API-key caller is attributed to the
        key's owner; reading the JWT directly raises for those requests and
        the blanket except turned that into a silent None."""
        try:
            from app.middleware.rbac import get_current_user
            user = get_current_user()
            return user.id if user else None
        except Exception:
            return None

    @staticmethod
    def record(*, provider_zone_id, product, action, target=None, result='ok',
               error=None, config_id=None, user_id=None):
        """Append a Cloudflare-ops change to the ledger. Never raises."""
        try:
            row = CfOpsChange(
                provider_zone_id=provider_zone_id,
                product=product,
                action=action,
                target=str(target)[:256] if target is not None else None,
                result=result,
                error=error,
                dns_provider_config_id=config_id,
                user_id=user_id if user_id is not None
                else CfOpsChangeService._current_user_id(),
            )
            db.session.add(row)
            db.session.commit()
            return row
        except Exception as e:
            db.session.rollback()
            logger.warning('Failed to record Cloudflare ops change: %s', e)
            return None

    @staticmethod
    def list(provider_zone_id=None, config_id=None, product=None, result=None, limit=100):
        q = CfOpsChange.query
        if provider_zone_id:
            q = q.filter_by(provider_zone_id=provider_zone_id)
        if config_id:
            q = q.filter_by(dns_provider_config_id=config_id)
        if product:
            q = q.filter_by(product=product)
        if result:
            q = q.filter_by(result=result)
        return q.order_by(CfOpsChange.created_at.desc(), CfOpsChange.id.desc()).limit(limit).all()
