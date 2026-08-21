"""Authorization-first context attachments for the in-panel AI assistant.

An attachment is a reference (``type`` + stable ``id``), never a client-sent
resource dump. The resolver registered for that type reloads the resource for
the current user on every turn and returns a compact allowlisted summary. This
keeps stale permissions, deleted rows, and secret-bearing model serializers out
of the model prompt.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable

from app.utils.sensitive_data_filter import mask_payload

logger = logging.getLogger(__name__)

MAX_ATTACHMENTS = 8
MAX_CONTEXT_CHARS = 12_000
MAX_REFERENCE_ID_CHARS = 128
MAX_LABEL_CHARS = 160
_TYPE_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')


class AttachmentValidationError(ValueError):
    """The submitted attachment manifest is malformed or exceeds its cap."""


class AttachmentDeniedError(PermissionError):
    """The current caller cannot read the referenced resource."""


class AttachmentNotFoundError(LookupError):
    """The referenced resource no longer exists."""


Resolver = Callable[[Any, str], dict]


class AiAttachmentRegistry:
    """Type-keyed resolver registry with plugin ownership and teardown."""

    def __init__(self):
        self._resolvers: dict[str, tuple[Resolver, str | None]] = {}
        self._lock = RLock()

    def register(self, attachment_type: str, resolver: Resolver, *,
                 plugin_slug: str | None = None, replace: bool = False):
        attachment_type = _clean_type(attachment_type)
        if not callable(resolver):
            raise ValueError('AI attachment resolver must be callable')
        if plugin_slug and not attachment_type.startswith(f'{plugin_slug}.'):
            raise ValueError('plugin attachment types must be namespaced by plugin slug')
        with self._lock:
            if attachment_type in self._resolvers and not replace:
                raise ValueError(
                    f'AI attachment resolver for {attachment_type!r} already exists'
                )
            self._resolvers[attachment_type] = (resolver, plugin_slug)
        return resolver

    def get(self, attachment_type: str):
        with self._lock:
            entry = self._resolvers.get(attachment_type)
        return entry[0] if entry else None

    def types(self):
        with self._lock:
            return sorted(self._resolvers)

    def unregister_plugin(self, plugin_slug: str):
        with self._lock:
            doomed = [kind for kind, (_, owner) in self._resolvers.items()
                      if owner == plugin_slug]
            for kind in doomed:
                self._resolvers.pop(kind, None)

    def clear(self):
        """Drop registrations. Tests only; boot registration is idempotent."""
        with self._lock:
            self._resolvers.clear()


ai_attachment_registry = AiAttachmentRegistry()


def normalize_references(references) -> list[dict]:
    if references in (None, []):
        return []
    if not isinstance(references, list):
        raise AttachmentValidationError('attachments must be a list')
    if len(references) > MAX_ATTACHMENTS:
        raise AttachmentValidationError(
            f'attachments may contain at most {MAX_ATTACHMENTS} items'
        )

    normalized = []
    seen = set()
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            raise AttachmentValidationError(f'attachment {index} must be an object')
        try:
            attachment_type = _clean_type(reference.get('type'))
        except ValueError as exc:
            raise AttachmentValidationError(f'attachment {index}: {exc}') from exc
        resource_id = str(reference.get('id') or '').strip()
        if not resource_id or len(resource_id) > MAX_REFERENCE_ID_CHARS:
            raise AttachmentValidationError(
                f'attachment {index} requires an id up to {MAX_REFERENCE_ID_CHARS} characters'
            )
        key = (attachment_type, resource_id)
        if key in seen:
            continue
        seen.add(key)
        label = str(reference.get('label') or '').strip()[:MAX_LABEL_CHARS] or None
        normalized.append({'type': attachment_type, 'id': resource_id, 'label': label})
    return normalized


def resolve_attachments(user, references, *, registry=None) -> dict:
    """Resolve references into a safe manifest, model context, and warnings."""
    registry = registry or ai_attachment_registry
    normalized = normalize_references(references)
    manifest = []
    context = []
    warnings = []
    used_chars = 0

    for reference in normalized:
        attachment_type = reference['type']
        resource_id = reference['id']
        resolver = registry.get(attachment_type)
        if resolver is None:
            warning = _warning(reference, 'unknown', 'Attachment type is not supported')
            warnings.append(warning)
            manifest.append(_manifest(reference, 'unknown'))
            _audit_resolution(user, reference, 'unknown')
            continue

        try:
            resolved = _clean_resolution(resolver(user, resource_id))
        except AttachmentDeniedError:
            warnings.append(_warning(reference, 'denied', 'Access to this attachment was denied'))
            manifest.append(_manifest(reference, 'denied'))
            _audit_resolution(user, reference, 'denied')
            continue
        except AttachmentNotFoundError:
            warnings.append(_warning(reference, 'stale', 'Attachment no longer exists'))
            manifest.append(_manifest(reference, 'stale'))
            continue
        except Exception:
            logger.exception('AI attachment resolver failed for %s', attachment_type)
            warnings.append(_warning(reference, 'unavailable', 'Attachment could not be resolved'))
            manifest.append(_manifest(reference, 'unavailable'))
            continue

        item = {
            'type': attachment_type,
            'id': resource_id,
            'source': resolved['source'],
            'label': resolved['label'],
            'observed_at': resolved['observed_at'],
            # Even trusted core/plugin resolvers pass through unconditional
            # key-based masking before model context is assembled.
            'summary': mask_payload(resolved['summary']),
        }
        encoded_size = len(json.dumps(item, ensure_ascii=False, default=str))
        if used_chars + encoded_size > MAX_CONTEXT_CHARS:
            warnings.append(_warning(
                reference, 'omitted', 'Attachment context limit reached',
            ))
            manifest.append(_manifest(reference, 'omitted', label=resolved['label']))
            continue
        used_chars += encoded_size
        context.append(item)
        manifest.append(_manifest(
            reference,
            'resolved',
            label=resolved['label'],
            observed_at=resolved['observed_at'],
            source=resolved['source'],
        ))

    return {'manifest': manifest, 'context': context, 'warnings': warnings}


def register_builtin_attachment_resolvers():
    """Register the core ResourcePicker entity types, idempotently."""
    builtins = {
        'service': _resolve_service,
        'server': _resolve_server,
        'project': _resolve_project,
        'environment': _resolve_environment,
        'domain': _resolve_domain,
        'incident': _resolve_incident,
    }
    for attachment_type, resolver in builtins.items():
        ai_attachment_registry.register(
            attachment_type, resolver, replace=True,
        )


def _clean_type(value):
    attachment_type = str(value or '').strip().lower()
    if not _TYPE_RE.fullmatch(attachment_type):
        raise ValueError('attachment type is invalid')
    return attachment_type


def _clean_resolution(resolved):
    if not isinstance(resolved, dict) or not isinstance(resolved.get('summary'), dict):
        raise ValueError('attachment resolver returned an invalid summary')
    label = str(resolved.get('label') or '').strip()[:MAX_LABEL_CHARS]
    if not label:
        raise ValueError('attachment resolver returned no label')
    return {
        'label': label,
        'source': str(resolved.get('source') or 'ServerKit').strip()[:80],
        'observed_at': str(resolved.get('observed_at') or _now()),
        'summary': resolved['summary'],
    }


def _manifest(reference, status, *, label=None, observed_at=None, source=None):
    return {
        'type': reference['type'],
        'id': reference['id'],
        'label': label or reference.get('label'),
        'status': status,
        'source': source,
        'observed_at': observed_at,
    }


def _warning(reference, status, message):
    return {
        'type': reference['type'],
        'id': reference['id'],
        'status': status,
        'message': message,
    }


def _audit_resolution(user, reference, reason):
    """Audit identity and reason only; never record labels or resolver data."""
    try:
        from app.services.audit_service import AuditService
        AuditService.log(
            action=f'ai.attachment.{reason}',
            user_id=getattr(user, 'id', None),
            target_type='ai_attachment',
            details={'attachment_type': reference['type'], 'reason': reason},
        )
    except Exception:
        logger.warning('Failed to audit AI attachment %s', reason, exc_info=True)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _stamp(row):
    value = getattr(row, 'updated_at', None) or getattr(row, 'created_at', None)
    return value.isoformat() if value else _now()


def _parse_int(resource_id):
    try:
        return int(resource_id)
    except (TypeError, ValueError) as exc:
        raise AttachmentNotFoundError from exc


def _workspace_access(user, workspace_id):
    if getattr(user, 'is_admin', False):
        return True
    if workspace_id is None:
        return False
    from app.services.workspace_service import WorkspaceService
    return WorkspaceService.get_user_role(workspace_id, user.id) is not None


def _resolve_service(user, resource_id):
    from app.middleware.rbac import app_access_tier
    from app.models.application import Application

    row = Application.query_active().filter_by(id=_parse_int(resource_id)).first()
    if row is None:
        raise AttachmentNotFoundError
    if app_access_tier(user, row) is None:
        raise AttachmentDeniedError
    return {
        'label': row.name,
        'source': 'ServerKit service inventory',
        'observed_at': _stamp(row),
        'summary': {
            'name': row.name,
            'application_type': row.app_type,
            'status': row.status,
            'workspace_id': row.workspace_id,
            'project_id': row.project_id,
            'environment_id': row.environment_id,
            'port': row.port,
        },
    }


def _resolve_server(user, resource_id):
    from app.models.server import Server

    row = Server.query.filter_by(id=resource_id).first()
    if row is None:
        raise AttachmentNotFoundError
    # Servers are a global authenticated read surface today, matching search.
    return {
        'label': row.name or row.hostname or resource_id,
        'source': 'ServerKit server inventory',
        'observed_at': _stamp(row),
        'summary': {
            'name': row.name,
            'hostname': row.hostname,
            'status': row.status,
            'last_seen': row.last_seen.isoformat() if row.last_seen else None,
            'operating_system': row.os_type,
            'os_version': row.os_version,
            'architecture': row.architecture,
            'cpu_cores': row.cpu_cores,
            'total_memory_bytes': row.total_memory,
            'total_disk_bytes': row.total_disk,
            'docker_version': row.docker_version,
            'tags': list(row.tags or []),
        },
    }


def _resolve_project(user, resource_id):
    from app.models.project import Project

    row = Project.query.filter_by(id=_parse_int(resource_id)).first()
    if row is None:
        raise AttachmentNotFoundError
    if not _workspace_access(user, row.workspace_id):
        raise AttachmentDeniedError
    return {
        'label': row.name,
        'source': 'ServerKit project inventory',
        'observed_at': _stamp(row),
        'summary': {
            'name': row.name,
            'description': (row.description or '')[:1000],
            'workspace_id': row.workspace_id,
            'environment_count': row.environments.count(),
        },
    }


def _resolve_environment(user, resource_id):
    from app.models.environment import Environment

    row = Environment.query.filter_by(id=_parse_int(resource_id)).first()
    if row is None:
        raise AttachmentNotFoundError
    project = row.project
    if project is None or not _workspace_access(user, project.workspace_id):
        raise AttachmentDeniedError
    return {
        'label': row.name,
        'source': 'ServerKit environment inventory',
        'observed_at': _stamp(row),
        'summary': {
            'name': row.name,
            'project_id': row.project_id,
            'project_name': project.name,
            'workspace_id': project.workspace_id,
            'is_default': bool(row.is_default),
        },
    }


def _resolve_domain(user, resource_id):
    from app.middleware.rbac import app_access_tier
    from app.models.domain import Domain

    row = Domain.query_active().filter_by(id=_parse_int(resource_id)).first()
    if row is None:
        raise AttachmentNotFoundError
    if row.application is None or app_access_tier(user, row.application) is None:
        raise AttachmentDeniedError
    return {
        'label': row.name,
        'source': 'ServerKit domain inventory',
        'observed_at': _stamp(row),
        'summary': {
            'name': row.name,
            'application_id': row.application_id,
            'application_name': row.application.name,
            'is_primary': bool(row.is_primary),
            'ssl_enabled': bool(row.ssl_enabled),
            'ssl_expires_at': (
                row.ssl_expires_at.isoformat() if row.ssl_expires_at else None
            ),
            'ssl_auto_renew': bool(row.ssl_auto_renew),
        },
    }


def _resolve_incident(user, resource_id):
    from app.models.status_page import StatusIncident

    row = StatusIncident.query.filter_by(id=_parse_int(resource_id)).first()
    if row is None:
        raise AttachmentNotFoundError
    return {
        'label': row.title,
        'source': 'ServerKit incident ledger',
        'observed_at': _stamp(row),
        'summary': {
            'title': row.title,
            'status': row.status,
            'impact': row.impact,
            'is_maintenance': bool(row.is_maintenance),
            'scheduled_start': (
                row.scheduled_start.isoformat() if row.scheduled_start else None
            ),
            'scheduled_end': (
                row.scheduled_end.isoformat() if row.scheduled_end else None
            ),
            'resolved_at': row.resolved_at.isoformat() if row.resolved_at else None,
        },
    }
