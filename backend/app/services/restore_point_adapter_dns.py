"""Restore-point adapter for panel-owned provider DNS records.

The checkpoint intentionally reads only ``ManagedDnsRecord``. Provider-only
records remain outside coverage and are never adopted by a restore. Replay
uses ``DnsOwnershipService`` so the same foreign-record protection guards
ordinary writes and restores.
"""
from app.models.dns_zone import DNSZone
from app.models.email import DNSProviderConfig
from app.models.managed_dns_record import ManagedDnsRecord
from app.services.dns.base import DnsCredential, DnsRecordSpec
from app.services.dns_ownership_service import (
    DnsOwnershipService,
    parse_dns_scope_id,
)


def _validate_scope(scope_id, server_id=None):
    if server_id is not None:
        raise ValueError('Remote DNS restore points are not supported')
    return parse_dns_scope_id(scope_id)


def _query(provider, config_id, provider_zone_id):
    query = ManagedDnsRecord.query.filter_by(
        provider=provider,
        provider_zone_id=provider_zone_id,
    )
    if config_id is None:
        query = query.filter(ManagedDnsRecord.dns_provider_config_id.is_(None))
    else:
        query = query.filter_by(dns_provider_config_id=config_id)
    return query


def _record_payload(row):
    return DnsOwnershipService.record_payload(row)


def capture(scope_id, server_id=None):
    """Capture exactly the managed ledger rows for one provider connection/zone."""
    provider, config_id, provider_zone_id = _validate_scope(scope_id, server_id)
    rows = _query(provider, config_id, provider_zone_id).order_by(
        ManagedDnsRecord.record_type,
        ManagedDnsRecord.name,
        ManagedDnsRecord.id,
    ).all()
    return {
        'provider': provider,
        'config_id': config_id,
        'provider_zone_id': provider_zone_id,
        'records': [_record_payload(row) for row in rows],
    }


def _record_map(payload, *, expected_scope=None):
    if not isinstance(payload, dict):
        raise ValueError('DNS restore payload must be an object')
    required = ('provider', 'config_id', 'provider_zone_id', 'records')
    if any(key not in payload for key in required):
        raise ValueError('DNS restore payload is incomplete')

    if expected_scope is not None:
        provider, config_id, provider_zone_id = expected_scope
        if (
            str(payload.get('provider')).lower() != provider
            or payload.get('config_id') != config_id
            or str(payload.get('provider_zone_id')) != provider_zone_id
        ):
            raise ValueError('DNS restore payload belongs to a different scope')

    records = payload.get('records')
    if not isinstance(records, list):
        raise ValueError('DNS restore payload.records must be a list')

    out = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValueError('DNS restore records must be objects')
        record_type = str(item.get('record_type') or '').upper()
        name = str(item.get('name') or '').lower().rstrip('.')
        if not record_type or not name or item.get('content') is None:
            raise ValueError('DNS restore record requires type, name, and content')
        key = (record_type, name)
        if key in out:
            raise ValueError(f'DNS restore payload repeats RRset {record_type} {name}')
        normalized = {
            'record_type': record_type,
            'name': name,
            'content': str(item.get('content')),
            'ttl': item.get('ttl'),
            'priority': item.get('priority'),
            'proxied': item.get('proxied'),
            'source': item.get('source'),
            'app_id': item.get('app_id'),
        }
        if normalized['proxied'] not in (None, True, False):
            raise ValueError(
                f'DNS restore record {record_type} {name} has invalid proxy state',
            )
        try:
            normalized['ttl'] = (int(normalized['ttl'])
                                 if normalized['ttl'] is not None else None)
            normalized['priority'] = (
                int(normalized['priority'])
                if normalized['priority'] is not None else None
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f'DNS restore record {record_type} {name} has invalid numeric fields',
            ) from exc
        out[key] = normalized
    return out


def _display_key(key):
    return f'{key[0]} {key[1]}'


