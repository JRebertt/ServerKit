"""The DNS change activity log — every record write ServerKit sends to a connected
provider is recorded here, and failures are surfaced to admins.

Recording happens at the single write choke point
(:meth:`DnsOwnershipService.guarded_upsert` / ``guarded_delete``), so the feed on a
connection is a complete, honest account of what the panel changed in the user's
zone — successes, foreign-record refusals, and failures alike.
"""
import json
import logging

from app import db
from app.models.dns_change import DnsChange

logger = logging.getLogger(__name__)


class DnsChangeService:

    @staticmethod
    def record(*, provider, provider_zone_id, action, record_type=None, name=None,
               content=None, provider_record_id=None, source=None, result='ok',
               error=None, config_id=None, before=None):
        """Append a change to the log. On a real failure (``result == 'error'``) also
        surface an admin-facing notice. Never raises — logging a change must not break
        the write it describes."""
        try:
            row = DnsChange(
                provider=provider, provider_zone_id=provider_zone_id, action=action,
                record_type=record_type, name=name, content=content,
                before_json=(json.dumps(before, sort_keys=True, separators=(',', ':'))
                             if isinstance(before, (dict, list)) else before),
                provider_record_id=provider_record_id, source=source,
                result=result, error=error, dns_provider_config_id=config_id)
            db.session.add(row)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning('Failed to record DNS change: %s', e)
            return None

        if result == 'error':
            DnsChangeService._notify_failure(row)
        return row

    @staticmethod
    def _notify_failure(row):
        """Surface a failed provider write to admins (best-effort)."""
        try:
            from app.plugins_sdk import notify
            notify.send('dns.sync_failed', to='admins', data={
                'record': f'{row.record_type or ""} {row.name or ""}'.strip(),
                'zone': row.provider_zone_id,
                'provider': row.provider,
                'action': row.action,
                'error': row.error or 'unknown error',
            }, severity='warning', category='system')
        except Exception as e:
            logger.warning('DNS failure notification skipped: %s', e)

    @staticmethod
    def list(config_id=None, provider_zone_id=None, result=None, limit=100):
        q = DnsChange.query
        if config_id:
            q = q.filter_by(dns_provider_config_id=config_id)
        if provider_zone_id:
            q = q.filter_by(provider_zone_id=provider_zone_id)
        if result:
            q = q.filter_by(result=result)
        return q.order_by(DnsChange.created_at.desc(), DnsChange.id.desc()).limit(limit).all()
