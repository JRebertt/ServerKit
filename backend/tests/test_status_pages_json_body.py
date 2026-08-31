"""A JSON body of literal `null` must not 500 the status-page routes.

Flask already answers the two obvious bad bodies itself — an empty body is a
400 and a wrong content-type is a 415 — so those were never the exposure. The
one that reaches the view is `null`, which is valid JSON: `get_json()` returns
None, and the service then does `if field in data` and raises TypeError.

Measured on Flask 3.1.3:
    body='null' + application/json -> get_json() is None
    body=''     + application/json -> 400 (raised by Flask)
    body='x'    + text/plain       -> 415 (raised by Flask)
"""

import importlib.util
import pathlib
import re

import pytest

EXT_DIR = pathlib.Path(__file__).resolve().parent.parent / 'app' / 'plugins' / 'serverkit-status'


def _load(module_name, filename):
    """Load a module out of the hyphenated plugin dir (not importable normally)."""
    spec = importlib.util.spec_from_file_location(module_name, EXT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_service_still_assumes_a_dict(app):
    """Pins WHY the route guard matters: the service has no defence of its own."""
    service = _load('_sk_status_service', 'status_page_service.py').StatusPageService

    with app.app_context():
        # The crash only happens past the not-found early return, so the row
        # has to exist — with no page, update_page returns None harmlessly and
        # the test would pass for the wrong reason.
        page = service.create_page({'name': 'Probe', 'slug': 'probe-null-body'})

        # None is exactly what an unguarded request.get_json() handed it.
        with pytest.raises(TypeError):
            service.update_page(page.id, None)

        # The value the route now passes instead is safe.
        assert service.update_page(page.id, {}) is not None


def test_no_route_passes_a_possibly_none_body_to_the_service():
    """Every call site either coerces None away or rejects a falsy body inline."""
    src = (EXT_DIR / 'status_pages.py').read_text(encoding='utf-8')
    lines = src.splitlines()

    assert 'request.get_json()' in src, 'no get_json call sites — did the file move?'

    unguarded = []
    for i, line in enumerate(lines):
        if line.strip() == 'data = request.get_json()':
            following = ' '.join(lines[i + 1:i + 3])
            if 'if not data' not in following:
                unguarded.append(i + 1)

    assert not unguarded, (
        f'status_pages.py lines {unguarded} pass a possibly-None body straight '
        'into the service; use `request.get_json() or {}` or reject it inline.'
    )


def test_live_copy_and_source_agree_on_the_guard():
    """The extension exists twice on disk; a one-sided fix is the classic drift."""
    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    source = repo / 'builtin-extensions' / 'serverkit-status' / 'backend' / 'status_pages.py'
    if not source.is_file():
        pytest.skip('builtin-extensions source copy not present in this checkout')

    def norm(p):
        return p.read_bytes().replace(b'\r\n', b'\n')

    assert norm(EXT_DIR / 'status_pages.py') == norm(source), (
        'status_pages.py differs between app/plugins/ and builtin-extensions/ — '
        'the loader imports the live copy, so edit BOTH.'
    )


def test_flask_still_handles_the_bodies_we_rely_on_it_for():
    """If Flask ever stopped raising on these, the routes would need their own
    handling — this is the assumption the guard is scoped against.

    Deliberately a throwaway Flask app rather than the shared `app` fixture:
    adding a route there leaks into every route-level sweep in the suite (the
    mutating-route authz sweep would see an unauthenticated PUT and fail).
    """
    from flask import Flask, request

    probe = Flask(__name__)

    @probe.route('/probe', methods=['PUT'])
    def _probe():  # pragma: no cover - exercised via the client below
        return {'is_none': request.get_json() is None}

    client = probe.test_client()

    assert client.put('/probe', data='null',
                      content_type='application/json').get_json() == {'is_none': True}
    assert client.put('/probe', data='',
                      content_type='application/json').status_code == 400
    assert client.put('/probe', data='x',
                      content_type='text/plain').status_code == 415