def diff(old_payload, new_payload):
    """Return the common added/removed/changed vocabulary per DNS RRset."""
    old = _record_map(old_payload)
    new = _record_map(new_payload)
    old_keys = set(old)
    new_keys = set(new)
    return {
        'added': {
            _display_key(key): new[key] for key in sorted(new_keys - old_keys)
        },
        'removed': {
            _display_key(key): old[key] for key in sorted(old_keys - new_keys)
        },
        'changed': {
            _display_key(key): {'old': old[key], 'new': new[key]}
            for key in sorted(old_keys & new_keys)
            if old[key] != new[key]
        },
    }


def _legacy_credential(provider, provider_zone_id):
    zone = DNSZone.query.filter_by(
        provider=provider,
        provider_zone_id=provider_zone_id,
        dns_provider_config_id=None,
    ).first()
    if zone is None:
        raise ValueError('Legacy DNS zone credential not found')
    data = zone.provider_config or {}
    token = data.get('api_token') or data.get('api_key') or data.get('token')
    if not token:
        raise ValueError('Legacy DNS zone has no usable credential')
    return DnsCredential(
        provider=provider,
        token=token,
        email=data.get('api_email') or data.get('email'),
        secret=data.get('api_secret') or data.get('secret'),
    )


def _client_for_scope(provider, config_id, provider_zone_id):
    from app.services.dns import get_record_client

    if config_id is None:
        credential = _legacy_credential(provider, provider_zone_id)
    else:
        config = DNSProviderConfig.query.get(config_id)
        if config is None:
            raise ValueError(f'DNS provider connection {config_id} not found')
        if config.provider.lower() != provider:
            raise ValueError('DNS provider connection does not match restore scope')
        credential = DnsCredential.from_provider_config(config)
    return get_record_client(credential)


def _existing_id(client, provider_zone_id, record):
    caa = None
    if record['record_type'] == 'CAA':
        from app.services.dns.cloudflare import parse_caa_value
        caa = parse_caa_value(record['content'])
    return client.find_record_id(
        provider_zone_id, record['record_type'], record['name'], caa=caa,
    )


def _foreign_conflicts(client, provider, config_id, provider_zone_id,
                       target, current_rows):
    """Preflight every target before the first write to avoid partial replay."""
    conflicts = []
    existing_ids = {}
    for key, record in sorted(target.items()):
        existing_id = _existing_id(client, provider_zone_id, record)
        existing_ids[key] = existing_id
        if not existing_id:
            continue
        row = current_rows.get(key)
        owns_id = DnsOwnershipService.owns(
            provider_zone_id, provider_record_id=existing_id,
            provider=provider, config_id=config_id,
        )
        if not owns_id and not (row is not None and not row.provider_record_id):
            conflicts.append(_display_key(key))
    return conflicts, existing_ids


def _live_record_map(client, provider_zone_id):
    result = client.list_records(provider_zone_id)
    if not result.get('success'):
        raise RuntimeError(
            result.get('error') or 'Provider live DNS records are unavailable',
        )
    out = {}
    for row in result.get('records', []):
        key = (
            str(row.get('type') or '').upper(),
            str(row.get('name') or '').lower().rstrip('.'),
        )
        if key[0] and key[1]:
            out.setdefault(key, row)
    return out


