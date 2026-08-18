"""Request-ID propagation for API responses, errors, and diagnostic logs."""

import re
import secrets

from flask import g, has_request_context, request


REQUEST_ID_HEADER = 'X-Request-ID'
_SAFE_REQUEST_ID = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')


def _new_request_id():
    return secrets.token_hex(16)


def get_request_id(*, create=False):
    """Return this request's ID, optionally creating it for direct handlers."""
    if not has_request_context():
        return None
    request_id = getattr(g, 'request_id', None)
    if request_id is None and create:
        request_id = _new_request_id()
        g.request_id = request_id
    return request_id


def register_request_id(app):
    """Accept a safe caller ID or generate one and echo it on API responses."""

    @app.before_request
    def assign_request_id():
        if not request.path.startswith('/api/'):
            return
        supplied = (request.headers.get(REQUEST_ID_HEADER) or '').strip()
        g.request_id = supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else _new_request_id()

    @app.after_request
    def expose_request_id(response):
        if request.path.startswith('/api/'):
            response.headers[REQUEST_ID_HEADER] = get_request_id(create=True)
        return response
