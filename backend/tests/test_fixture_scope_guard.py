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
    'test_ai_lazy_import.py',
    'test_api_error_shape.py',
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


def test_no_new_direct_create_app_callers():
    import re
    from pathlib import Path
    tests_dir = Path(__file__).resolve().parent
    found = set()
    for f in sorted(tests_dir.glob('test_*.py')):
        if f.name == Path(__file__).name:
            continue
        if re.search(r'\bcreate_app\(', f.read_text(encoding='utf-8', errors='replace')):
            found.add(f.name)
    new = found - CREATE_APP_BASELINE
    assert not new, (
        f'New test files booting their own app: {sorted(new)}. Use the `app` '
        'fixture, `route_rules`, or a documented fresh-app fixture (plan 77 G3).'
    )
    stale = CREATE_APP_BASELINE - found
    assert not stale, f'Migrated files still in the baseline: {sorted(stale)} — delete them.'
