"""Generic restore-point lifecycle and adapter registry.

Adapters keep OS/provider knowledge out of this module.  Each adapter may be
an object or mapping with these members::

    capture(scope_id, server_id=None) -> JSON-serializable payload
    restore(scope_id, payload, actor=None, server_id=None) -> result
    diff(old_payload, new_payload) -> structured diff             # optional
    validate_restore(scope_id, payload, current_payload,
                     actor=None, server_id=None) -> refusals      # optional
    coverage -> list[str] or callable(scope_id, server_id=None)   # optional

Capture is deliberately best-effort: it returns ``None`` and logs when the
adapter or database cannot produce a checkpoint.  This preserves the existing
capture-before-mutation contract -- a checkpoint outage must not turn into a
configuration outage.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
import hashlib
import json
import logging

from sqlalchemy import and_, or_

from app import db
from app.exceptions import (
    ApplicationError,
    ConflictError,
    DependencyUnavailableError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30
DEFAULT_SCOPE_CAP = 50

BASE_COVERAGE = (
    'Secrets are stored masked and are never overwritten by a restore. '
    'State outside the panel (files on disk, provider-side records created '
    'elsewhere, container runtime state) is outside the checkpoint.'
)

SCOPE_COVERAGE = {
    'firewall': (
        'Persisted panel-supported UFW rules and firewalld service, port, and '
        'rich-rule families are part of this checkpoint, including matching '
        'rules created outside the panel. Other firewalld families, interfaces, '
        'sources, and runtime-only fail2ban/Docker chains are not captured.',
    ),
    'dns': (
        'Records that exist only at the provider and were never managed by '
        'the panel are not captured.',
    ),
    'nginx_vhost': (
        'Only panel-rendered vhosts are captured. Hand-edited files in '
        'sites-enabled are drift, not checkpoint content — see the Drift report.',
    ),
}


class RestorePointError(ValidationError):
    """Invalid restore-point operation (capture remains best-effort)."""

    code = 'restore_point_invalid'


class RestorePointNotFoundError(NotFoundError):
    code = 'restore_point_not_found'


class RestorePointAdapterError(DependencyUnavailableError):
    code = 'restore_point_adapter_unavailable'


class RestorePointCorruptError(ConflictError):
    code = 'restore_point_corrupt'


class RestorePointRefusedError(ConflictError):
    code = 'restore_point_refused'

    def __init__(self, refusals):
        self.refusals = list(refusals)
        super().__init__(
            'Restore refused by the surface safety check',
            details={'refusals': self.refusals},
        )


# scope_type -> adapter.  The alias is intentionally public for extensions and
# for registry introspection without coupling callers to the implementation.
ADAPTERS = {}
RESTORE_POINT_ADAPTERS = ADAPTERS

# Restore adapters deliberately replay through the ordinary mutation doors.
# Hooks at those doors call auto_capture(), so suppress only those automatic
# calls while a restore is replaying. Direct capture() remains available for
# the one deliberate pre-restore checkpoint.
_AUTO_CAPTURE_SUPPRESSED = ContextVar(
    'restore_point_auto_capture_suppressed', default=False,
)


def _member(adapter, name):
    if isinstance(adapter, dict):
        return adapter.get(name)
    return getattr(adapter, name, None)


def register_adapter(scope_type, adapter=None):
    """Register (or replace) an adapter; also supports decorator use."""
    if adapter is None:
        return lambda value: register_adapter(scope_type, value)
    if not scope_type:
        raise ValueError('scope_type is required')
    if not callable(_member(adapter, 'capture')):
        raise ValueError('restore-point adapter requires capture()')
    if not callable(_member(adapter, 'restore')):
        raise ValueError('restore-point adapter requires restore()')
    ADAPTERS[str(scope_type)] = adapter
    return adapter


def get_adapter(scope_type):
    return ADAPTERS.get(str(scope_type))


def clear_adapters():
    """Test/plugin-reload helper."""
    ADAPTERS.clear()


def auto_capture(scope_type, scope_id, action, label=None, actor=None,
                 server_id=None):
    """Best-effort pre-mutation capture for use at M2 mutation doors."""
    if _AUTO_CAPTURE_SUPPRESSED.get():
        return None
    action = str(action or 'mutation')
    if '.' not in action:
        action = f'{scope_type}.{action}'
    return capture(
        scope_type,
        scope_id,
        'pre_mutation',
        label=label or f'before {action}',
        actor=actor,
        server_id=server_id,
    )


@contextmanager
def suppress_auto_capture():
    """Suppress nested door hooks in this context, resetting even on error."""
    token = _AUTO_CAPTURE_SUPPRESSED.set(True)
    try:
        yield
    finally:
        _AUTO_CAPTURE_SUPPRESSED.reset(token)


def canonical_json(payload):
    """Match the proven DeploymentSnapshot canonical JSON construction."""
    return json.dumps(
        payload, sort_keys=True, separators=(',', ':'), default=str,
    )


def payload_hash(payload):
    return hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()


def _actor_id(actor):
    if actor is None:
        return None
    return getattr(actor, 'id', actor)


def _adapter_coverage(adapter, scope_type, scope_id, server_id):
    coverage = [BASE_COVERAGE]
    coverage.extend(SCOPE_COVERAGE.get(scope_type, ()))
    extra = _member(adapter, 'coverage')
    if callable(extra):
        extra = extra(scope_id, server_id=server_id)
    if isinstance(extra, str):
        extra = [extra]
    for statement in extra or ():
        if statement and statement not in coverage:
            coverage.append(statement)
    return coverage


def _retention_days():
    from app.services.settings_service import SettingsService

    value = SettingsService.get(
        'restore_point_retention_days', DEFAULT_RETENTION_DAYS,
    )
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def _capture_payload(adapter, scope_id, server_id):
    return _member(adapter, 'capture')(scope_id, server_id=server_id)


def _session_has_pending_changes():
    """Whether capture would accidentally own another service's unit of work."""
    session = db.session()
    return bool(session.new or session.dirty or session.deleted)


