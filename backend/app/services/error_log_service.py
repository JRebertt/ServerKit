"""Centralized error log service: fingerprint-deduped recording + admin queries."""
import hashlib
import logging
from datetime import datetime, timedelta

from app import db
from app.models.error_log import ErrorLog

logger = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 2000
MAX_TRACEBACK_LEN = 10000
VALID_SOURCES = ('backend', 'frontend')


def _fingerprint(source, exception_type, message, endpoint):
    """sha256 hex of `source|exception_type|message[:200]|endpoint_or_url`."""
    raw = '|'.join([
        source or '',
        exception_type or '',
        (message or '')[:200],
        endpoint or '',
    ])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def record_error(source, message, exception_type=None, traceback=None,
                 endpoint=None, method=None, user_id=None, context=None,
                 level='error'):
    """Record an error, deduping by fingerprint against unresolved rows.

    If an unresolved row with the same fingerprint exists, its count is
    incremented and last_seen bumped; otherwise a new row is created.

    Bulletproof by contract: recording an error must never break the code path
    that raised it, so every failure is swallowed after a session rollback.
    Returns (entry, deduplicated), or (None, False) on failure.
    """
    try:
        message = str(message or '')[:MAX_MESSAGE_LEN]
        if traceback is not None:
            traceback = str(traceback)[:MAX_TRACEBACK_LEN]
        if exception_type is not None:
            exception_type = str(exception_type)[:200]
        if endpoint is not None:
            endpoint = str(endpoint)[:255]
        if method is not None:
            method = str(method)[:10]
        if source not in VALID_SOURCES:
            source = 'backend'

        fp = _fingerprint(source, exception_type, message, endpoint)
        existing = ErrorLog.query.filter_by(fingerprint=fp, resolved=False).first()
        if existing:
            existing.count = (existing.count or 1) + 1
            existing.last_seen = datetime.utcnow()
            db.session.commit()
            return existing, True

        entry = ErrorLog(
            fingerprint=fp,
            source=source,
            level=level or 'error',
            exception_type=exception_type,
            message=message,
            traceback=traceback,
            endpoint=endpoint,
            method=method,
            user_id=user_id,
        )
        entry.set_context(context)
        db.session.add(entry)
        db.session.commit()
        return entry, False
    except Exception:  # noqa: BLE001 - must never raise into the failing request
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception('Failed to record error log entry')
        return None, False


def list_errors(source=None, resolved=None, search=None, page=1, per_page=25):
    """Paginated admin listing with optional source/resolved/search filters."""
    query = ErrorLog.query
    if source:
        query = query.filter_by(source=source)
    if resolved is not None:
        query = query.filter_by(resolved=resolved)
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(
            ErrorLog.message.ilike(like),
            ErrorLog.exception_type.ilike(like),
            ErrorLog.endpoint.ilike(like),
        ))
    query = query.order_by(ErrorLog.last_seen.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': [entry.to_dict() for entry in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'pages': pagination.pages,
    }


def get_error(error_id):
    """Return one error log entry, or None."""
    return ErrorLog.query.get(error_id)


def set_resolved(error_id, resolved):
    """Set the resolved flag. Returns the entry, or None when not found."""
    entry = ErrorLog.query.get(error_id)
    if not entry:
        return None
    entry.resolved = bool(resolved)
    db.session.commit()
    return entry


def delete_error(error_id):
    """Delete an entry. Returns True when a row was deleted."""
    entry = ErrorLog.query.get(error_id)
    if not entry:
        return False
    db.session.delete(entry)
    db.session.commit()
    return True


def get_stats():
    """Totals for the admin overview: total, unresolved, last 24h, by source."""
    since = datetime.utcnow() - timedelta(hours=24)
    by_source = dict(
        db.session.query(ErrorLog.source, db.func.count())
        .group_by(ErrorLog.source)
        .all()
    )
    return {
        'total': ErrorLog.query.count(),
        'unresolved': ErrorLog.query.filter_by(resolved=False).count(),
        'last_24h': ErrorLog.query.filter(ErrorLog.last_seen >= since).count(),
        'by_source': by_source,
    }