def _prepare_target(client, provider, provider_zone_id, target):
    """Hydrate nullable migration-092 fields without fabricating live state."""
    needs_live = any(
        item.get('ttl') is None
        or (provider == 'cloudflare' and item.get('proxied') is None)
        or (
            item.get('record_type') in ('MX', 'SRV')
            and item.get('priority') is None
            and not str(item.get('content') or '').partition(' ')[0].isdigit()
        )
        for item in target.values()
    )
    live = {}
    if needs_live:
        try:
            live = _live_record_map(client, provider_zone_id)
        except Exception as exc:  # noqa: BLE001 - preview should explain refusal
            return target, [
                'Legacy DNS record attributes are unknown and live provider '
                f'state could not be read safely: {exc}',
            ]

    prepared = {}
    refusals = []
    for key, original in target.items():
        item = dict(original)
        live_row = live.get(key)

        if item.get('ttl') is None:
            if live_row is None or live_row.get('ttl') is None:
                refusals.append(
                    f'{_display_key(key)} has unknown legacy TTL and no live '
                    'provider value; restore cannot safely invent one.'
                )
            else:
                item['ttl'] = int(live_row['ttl'])

        if provider == 'cloudflare' and item.get('proxied') is None:
            if live_row is None or live_row.get('proxied') is None:
                refusals.append(
                    f'{_display_key(key)} has unknown legacy proxy state and '
                    'no live provider value; restore cannot safely disable it.'
                )
            else:
                item['proxied'] = bool(live_row['proxied'])

        if (
            item['record_type'] in ('MX', 'SRV')
            and item.get('priority') is None
            and not item['content'].partition(' ')[0].isdigit()
        ):
            if live_row is None or live_row.get('priority') is None:
                refusals.append(
                    f'{_display_key(key)} has unknown legacy priority and no '
                    'live provider value; restore cannot safely invent one.'
                )
            else:
                item['priority'] = int(live_row['priority'])

        prepared[key] = item
    return prepared, refusals


def _canonical_live_content(record_type, content):
    value = str(content or '').strip()
    if record_type in ('CNAME', 'MX', 'NS', 'PTR', 'SRV'):
        return value.rstrip('.').lower()
    if record_type == 'CAA':
        return value.lower()
    return value


def _content_and_priority(record_type, content, priority):
    value = str(content or '').strip()
    effective_priority = priority
    if record_type in ('MX', 'SRV') and effective_priority is None:
        head, _, rest = value.partition(' ')
        if head.isdigit() and rest.strip():
            effective_priority = int(head)
            value = rest.strip()
    return _canonical_live_content(record_type, value), effective_priority


def _synthetic_delete_matches(row, live_row):
    ledger_content, ledger_priority = _content_and_priority(
        row.record_type, row.content, row.priority,
    )
    live_content, live_priority = _content_and_priority(
        row.record_type, live_row.get('content'), live_row.get('priority'),
    )
    if (
        ledger_content != live_content
    ):
        return False
    comparisons = (
        ('ttl', row.ttl),
        ('priority', ledger_priority),
        ('proxied', row.proxied),
    )
    for key, expected in comparisons:
        actual = live_priority if key == 'priority' else live_row.get(key)
        if expected is not None and actual is not None and expected != actual:
            return False
    return True


def _delete_refusals(client, provider, provider_zone_id, target, current_rows):
    """Never delete a provider-side replacement merely because its RRset is ours."""
    delete_keys = sorted(set(current_rows) - set(target))
    if not delete_keys:
        return []
    try:
        live = _live_record_map(client, provider_zone_id)
    except Exception as exc:  # noqa: BLE001 - inability to prove safety refuses
        return [
            'Provider live DNS state could not be read, so restore cannot '
            f'safely delete managed records: {exc}',
        ]

    refusals = []
    stable_id_provider = provider in ('cloudflare', 'digitalocean')
    for key in delete_keys:
        row = current_rows[key]
        live_row = live.get(key)
        if live_row is None:
            continue
        if stable_id_provider and row.provider_record_id:
            if str(live_row.get('id')) != str(row.provider_record_id):
                refusals.append(
                    f'Restore would delete provider-only replacement '
                    f'{_display_key(key)}; its provider id no longer matches.'
                )
        elif not _synthetic_delete_matches(row, live_row):
            refusals.append(
                f'Restore would delete provider-only replacement '
                f'{_display_key(key)}; its live value no longer matches the ledger.'
            )
    return refusals