def _audit_capture(point):
    from app.models.audit_log import AuditLog
    from app.services.audit_service import AuditService

    AuditService.log(
        AuditLog.ACTION_RESTORE_POINT_CREATE,
        user_id=point.actor_user_id,
        target_type='restore_point',
        target_id=None,
        details={
            'restore_point_id': point.id,
            'server_id': point.server_id,
            'scope_type': point.scope_type,
            'scope_id': point.scope_id,
            'trigger': point.trigger,
            'label': point.label,
        },
        commit=False,
    )


def capture(scope_type, scope_id, trigger, label=None, actor=None,
            server_id=None):
    """Capture and dedupe one scope, returning a row or ``None`` on failure."""
    from app.models.restore_point import RestorePoint

    scope_type = str(scope_type or '')
    scope_id = str(scope_id or '')
    adapter = get_adapter(scope_type)
    if not scope_type or not scope_id or adapter is None:
        logger.warning(
            'Restore-point capture skipped for %s/%s: adapter not registered',
            scope_type or '?', scope_id or '?',
        )
        return None

    # capture() commits its point + audit atomically. Never let that commit (or
    # its failure rollback) absorb a caller's pending unit of work.
    if _session_has_pending_changes():
        logger.warning(
            'Restore-point capture skipped for %s/%s: caller transaction '
            'has pending changes', scope_type, scope_id,
        )
        return None

    owns_transaction = False
    try:
        payload = _capture_payload(adapter, scope_id, server_id)
        # Adapters are read-only during capture. If one dirtied the session,
        # leave its objects untouched for the caller and refuse the checkpoint.
        if _session_has_pending_changes():
            logger.warning(
                'Restore-point capture skipped for %s/%s: adapter left '
                'pending database changes', scope_type, scope_id,
            )
            return None
        owns_transaction = True

        if not isinstance(payload, dict):
            raise ValueError('restore-point adapter capture must return a mapping')

        canonical = canonical_json(payload)
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()

        latest = RestorePoint.latest_for_scope(
            scope_type, scope_id, server_id=server_id,
        )
        if latest and latest.payload_hash == digest:
            # A manual quicksave doubles as a retained tag. Dedupe must not
            # throw away that operator intent just because an automatic point
            # already captured the same bytes.
            if str(trigger) == 'manual':
                now = datetime.utcnow()
                latest.keep = True
                latest.trigger = 'manual'
                latest.actor_user_id = _actor_id(actor)
                if label and latest.label != str(label)[:255]:
                    latest.label = str(label)[:255]
                latest.created_at = now
                latest.updated_at = now
                _audit_capture(latest)
                db.session.commit()
            return latest

        now = datetime.utcnow()
        point = RestorePoint(
            server_id=server_id,
            scope_type=scope_type,
            scope_id=scope_id,
            trigger=str(trigger),
            label=str(label)[:255] if label else None,
            payload_hash=digest,
            payload_json=canonical,
            coverage_json=canonical_json(_adapter_coverage(
                adapter, scope_type, scope_id, server_id,
            )),
            actor_user_id=_actor_id(actor),
            expires_at=now + timedelta(days=_retention_days()),
            keep=str(trigger) == 'manual',
        )
        db.session.add(point)
        db.session.flush()  # uuid/defaults are available to the audit details
        _audit_capture(point)
        db.session.commit()
        return point
    except Exception as exc:  # noqa: BLE001 -- must never block the mutation
        # Before the clean post-adapter boundary, rollback could destroy work
        # the caller/adapter still owns. Once the boundary passes, every write
        # in this transaction belongs to restore-point capture.
        if owns_transaction:
            try:
                db.session.rollback()
            except Exception:  # pragma: no cover - defensive
                pass
        logger.warning(
            'Restore-point capture failed for %s/%s: %s',
            scope_type, scope_id, exc, exc_info=True,
        )
        return None


