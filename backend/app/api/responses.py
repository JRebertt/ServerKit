"""Canonical JSON response envelopes for newly converged API endpoints."""

from flask import jsonify


def data_response(data, *, status=200, message=None, meta=None, legacy=None):
    """Return a stable ``data`` envelope with optional compatibility fields.

    ``legacy`` is deliberately explicit.  It supports additive migrations of
    public endpoints without making old top-level names the default for new
    code.  Every use should have a consumer-removal condition in its domain.
    """

    payload = {'data': data}
    if meta is not None:
        payload['meta'] = meta
    if message:
        payload['message'] = message
    if legacy:
        payload.update(legacy)
    return jsonify(payload), status


def list_response(items, *, total=None, status=200, meta=None, legacy_key=None):
    """Return the canonical list envelope and paging metadata."""

    rows = list(items)
    list_meta = dict(meta or {})
    list_meta.setdefault('total', len(rows) if total is None else total)
    legacy = {legacy_key: rows} if legacy_key else None
    return data_response(rows, status=status, meta=list_meta, legacy=legacy)
