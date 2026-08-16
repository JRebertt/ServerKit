"""API error-response shape and logging configuration.

Issue #101 was hard to diagnose partly because the panel produced no diagnostic
trail at all: the backend had exactly one error handler (the 404/SPA one), no
500 or HTTPException handler, and nothing anywhere configured logging -- so
framework-generated errors under /api/ came back as Werkzeug HTML to clients
parsing JSON, and unhandled exceptions were never logged with their path.
"""

import logging

from werkzeug.exceptions import InternalServerError


def test_unknown_api_route_returns_json_404(client):
    response = client.get('/api/v1/this-route-does-not-exist')

    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()['error'] == 'Not found'


def test_method_not_allowed_on_api_returns_json_not_html(client):
    """405 used to render Werkzeug's HTML page even under /api/.

    An API client parsing the body got a JSON decode error instead of the
    actual reason it failed.
    """
    # The installer route is GET-only and needs no auth, so a POST reaches the
    # router's 405 without any credential handling in the way.
    response = client.post('/api/v1/servers/install.sh')

    assert response.status_code == 405
    assert response.is_json, (
        f'405 under /api/ returned {response.content_type}; API clients parse JSON'
    )
    payload = response.get_json()
    assert payload['status'] == 405
    assert payload['error']


def test_non_api_404_is_not_forced_into_json(client):
    """The SPA fallback must survive the new HTTPException handler.

    A more general handler that shadowed the 404 one would break client-side
    routing for every deep link.
    """
    response = client.get('/some/spa/deep/link')

    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert b'<' in response.get_data()  # index.html, not a JSON error


def test_internal_error_handler_is_registered(app):
    """A 500 handler must exist, or API clients get an HTML page on a crash."""
    handlers = app.error_handler_spec[None]

    assert 500 in handlers and handlers[500], (
        'no 500 error handler registered; an unhandled exception returns '
        "Werkzeug's HTML page and is never logged with its request path"
    )
    assert InternalServerError in handlers[500]


def test_logging_is_configured_with_a_formatter(app):
    """Services log via logging.getLogger(__name__); something must configure it.

    Without a root handler those records fall through to logging's last-resort
    handler: WARNING and above only, no timestamp, no logger name, INFO dropped.
    """
    root = logging.getLogger()

    assert root.handlers, 'root logger has no handler; log records are unformatted'
    assert any(h.formatter is not None for h in root.handlers), (
        'no handler has a formatter; records lose their timestamp and logger name'
    )
    assert root.level <= logging.INFO, (
        f'root log level is {logging.getLevelName(root.level)}; INFO diagnostics '
        f'never reach the operator'
    )


def test_logging_is_not_duplicated(app):
    """Every record must be emitted once.

    Flask attaches its own handler to app.logger, which also propagates to the
    root logger. With a root handler added and Flask's left in place, every line
    printed twice -- once formatted with %(module)s and once with %(name)s --
    which is how it looked in the container before this was fixed.
    """
    from flask.logging import default_handler

    assert default_handler not in app.logger.handlers, (
        "Flask's default handler is still on app.logger while a root handler "
        'exists; every app.logger record is printed twice'
    )

    # And configuring twice must not stack a second handler. create_app() runs
    # many times in a test session, and gunicorn imports the module before
    # forking, so an unguarded addHandler would multiply every line.
    from app import _configure_logging

    root = logging.getLogger()
    before = len(root.handlers)
    _configure_logging(app)
    assert len(root.handlers) == before, (
        'a repeat _configure_logging() added another root handler; every record '
        'would print once per call'
    )
