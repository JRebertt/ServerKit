"""API error-response shape and logging configuration.

Issue #101 was hard to diagnose partly because the panel produced no diagnostic
trail at all: the backend had exactly one error handler (the 404/SPA one), no
500 or HTTPException handler, and nothing anywhere configured logging -- so
framework-generated errors under /api/ came back as Werkzeug HTML to clients
parsing JSON, and unhandled exceptions were never logged with their path.
"""

import logging
import re


def test_unknown_api_route_returns_json_404(client):
    response = client.get('/api/v1/this-route-does-not-exist')

    assert response.status_code == 404
    assert response.is_json
    payload = response.get_json()
    assert payload['error'] == 'Not found'
    assert payload['code'] == 'not_found'
    assert payload['request_id'] == response.headers['X-Request-ID']


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
    assert payload['request_id'] == response.headers['X-Request-ID']


def test_api_request_id_is_propagated(client):
    response = client.get(
        '/api/v1/this-route-does-not-exist',
        headers={'X-Request-ID': 'operator-trace_123'},
    )

    assert response.headers['X-Request-ID'] == 'operator-trace_123'
    assert response.get_json()['request_id'] == 'operator-trace_123'


def test_unsafe_api_request_id_is_replaced(client):
    response = client.get(
        '/api/v1/this-route-does-not-exist',
        headers={'X-Request-ID': 'x' * 129},
    )

    request_id = response.headers['X-Request-ID']
    assert request_id != 'x' * 129
    assert re.fullmatch(r'[0-9a-f]{32}', request_id)
    assert response.get_json()['request_id'] == request_id


def test_typed_validation_error_keeps_stable_shape(client, auth_headers):
    response = client.post('/api/v1/monitors', json={}, headers={
        **auth_headers,
        'X-Request-ID': 'monitor-create-test',
    })

    assert response.status_code == 400
    assert response.get_json() == {
        'error': 'Monitor name is required',
        'status': 400,
        'code': 'validation_error',
        'request_id': 'monitor-create-test',
    }
    assert response.headers['X-Request-ID'] == 'monitor-create-test'


def test_typed_not_found_error_has_resource_code(client, auth_headers):
    response = client.get(
        '/api/v1/monitors/999999',
        headers=auth_headers,
    )

    payload = response.get_json()
    assert response.status_code == 404
    assert payload['error'] == 'Monitor not found'
    assert payload['status'] == 404
    assert payload['code'] == 'monitor_not_found'
    assert payload['request_id'] == response.headers['X-Request-ID']


def test_non_api_404_is_not_forced_into_json(client):
    """The SPA fallback must survive the new HTTPException handler.

    A more general handler that shadowed the 404 one would break client-side
    routing for every deep link.
    """
    response = client.get('/some/spa/deep/link')

    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert b'<' in response.get_data()  # index.html, not a JSON error


def test_unhandled_exception_returns_json_500_and_logs_the_path(app, caplog):
    """A crash must answer JSON and leave a trail naming the request.

    Driven through `app.handle_exception()` -- Flask's own entry point for an
    unhandled exception -- rather than by reading `app.error_handler_spec`.
    That attribute is a Flask internal whose shape has moved between releases,
    and registration is not behaviour: a handler can be registered and still
    return the wrong thing or log nothing.

    Not done by adding a route that raises, either. The `app` fixture is
    function-scoped but wraps a session-scoped Flask object, so a route
    registered here would leak into every later test (and collide on the second
    registration).

    PROPAGATE_EXCEPTIONS is forced off for the call because TESTING=True turns
    it on, which re-raises before any handler runs -- the same mechanism that
    keeps the dev server's traceback.
    """
    original = app.config.get('PROPAGATE_EXCEPTIONS')
    app.config['PROPAGATE_EXCEPTIONS'] = False
    try:
        with caplog.at_level(logging.ERROR):
            with app.test_request_context('/api/v1/boom', method='GET'):
                response = app.handle_exception(RuntimeError('boom'))
    finally:
        app.config['PROPAGATE_EXCEPTIONS'] = original

    assert response.status_code == 500
    assert response.is_json, (
        f'a crash returned {response.content_type}; API clients parse JSON'
    )
    payload = response.get_json()
    assert payload['error']
    assert payload['code'] == 'internal_error'
    assert payload['request_id']
    # Matched on this handler's own wording, not merely on the path: Flask's
    # log_exception() already emits "Exception on /path [GET]" before any
    # handler runs, so asserting the path alone passes even with the handler's
    # logging deleted -- verified by mutation.
    assert any(
        'Unhandled exception on GET /api/v1/boom' in record.getMessage()
        for record in caplog.records
    ), (
        'the 500 handler did not log the failing request; that missing trail is '
        'what made #101 hard to diagnose'
    )


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