def validate_restore(scope_id, payload, current_payload, actor=None,
                     server_id=None):
    """Surface foreign-record refusals during preview, before restore is offered."""
    del actor, current_payload
    scope = _validate_scope(scope_id, server_id)
    provider, config_id, provider_zone_id = scope
    target = _record_map(payload, expected_scope=scope)
    client = _client_for_scope(provider, config_id, provider_zone_id)
    current_rows = {
        ((row.record_type or '').upper(), (row.name or '').lower().rstrip('.')): row
        for row in _query(provider, config_id, provider_zone_id).all()
    }
    _, attribute_refusals = _prepare_target(
        client, provider, provider_zone_id, target,
    )
    conflicts, _ = _foreign_conflicts(
        client, provider, config_id, provider_zone_id, target, current_rows,
    )
    delete_refusals = _delete_refusals(
        client, provider, provider_zone_id, target, current_rows,
    )
    return attribute_refusals + delete_refusals + [
        'Restore would overwrite provider-only DNS record '
        f'{record}; it was not created by ServerKit.'
        for record in conflicts
    ]


def restore(scope_id, payload, actor=None, server_id=None):
    """Re-converge owned RRsets while refusing to touch provider-only records."""
    del actor  # Generic restore auditing owns actor attribution.
    scope = _validate_scope(scope_id, server_id)
    provider, config_id, provider_zone_id = scope
    target = _record_map(payload, expected_scope=scope)
    client = _client_for_scope(provider, config_id, provider_zone_id)

    current_rows = {
        ((row.record_type or '').upper(), (row.name or '').lower().rstrip('.')): row
        for row in _query(provider, config_id, provider_zone_id).all()
    }
    target, attribute_refusals = _prepare_target(
        client, provider, provider_zone_id, target,
    )
    conflicts, existing_ids = _foreign_conflicts(
        client, provider, config_id, provider_zone_id, target, current_rows,
    )
    delete_refusals = _delete_refusals(
        client, provider, provider_zone_id, target, current_rows,
    )
    if conflicts or attribute_refusals or delete_refusals:
        errors = list(attribute_refusals) + list(delete_refusals)
        if conflicts:
            errors.append(
                'Restore refused to overwrite provider-only DNS records: '
                + ', '.join(conflicts)
            )
        return {
            'success': False,
            'conflict': bool(conflicts),
            'refused': True,
            'error': '; '.join(errors),
            'conflicts': conflicts,
        }

    restored = []
    removed = []
    results = []

    for key in sorted(target):
        item = target[key]
        # The ledger is the capture source, not proof that provider live state
        # still matches. Always send the idempotent guarded upsert so deleted or
        # drifted managed records are repaired during restore.
        spec = DnsRecordSpec(
            record_type=item['record_type'],
            name=item['name'],
            content=item['content'],
            ttl=item['ttl'],
            priority=item['priority'],
            proxied=item['proxied'],
        )
        result = DnsOwnershipService.guarded_upsert(
            client, provider=provider, provider_zone_id=provider_zone_id,
            spec=spec, source=item.get('source') or 'restore',
            app_id=item.get('app_id'), config_id=config_id,
            # Provider live state, not the ledger, decides whether an id is
            # still usable. A stale id must become a create, never a PUT to a
            # provider-deleted object.
            known_record_id=existing_ids.get(key),
            allow_foreign=False,
        )
        results.append({'action': 'upsert', 'record': _display_key(key), **result})
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'DNS restore upsert failed'),
                'results': results,
            }
        restored.append(_display_key(key))

    for key in sorted(set(current_rows) - set(target)):
        row = current_rows[key]
        result = DnsOwnershipService.guarded_delete(
            client, provider=provider, provider_zone_id=provider_zone_id,
            record_type=row.record_type, name=row.name,
            provider_record_id=row.provider_record_id,
            source='restore', config_id=config_id,
        )
        results.append({'action': 'delete', 'record': _display_key(key), **result})
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'DNS restore delete failed'),
                'results': results,
            }
        removed.append(_display_key(key))

    return {
        'success': True,
        'scope_id': scope_id,
        'restored': restored,
        'removed': removed,
        'results': results,
    }
