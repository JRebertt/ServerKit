"""Guard: the `_flask_app` fixture must stay session-scoped.

The backend suite is fast because `create_app('testing')` runs once per process
instead of once per test. Measured before that change, on a fixed 199-test
sample, fixture setup was 89.5% of total runtime against 5.4% actually spent
running tests; making the app per-test again roughly triples the suite.

Nothing else would catch a revert to `scope='function'`. The suite would still
pass — just slowly — and CI would quietly go back to being a 20-minute wait,
which is exactly how it got that way the first time. Same idea as the
collected-test-count ratchet in tests/check_test_count.py: make a silent
regression a red test rather than a slow one.

See docs/plans/64_TEST_FIXTURE_SCOPE_PLAN.md.
"""

import ast
import re
from pathlib import Path


def _fixturedefs(request, name):
    """`getfixturedefs` takes a Node on pytest >= 8.1 and a nodeid before it."""
    manager = request._fixturemanager
    try:
        return manager.getfixturedefs(name, request.node)
    except (TypeError, AttributeError):
        return manager.getfixturedefs(name, request.node.nodeid)


def test_flask_app_fixture_is_session_scoped(request):
    defs = _fixturedefs(request, '_flask_app')
    assert defs, (
        "the `_flask_app` fixture is missing from tests/conftest.py — if it was "
        "renamed, update this guard so the scope stays enforced"
    )
    assert defs[-1].scope == 'session', (
        "`_flask_app` is %r-scoped; it must be 'session'. Rebuilding the Flask "
        "app per test was ~90%% of this suite's runtime (plan 64). If a test "
        "needs its own app, mark it `pytest.mark.fresh_app` instead of widening "
        "this fixture's scope for everyone." % (defs[-1].scope,)
    )


def test_app_fixture_stays_function_scoped(request):
    """The per-test wrapper must NOT become session-scoped.

    `app` is what resets the database between tests. Session-scoping it would
    leak every test's rows into the next, which fails in ways that point at the
    wrong test entirely.
    """
    defs = _fixturedefs(request, 'app')
    assert defs, 'the `app` fixture is missing from tests/conftest.py'
    assert defs[-1].scope == 'function', (
        "`app` is %r-scoped; it must be 'function' so each test gets a clean "
        "database." % (defs[-1].scope,)
    )


# ---------------------------------------------------------------------------
# Plan 77 G3 — direct create_app() in test modules is a frozen population.
# ---------------------------------------------------------------------------

# Files that booted their own app before the session-scoped fixture landed
# (plan 64). Each extra boot re-exposes the state-leak classes documented on
# `_flask_app` and costs seconds. New tests use the `app` fixture, the
# session `route_rules` fixture (for url_map checks), or — when a different
# config is genuinely needed — a documented fresh-app fixture in the module.
# Shrinking this list is progress; do not add to it.
CREATE_APP_BASELINE = {
    'test_agent_poll_e2e.py',
    'test_ai_lazy_import.py',  # boots one in a subprocess probe, by design
    'test_enhancements_integration.py',
    'test_fleet_proxy.py',
    'test_health_staging.py',
    'test_login_bruteforce.py',
    'test_no_background_threads.py',
    'test_observability_namespace.py',
    'test_proxy_stack.py',
    'test_services_alias.py',
    'test_ssl_unified_surface.py',
    'test_trusted_client_ip.py',
}


_CREATE_APP_CALL = re.compile(r'\bcreate_app\(')


def _boots_its_own_app(source):
    """True when *source* actually boots an app, not merely mentions one.

    A raw text search over the file counted prose: a docstring reading
    "Stand-in for create_app()" and a comment reading "create_app() runs many
    times in a test session" both matched, so two files that use the shared
    `app` fixture were reported as boots -- one as a new violation, one sitting
    in the baseline for it. Calls now come from the AST. String literals still
    count, because test_ai_lazy_import.py boots its probe app from an embedded
    script; docstrings and comments never boot anything.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:  # unparseable file still gets the old, blunt check
        return bool(_CREATE_APP_CALL.search(source))

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is not None:
                docstrings.add(id(node.body[0].value))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, 'id', None) or getattr(func, 'attr', None)
            if name == 'create_app':
                return True
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings
                and _CREATE_APP_CALL.search(node.value)):
            return True
    return False


def test_no_new_direct_create_app_callers():
    tests_dir = Path(__file__).resolve().parent
    found = set()
    for f in sorted(tests_dir.glob('test_*.py')):
        if f.name == Path(__file__).name:
            continue
        if _boots_its_own_app(f.read_text(encoding='utf-8', errors='replace')):
            found.add(f.name)
    new = found - CREATE_APP_BASELINE
    assert not new, (
        f'New test files booting their own app: {sorted(new)}. Use the `app` '
        'fixture, `route_rules`, or a documented fresh-app fixture (plan 77 G3).'
    )
    stale = CREATE_APP_BASELINE - found
    assert not stale, f'Migrated files still in the baseline: {sorted(stale)} — delete them.'


def test_boot_detection_reads_code_not_prose():
    """Prove the guard's own scanner, or it fails on the next docstring instead.

    Both false positives it produced were prose: test_disk_reclaim.py's
    "Stand-in for create_app()" docstring, and the comment that put
    test_api_error_shape.py in the baseline for a boot it never did. The
    subprocess probe in test_ai_lazy_import.py is why string literals still
    count.
    """
    docstring_only = (
        'def helper():\n'
        '    """Stand-in for create_app() - only a context is needed."""\n'
        '    return None\n'
    )
    comment_only = '# create_app() runs many times in a test session\nx = 1\n'
    real_call = 'from app import create_app\napp = create_app("testing")\n'
    embedded_probe = 'PROBE = "from app import create_app\\ncreate_app(\'testing\')"\n'
    attribute_call = 'import app\napp.create_app("testing")\n'

    assert not _boots_its_own_app(docstring_only)
    assert not _boots_its_own_app(comment_only)
    assert _boots_its_own_app(real_call)
    assert _boots_its_own_app(embedded_probe)
    assert _boots_its_own_app(attribute_call)

    # A file this guard cannot parse must not slip through unchecked.
    assert _boots_its_own_app('def broken(:\n    create_app()\n')
