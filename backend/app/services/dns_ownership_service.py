"""Ownership ledger + the never-touch-foreign guard for provider DNS writes.

Every record ServerKit creates through a connected provider is recorded in
``managed_dns_records``. Before the panel overwrites or deletes a provider record
it checks this ledger, so it never mutates a record the *user* created themselves
(their pre-existing "Maria & Pedro" records).

Two guard postures:

* **Automatic paths** (WordPress auto-DNS, wildcard setup, email) call with
  ``allow_foreign=False`` — they refuse to touch a record we didn't create.
* **Explicit management** (the /dns Zones page, where the user is deliberately
  editing their own zone) calls with ``allow_foreign=True`` — it adopts the
  existing record and records ownership from then on.
"""
import logging

from app import db
from app.models.managed_dns_record import ManagedDnsRecord

logger = logging.getLogger(__name__)

_UNSET = object()
LEGACY_DNS_CONFIG = 'legacy'


def dns_scope_id(provider, config_id, provider_zone_id):
    """Stable restore-point scope: provider:config-or-legacy:zone."""
    config_key = LEGACY_DNS_CONFIG if config_id is None else str(config_id)
    return f'{str(provider).lower()}:{config_key}:{provider_zone_id}'


def parse_dns_scope_id(scope_id):
    """Return ``(provider, config_id|None, provider_zone_id)``."""
    try:
        provider, config_key, provider_zone_id = str(scope_id).split(':', 2)
    except ValueError as exc:
        raise ValueError('DNS scope must be provider:config-or-legacy:zone') from exc
    if not provider or not provider_zone_id:
        raise ValueError('DNS scope must include provider and zone')
    if config_key == LEGACY_DNS_CONFIG:
        config_id = None
    else:
        try:
            config_id = int(config_key)
        except (TypeError, ValueError) as exc:
            raise ValueError('DNS scope has an invalid provider configuration') from exc
    return provider.lower(), config_id, provider_zone_id