def _point_or_raise(point_id):
    from app.models.restore_point import RestorePoint

    point = db.session.get(RestorePoint, point_id)
    if point is None:
        raise RestorePointNotFoundError(f'Restore point {point_id} not found')
    return point


def _strict_payload(point):
    """Parse a stored payload without JsonColumnMixin's lossy fallback."""
    try:
        payload = json.loads(point.payload_json)
    except (TypeError, ValueError) as exc:
        raise RestorePointCorruptError(
            f'Restore point {point.id} has a corrupt payload',
            details={'restore_point_id': point.id},
        ) from exc
    if not isinstance(payload, dict):
        raise RestorePointCorruptError(
            f'Restore point {point.id} has a corrupt payload',
            details={'restore_point_id': point.id},
        )
    return payload


def _previous_point(point):
    from app.models.restore_point import RestorePoint

    earlier = or_(
        RestorePoint.created_at < point.created_at,
        and_(
            RestorePoint.created_at == point.created_at,
            RestorePoint.id < point.id,
        ),
    )
    return (RestorePoint.query.filter_by(
        server_id=point.server_id,
        scope_type=point.scope_type,
        scope_id=point.scope_id,
    ).filter(earlier)
        .order_by(RestorePoint.created_at.desc(), RestorePoint.id.desc())
        .first())


def diff_payloads(old, new):
    """Generic secret-safe diff over already-masked checkpoint payloads."""
    if isinstance(old, dict) and isinstance(new, dict):
        old_keys = set(old)
        new_keys = set(new)
        return {
            'added': {key: new[key] for key in sorted(new_keys - old_keys)},
            'removed': {key: old[key] for key in sorted(old_keys - new_keys)},
            'changed': {
                key: {'old': old[key], 'new': new[key]}
                for key in sorted(old_keys & new_keys)
                if old[key] != new[key]
            },
        }
    if isinstance(old, list) and isinstance(new, list):
        old_by_json = {canonical_json(value): value for value in old}
        new_by_json = {canonical_json(value): value for value in new}
        return {
            'added': [new_by_json[key] for key in sorted(new_by_json.keys() - old_by_json.keys())],
            'removed': [old_by_json[key] for key in sorted(old_by_json.keys() - new_by_json.keys())],
            'changed': [],
        }
    return {
        'added': [],
        'removed': [],
        'changed': {'old': old, 'new': new} if old != new else {},
    }


