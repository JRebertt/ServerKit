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
