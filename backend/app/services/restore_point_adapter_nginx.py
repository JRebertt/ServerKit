"""Restore-point adapter for one local nginx vhost lifecycle."""

import os

from app.services.nginx_service import NginxService


def _validate_scope(scope_id, server_id):
    name = str(scope_id or '')
    if (
        not name
        or name in ('.', '..')
        or os.path.isabs(name)
        or os.path.basename(name) != name
        or '/' in name
        or '\\' in name
        or '\x00' in name
    ):
        raise ValueError('nginx vhost scope must be one safe filename')
    if server_id is not None:
        raise ValueError('Remote nginx vhost restore points are not supported')
    return name


def capture(scope_id, server_id=None):
    """Capture file existence, enablement, and exact vhost bytes.

    A present-but-unreadable file is not represented as an empty or absent
    vhost.  Refusing that capture prevents a later restore from deleting state
    that merely could not be observed.
    """
    name = _validate_scope(scope_id, server_id)
    available_path = os.path.join(NginxService.SITES_AVAILABLE, name)
    enabled_path = os.path.join(NginxService.SITES_ENABLED, name)
    exists = os.path.exists(available_path)
    content = NginxService.read_vhost(name) if exists else None
    if exists and content is None:
        raise RuntimeError(f'Existing nginx vhost {name} could not be read')
    return {
        'exists': exists,
        'enabled': os.path.exists(enabled_path),
        'content': content,
    }


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('nginx restore payload must be an object')
    if not isinstance(payload.get('exists'), bool):
        raise ValueError('nginx restore payload requires an exists flag')
    if not isinstance(payload.get('enabled'), bool):
        raise ValueError('nginx restore payload requires an enabled flag')
    content = payload.get('content')
    if payload['exists'] and not isinstance(content, str):
        raise ValueError('Existing nginx restore payload requires vhost content')
    return payload['exists'], payload['enabled'], content


def restore(scope_id, payload, actor=None, server_id=None):
    """Re-converge exclusively through nginx lifecycle service doors."""
    del actor  # Actor attribution belongs to the generic restore-point service.
    name = _validate_scope(scope_id, server_id)
    exists, enabled, content = _validate_payload(payload)

    if not exists:
        return NginxService.delete_site(name)

    written = NginxService.write_vhost(name, content, enable=enabled)
    if not written.get('success'):
        return written

    # write_vhost(enable=False) deliberately preserves a currently enabled
    # site.  A restore target is stronger: reproduce the captured enabled bit.
    if not enabled:
        disabled = NginxService.disable_site(name)
        if not disabled.get('success'):
            return disabled

    return {'success': True, 'message': f'nginx vhost {name} restored'}