def _build_diff(scope_type, old, new):
    adapter = get_adapter(scope_type)
    adapter_diff = _member(adapter, 'diff') if adapter is not None else None
    if not callable(adapter_diff):
        return diff_payloads(old, new)
    try:
        return adapter_diff(old, new)
    except RestorePointAdapterError:
        raise
    except Exception as exc:
        raise RestorePointAdapterError(
            f'{scope_type} restore-point diff failed: {exc}',
        ) from exc


def diff(point_id, against='previous'):
    """Diff a point against the previous point or an explicit point id."""
    point = _point_or_raise(point_id)
    if against in (None, '', 'previous'):
        against_point = _previous_point(point)
    else:
        against_point = _point_or_raise(against)
        if (
            against_point.server_id != point.server_id
            or against_point.scope_type != point.scope_type
            or against_point.scope_id != point.scope_id
        ):
            raise RestorePointError('Restore points belong to different scopes')

    old = _strict_payload(against_point) if against_point else {}
    new = _strict_payload(point)
    return {
        'point_id': point.id,
        'against_point_id': against_point.id if against_point else None,
        'diff': _build_diff(point.scope_type, old, new),
        'has_changes': canonical_json(old) != canonical_json(new),
    }


def _normalize_refusals(value):
    if value in (None, True):
        return []
    if value is False:
        return ['The surface safety check refused this restore.']
    if isinstance(value, dict):
        if value.get('allowed', True) is False:
            value = value.get('refusals') or value.get('error') or value
        else:
            value = value.get('refusals', [])
    if isinstance(value, (str, bytes)):
        return [value.decode() if isinstance(value, bytes) else value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _restore_refusals(adapter, point, target_payload, current_payload, actor):
    validator = _member(adapter, 'validate_restore')
    if not callable(validator):
        return []
    return _normalize_refusals(validator(
        point.scope_id,
        target_payload,
        current_payload,
        actor=actor,
        server_id=point.server_id,
    ))


def preview(point_id, actor=None):
    """Read-only current → checkpoint diff, coverage, and safety refusals."""
    point = _point_or_raise(point_id)
    adapter = get_adapter(point.scope_type)
    if adapter is None:
        raise RestorePointAdapterError(
            f'No restore-point adapter registered for {point.scope_type}',
        )
    # Validate stored bytes before invoking any adapter code. A corrupt point
    # must be inert: no current-state reads, safety probes, diffs, or restores.
    target = _strict_payload(point)
    try:
        current = _capture_payload(adapter, point.scope_id, point.server_id)
        refusals = _restore_refusals(adapter, point, target, current, actor)
    except ApplicationError:
        raise
    except Exception as exc:
        raise RestorePointAdapterError(str(exc)) from exc
    return {
        'point_id': point.id,
        'scope_type': point.scope_type,
        'scope_id': point.scope_id,
        'diff': _build_diff(point.scope_type, current, target),
        'has_changes': canonical_json(current) != canonical_json(target),
        'outside_checkpoint': point.get_coverage(),
        'refusals': refusals,
        'can_restore': not refusals,
    }


def restore(point_id, actor=None):
    """Re-converge through the adapter after a recoverable pre-checkpoint."""
    point = _point_or_raise(point_id)
    adapter = get_adapter(point.scope_type)
    if adapter is None:
        raise RestorePointAdapterError(
            f'No restore-point adapter registered for {point.scope_type}',
        )
    target = _strict_payload(point)

    restore_preview = preview(point.id, actor=actor)
    if restore_preview['refusals']:
        raise RestorePointRefusedError(restore_preview['refusals'])

    before = capture(
        point.scope_type,
        point.scope_id,
        'pre_mutation',
        label=f'before restore {point.id}',
        actor=actor,
        server_id=point.server_id,
    )
    if before is None:
        raise RestorePointAdapterError(
            'Restore aborted because the pre-restore checkpoint could not be captured',
        )

    try:
        with suppress_auto_capture():
            result = _member(adapter, 'restore')(
                point.scope_id,
                target,
                actor=actor,
                server_id=point.server_id,
            )
    except ApplicationError:
        raise
    except Exception as exc:
        raise RestorePointAdapterError(str(exc)) from exc

    if isinstance(result, dict) and result.get('success') is False:
        return result

    from app.models.audit_log import AuditLog
    from app.services.audit_service import AuditService

    AuditService.log(
        AuditLog.ACTION_RESTORE_POINT_RESTORE,
        user_id=_actor_id(actor),
        target_type='restore_point',
        target_id=None,
        details={
            'restore_point_id': point.id,
            'pre_restore_point_id': before.id if before else None,
            'server_id': point.server_id,
            'scope_type': point.scope_type,
            'scope_id': point.scope_id,
        },
    )
    return result if result is not None else {'success': True}


def prune(retention_days=DEFAULT_RETENTION_DAYS, per_scope_cap=DEFAULT_SCOPE_CAP,
          now=None):
    """Expire old unkept rows and cap each server/scope timeline at 50."""
    from app.models.restore_point import RestorePoint

    try:
        retention_days = max(0, int(retention_days))
    except (TypeError, ValueError):
        retention_days = DEFAULT_RETENTION_DAYS
    try:
        per_scope_cap = max(0, int(per_scope_cap))
    except (TypeError, ValueError):
        per_scope_cap = DEFAULT_SCOPE_CAP
    now = now or datetime.utcnow()

    backfilled = 0
    expired_deleted = 0
    cap_deleted = 0
    try:
        pending = RestorePoint.query.filter(
            RestorePoint.keep.is_(False),
            RestorePoint.expires_at.is_(None),
        ).all()
        for point in pending:
            point.expires_at = (point.created_at or now) + timedelta(
                days=retention_days,
            )
            backfilled += 1

        expired = RestorePoint.query.filter(
            RestorePoint.keep.is_(False),
            RestorePoint.expires_at.isnot(None),
            RestorePoint.expires_at <= now,
        ).all()
        for point in expired:
            db.session.delete(point)
            expired_deleted += 1
        db.session.flush()

        scopes = db.session.query(
            RestorePoint.server_id,
            RestorePoint.scope_type,
            RestorePoint.scope_id,
        ).filter(RestorePoint.keep.is_(False)).distinct().all()
        for server_id, scope_type, scope_id in scopes:
            rows = (RestorePoint.query.filter_by(
                server_id=server_id,
                scope_type=scope_type,
                scope_id=scope_id,
                keep=False,
            ).order_by(RestorePoint.created_at.desc(), RestorePoint.id.desc())
                .all())
            for point in rows[per_scope_cap:]:
                db.session.delete(point)
                cap_deleted += 1

        db.session.commit()
        return {
            'success': True,
            'backfilled': backfilled,
            'expired_deleted': expired_deleted,
            'cap_deleted': cap_deleted,
            'deleted': expired_deleted + cap_deleted,
        }
    except Exception as exc:  # noqa: BLE001 -- scheduled job reports cleanly
        db.session.rollback()
        logger.error('Restore-point retention failed: %s', exc, exc_info=True)
        return {
            'success': False,
            'error': str(exc),
            'backfilled': backfilled,
            'expired_deleted': expired_deleted,
            'cap_deleted': cap_deleted,
            'deleted': expired_deleted + cap_deleted,
        }


class RestorePointService:
    """Class facade matching other ServerKit service modules."""

    capture = staticmethod(capture)
    diff = staticmethod(diff)
    preview = staticmethod(preview)
    restore = staticmethod(restore)
    prune = staticmethod(prune)
    register_adapter = staticmethod(register_adapter)
    auto_capture = staticmethod(auto_capture)
    suppress_auto_capture = staticmethod(suppress_auto_capture)
