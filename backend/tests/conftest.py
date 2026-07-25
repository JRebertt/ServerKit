"""Pytest fixtures for backend tests (Flask app, DB, client)."""
import os
import sys

import pytest

# Ensure backend root is on path
_backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend not in sys.path:
    sys.path.insert(0, _backend)

os.environ.setdefault('FLASK_ENV', 'testing')

# Keep the suite offline: unset SERVERKIT_REGISTRY_URL now means "use the
# public serverkit-extensions registry", while set-but-EMPTY means explicitly
# disabled (bundled index only) — which is what hermetic tests want.
os.environ.setdefault('SERVERKIT_REGISTRY_URL', '')

# Tests use a FILE-backed SQLite, not :memory:. Flask-SQLAlchemy serves an
# in-memory SQLite from a single shared connection (StaticPool), so a test that
# drives the DB from a background thread (e.g. the agent send_command round-trip
# e2e) races on that one connection and intermittently dies with
# ObjectDeletedError / PendingRollbackError. A temp file gives each thread its
# own connection with SQLite's own file locking — safe and deterministic. Each
# test still create_all/drop_all's a clean schema (see the `app` fixture).
# The file is per-PROCESS, not a fixed shared name. A shared name breaks two
# ways, both of which surface as errors at fixture setup in a different test
# every run — never in the test that caused them:
#
#   * a previous run whose app threads outlived it still holds the file, so
#     Windows refuses the delete and this run inherits that database's rows;
#     create_all then collides with the already-seeded settings row.
#   * two suites running at once share one database and truncate each other's
#     tables mid-test.
#
# A private file per process costs nothing and removes both.
_OWN_DB = None

if 'TEST_DATABASE_URL' not in os.environ:
    import glob
    import tempfile

    _tmp = tempfile.gettempdir()
    # Sweep the legacy shared file and any database left behind by a crashed
    # run. Best effort: one still held open just stays until the next sweep.
    for _stale in [os.path.join(_tmp, 'serverkit_test.db')] + \
            glob.glob(os.path.join(_tmp, 'serverkit_test_*.db')):
        try:
            os.remove(_stale)
        except OSError:
            pass

    _OWN_DB = os.path.join(_tmp, f'serverkit_test_{os.getpid()}.db').replace('\\', '/')
    os.environ['TEST_DATABASE_URL'] = 'sqlite:///' + _OWN_DB


def pytest_sessionfinish(session, exitstatus):
    """Drop this process's database so temp files can't accumulate."""
    if not _OWN_DB:
        return
    try:
        from app import db
        db.engine.dispose()
    except Exception:
        pass
    try:
        os.remove(_OWN_DB)
    except OSError:
        pass  # Still held by a lingering thread; the next run sweeps it.


# A file-backed SQLite fsyncs on every commit, which makes the suite ~3x
# slower than :memory:. For throwaway test data that durability is pure
# overhead, so disable it and keep the journal in memory — this recovers
# roughly in-memory speed while keeping the per-connection thread-safety the
# file gives us. SQLite-only and scoped to the test process.
#
# Guarded import: some CI jobs run only the stdlib-y system-utils tests with a
# minimal dependency set (no SQLAlchemy). conftest still has to import there,
# and those jobs run no DB-backed test, so the PRAGMA tuning is simply skipped.
try:
    import sqlite3  # noqa: E402
    from sqlalchemy import event  # noqa: E402
    from sqlalchemy.engine import Engine  # noqa: E402

    @event.listens_for(Engine, 'connect')
    def _fast_sqlite_for_tests(dbapi_connection, _record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cur = dbapi_connection.cursor()
            cur.execute('PRAGMA synchronous=OFF')
            cur.execute('PRAGMA journal_mode=MEMORY')
            cur.execute('PRAGMA temp_store=MEMORY')
            cur.close()
except ImportError:
    pass


@pytest.fixture(scope='function')
def app():
    """Create Flask app with testing config and in-memory DB."""
    from app import create_app
    from app import db as _db

    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db_session(app):
    """Database session for the current test (same as app's db)."""
    from app import db
    return db


@pytest.fixture
def auth_headers(app):
    """Create an admin user and return headers with valid JWT for API tests."""
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    with app.app_context():
        user = User(
            email='testadmin@test.local',
            username='testadmin',
            password_hash=generate_password_hash('testpass'),
            role=User.ROLE_ADMIN,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=user.id)

    return {'Authorization': f'Bearer {token}'}


def _mk_scope_user(db, username, role='developer'):
    from app.models import User
    from werkzeug.security import generate_password_hash
    u = User(email=f'{username}@t.local', username=username,
             password_hash=generate_password_hash('x'), role=role, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def _scope_token(user_id):
    from flask_jwt_extended import create_access_token
    return {'Authorization': f'Bearer {create_access_token(identity=user_id)}'}


@pytest.fixture
def scoping_rbac(app):
    """Five personas over ONE workspace containing ONE application (plan 19
    Decision 2 — the workspace-scoping membership model).

    Every path to the app folds into a single capability tier (see
    app_access_tier): the app owner and a panel admin resolve to 'owner',
    workspace members resolve to their workspace role, and a foreign user has no
    access at all.

        owner  -> owns the app                         (tier 'owner')
        admin  -> panel admin, bypasses to             (tier 'owner')
        member -> workspace 'member' role              (tier 'member')
        viewer -> workspace 'viewer' role              (tier 'viewer')
        foreign-> no membership / no grant             (no access)

    Returns a namespace of per-persona auth headers plus the shared app/workspace
    ids so a suite can drive the /for-app read gate and the admin write gate.
    """
    from types import SimpleNamespace
    from app import db
    from app.models import Application, Workspace
    from app.services.workspace_service import WorkspaceService

    owner = _mk_scope_user(db, 'scope_owner')
    member = _mk_scope_user(db, 'scope_member')
    viewer = _mk_scope_user(db, 'scope_viewer')
    foreign = _mk_scope_user(db, 'scope_foreign')
    admin = _mk_scope_user(db, 'scope_admin', role='admin')

    ws = Workspace(name='scope-ws', slug='scope-ws', created_by=owner.id)
    db.session.add(ws)
    db.session.commit()

    WorkspaceService.add_member(ws.id, member.id, role='member')
    WorkspaceService.add_member(ws.id, viewer.id, role='viewer')

    a = Application(name='scope-app', app_type='php', user_id=owner.id,
                    workspace_id=ws.id, root_path='/srv/scope')
    db.session.add(a)
    db.session.commit()

    return SimpleNamespace(
        app_id=a.id,
        ws_id=ws.id,
        owner=_scope_token(owner.id),
        admin=_scope_token(admin.id),
        member=_scope_token(member.id),
        viewer=_scope_token(viewer.id),
        foreign=_scope_token(foreign.id),
    )