class DnsOwnershipService:

    @staticmethod
    def scope_id(provider, config_id, provider_zone_id):
        return dns_scope_id(provider, config_id, provider_zone_id)

    @staticmethod
    def _scope_query(provider_zone_id, *, provider=None, config_id=_UNSET):
        query = ManagedDnsRecord.query.filter_by(
            provider_zone_id=provider_zone_id,
        )
        if provider is not None:
            query = query.filter_by(provider=str(provider).lower())
        if config_id is not _UNSET:
            if config_id is None:
                query = query.filter(ManagedDnsRecord.dns_provider_config_id.is_(None))
            else:
                query = query.filter_by(dns_provider_config_id=config_id)
        return query

    # ── ledger reads ─────────────────────────────────────────────────────────
    @staticmethod
    def _row(provider_zone_id, record_type, name, *, provider=None,
             config_id=_UNSET):
        """One owned RRset, scoped so identical provider zone ids cannot collide."""
        normalized_type = str(record_type or '').upper()
        normalized_name = str(name or '').lower().rstrip('.')
        query = DnsOwnershipService._scope_query(
            provider_zone_id, provider=provider, config_id=config_id,
        ).filter_by(record_type=normalized_type)
        return query.filter(
            db.func.lower(db.func.rtrim(ManagedDnsRecord.name, '.'))
            == normalized_name,
        ).first()

    @staticmethod
    def _row_by_id(provider_zone_id, provider_record_id, *, provider=None,
                   config_id=_UNSET):
        return DnsOwnershipService._scope_query(
            provider_zone_id, provider=provider, config_id=config_id,
        ).filter_by(provider_record_id=provider_record_id).first()

    @staticmethod
    def record_payload(row):
        """Complete managed DNS pre-image used by restore points/change rows."""
        if row is None:
            return None
        return {
            'record_type': row.record_type,
            'name': row.name,
            'content': row.content,
            'ttl': row.ttl,
            'priority': row.priority,
            'proxied': row.proxied,
            'source': row.source,
            'app_id': row.app_id,
        }

    @staticmethod
    def owns(provider_zone_id, *, provider_record_id=None, record_type=None,
             name=None, provider=None, config_id=_UNSET):
        """Whether ServerKit created the matching record (by provider record id, or
        by type+name)."""
        q = DnsOwnershipService._scope_query(
            provider_zone_id, provider=provider, config_id=config_id,
        )
        if provider_record_id:
            q = q.filter_by(provider_record_id=provider_record_id)
        elif record_type and name:
            return DnsOwnershipService._row(
                provider_zone_id, record_type, name,
                provider=provider, config_id=config_id,
            ) is not None
        else:
            return False
        return q.first() is not None

    @staticmethod
    def owned_keys(provider_zone_id, *, provider=None, config_id=_UNSET):
        """``(record_id set, (type, lower-name) set)`` for fast mirror classification."""
        rows = DnsOwnershipService._scope_query(
            provider_zone_id, provider=provider, config_id=config_id,
        ).all()
        ids = {r.provider_record_id for r in rows if r.provider_record_id}
        keys = {((r.record_type or '').upper(), (r.name or '').lower().rstrip('.'))
                for r in rows}
        return ids, keys

    @staticmethod
    def list_for_zone(provider_zone_id, *, provider=None, config_id=_UNSET):
        return DnsOwnershipService._scope_query(
            provider_zone_id, provider=provider, config_id=config_id,
        ).all()

    @staticmethod
    def list_all():
        return ManagedDnsRecord.query.order_by(
            ManagedDnsRecord.provider_zone_id, ManagedDnsRecord.name).all()

    # ── ledger writes ────────────────────────────────────────────────────────
    @staticmethod
    def record_write(provider, provider_zone_id, record_type, name, *,
                     provider_record_id=None, content=None, source=None,
                     app_id=None, config_id=None, ttl=None, priority=None,
                     proxied=None):
        provider = str(provider).lower()
        record_type = str(record_type).upper()
        name = str(name).lower().rstrip('.')
        row = DnsOwnershipService._row(
            provider_zone_id, record_type, name,
            provider=provider, config_id=config_id,
        )
        if row is None:
            row = ManagedDnsRecord(provider=provider, provider_zone_id=provider_zone_id,
                                   record_type=record_type, name=name)
            db.session.add(row)
        if provider_record_id:
            row.provider_record_id = provider_record_id
        row.content = content
        row.ttl = ttl
        row.priority = priority
        row.proxied = proxied
        if source:
            row.source = source
        if app_id is not None:
            row.app_id = app_id
        if config_id is not None:
            row.dns_provider_config_id = config_id
        db.session.commit()
        return row

    @staticmethod
    def record_delete(provider_zone_id, *, record_type=None, name=None,
                      provider_record_id=None, provider=None,
                      config_id=_UNSET):
        q = DnsOwnershipService._scope_query(
            provider_zone_id, provider=provider, config_id=config_id,
        )
        if provider_record_id:
            q = q.filter_by(provider_record_id=provider_record_id)
        elif record_type and name:
            normalized_name = str(name).lower().rstrip('.')
            q = q.filter_by(record_type=str(record_type).upper()).filter(
                db.func.lower(db.func.rtrim(ManagedDnsRecord.name, '.'))
                == normalized_name,
            )
        else:
            return 0
        n = q.delete()
        db.session.commit()
        return n

    # ── guarded provider writes ──────────────────────────────────────────────
    @staticmethod
    def guarded_upsert(client, *, provider, provider_zone_id, spec, source,
                       app_id=None, config_id=None, known_record_id=None,
                       allow_foreign=False):
        """Upsert via the provider client, refusing to overwrite a record ServerKit
        doesn't own (unless ``allow_foreign``), then record ownership on success.

        Returns the client result (``{success, record_id?, error?}``) with
        ``conflict=True`` when a foreign record blocked an automatic write.
        """
        from app.services.dns.cloudflare import parse_caa_value
        from app.services.dns_change_service import DnsChangeService
        from app.services.restore_point_service import auto_capture

        provider = str(provider).lower()
        spec.record_type = str(spec.record_type).upper()
        spec.name = str(spec.name).lower().rstrip('.')
        if spec.record_type in ('MX', 'SRV') and spec.priority is None:
            head, _, rest = str(spec.content or '').strip().partition(' ')
            if head.isdigit() and rest.strip():
                # Canonicalize once at the door so every provider and the
                # ownership ledger see complete, replayable priority data.
                spec.priority = int(head)
                spec.content = rest.strip()

        before_row = DnsOwnershipService._row(
            provider_zone_id, spec.record_type, spec.name,
            provider=provider, config_id=config_id,
        )
        before = DnsOwnershipService.record_payload(before_row)

        record_id = known_record_id
        if record_id is None:
            caa = parse_caa_value(spec.content) if spec.record_type == 'CAA' else None
            existing = client.find_record_id(
                provider_zone_id, spec.record_type, spec.name, caa=caa,
            )
            if existing:
                owns_existing_id = DnsOwnershipService.owns(
                    provider_zone_id, provider_record_id=existing,
                    provider=provider, config_id=config_id,
                )
                owns_rrset_without_id = (
                    before_row is not None and not before_row.provider_record_id
                )
                if owns_existing_id or owns_rrset_without_id:
                    record_id = existing            # ours — update in place
                elif allow_foreign:
                    record_id = existing            # explicit management — adopt it
                else:
                    logger.warning('Refusing to overwrite foreign DNS record %s %s in zone %s',
                                   spec.record_type, spec.name, provider_zone_id)
                    msg = (f'{spec.record_type} record {spec.name} already exists in this zone '
                           f'and was not created by ServerKit — left untouched.')
                    DnsChangeService.record(
                        provider=provider, provider_zone_id=provider_zone_id, action='create',
                        record_type=spec.record_type, name=spec.name, content=spec.content,
                        source=source, result='conflict', error=msg,
                        config_id=config_id, before=before)
                    return {'success': False, 'conflict': True, 'error': msg}

        action = 'update' if record_id or before_row is not None else 'create'
        auto_capture(
            'dns', dns_scope_id(provider, config_id, provider_zone_id),
            f'upsert {spec.record_type} {spec.name}',
        )
        res = client.upsert(provider_zone_id, spec, record_id=record_id)
        if res.get('success'):
            DnsOwnershipService.record_write(
                provider, provider_zone_id, spec.record_type, spec.name,
                provider_record_id=res.get('record_id'), content=spec.content,
                source=source, app_id=app_id, config_id=config_id,
                ttl=spec.ttl, priority=spec.priority, proxied=spec.proxied)
        DnsChangeService.record(
            provider=provider, provider_zone_id=provider_zone_id, action=action,
            record_type=spec.record_type, name=spec.name, content=spec.content,
            provider_record_id=res.get('record_id'), source=source,
            result='ok' if res.get('success') else 'error',
            error=None if res.get('success') else res.get('error'),
            config_id=config_id, before=before)
        return res

    @staticmethod
    def guarded_delete(client, *, provider_zone_id, record_type, name, provider_record_id=None,
                       provider='cloudflare', source=None, config_id=None):
        """Delete only a record ServerKit owns; never a foreign one. Clears our
        ledger entry and logs the change on success."""
        from app.services.dns_change_service import DnsChangeService
        from app.services.restore_point_service import auto_capture

        provider = str(provider).lower()
        if provider_record_id:
            owned_row = DnsOwnershipService._row_by_id(
                provider_zone_id, provider_record_id,
                provider=provider, config_id=config_id,
            )
        else:
            owned_row = DnsOwnershipService._row(
                provider_zone_id, record_type, name,
                provider=provider, config_id=config_id,
            )
        if owned_row is None:
            return {'success': True, 'skipped': True,
                    'message': 'No ServerKit-owned record to delete.'}

        before = DnsOwnershipService.record_payload(owned_row)
        provider_record_id = provider_record_id or owned_row.provider_record_id
        auto_capture(
            'dns', dns_scope_id(provider, config_id, provider_zone_id),
            f'delete {record_type} {name}',
        )
        res = client.delete(provider_zone_id, record_id=provider_record_id,
                            record_type=record_type, name=name)
        # A failed provider delete must keep ownership. Otherwise a transient
        # failure turns our still-live record into one ServerKit now sees as foreign.
        if res.get('success'):
            DnsOwnershipService.record_delete(
                provider_zone_id, record_type=record_type, name=name,
                provider_record_id=provider_record_id, provider=provider,
                config_id=config_id,
            )
        DnsChangeService.record(
            provider=provider, provider_zone_id=provider_zone_id, action='delete',
            record_type=record_type, name=name, provider_record_id=provider_record_id,
            source=source, result='ok' if res.get('success') else 'error',
            error=None if res.get('success') else res.get('error'),
            config_id=config_id, before=before)
        return res
