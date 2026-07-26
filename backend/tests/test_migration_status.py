"""What the /migrate screen is told about the database's schema state.

The interesting case is the third one. Pending migrations are computed by
walking history backwards and breaking when the walk reaches the database's
current revision. When that revision is not in the chain at all — a branch that
added a migration and was then reverted, leaving the database stamped at a file
that no longer exists — the walk never breaks and every revision in history gets
reported as pending. That shipped: an install showed "80 pending updates" and a
Continue button that could only ever fail with "Can't locate revision".
"""
import pytest

from app.services.migration_service import MigrationService


@pytest.fixture
def migration_state():
    """Drive the service's cached state directly and restore it afterwards.

    `get_status()` is a pure read of these class attributes, which is what makes
    the three states cheap to pin without an Alembic run or a real database.
    """
    saved = (
        MigrationService._current_revision,
        MigrationService._head_revision,
        MigrationService._pending_migrations,
        MigrationService._orphaned_revision,
    )

    def apply(current, head, pending=(), orphaned=False):
        MigrationService._current_revision = current
        MigrationService._head_revision = head
        MigrationService._pending_migrations = list(pending)
        MigrationService._orphaned_revision = orphaned
        return MigrationService.get_status()

    yield apply

    (MigrationService._current_revision, MigrationService._head_revision,
     MigrationService._pending_migrations, MigrationService._orphaned_revision) = saved


def _revisions(*names):
    return [{'revision': n, 'description': f'{n} does a thing', 'down_revision': None}
            for n in names]


def test_up_to_date_asks_for_nothing(migration_state):
    status = migration_state('080_dashboard_boards', '080_dashboard_boards')
    assert status['needs_migration'] is False
    assert status['pending_count'] == 0
    assert status['orphaned_revision'] is False


def test_behind_head_lists_what_is_pending(migration_state):
    pending = _revisions('078_themes', '079_plugin_store', '080_dashboard_boards')
    status = migration_state('077_linked_panel', '080_dashboard_boards', pending)
    assert status['needs_migration'] is True
    assert status['pending_count'] == 3
    assert status['orphaned_revision'] is False
    assert [m['revision'] for m in status['pending_migrations']] == [
        '078_themes', '079_plugin_store', '080_dashboard_boards',
    ]


def test_orphaned_revision_reports_itself_instead_of_a_fake_backlog(migration_state):
    """The database is stamped at a revision this build doesn't contain.

    It still needs attention, but the pending list is unknowable rather than
    empty-because-current — and it must never be padded with all of history.
    """
    status = migration_state('081_database_engines', '080_dashboard_boards',
                             pending=(), orphaned=True)
    assert status['needs_migration'] is True
    assert status['orphaned_revision'] is True
    assert status['pending_count'] == 0
    assert status['pending_migrations'] == []
    assert status['current_revision'] == '081_database_engines'


def test_status_endpoint_exposes_the_orphan_flag(client, migration_state):
    """The screen keys its warning off this field, so it has to survive the API."""
    migration_state('081_database_engines', '080_dashboard_boards', orphaned=True)
    response = client.get('/api/v1/migrations/status')
    assert response.status_code == 200
    body = response.get_json()
    assert body['orphaned_revision'] is True
    assert body['needs_migration'] is True
    assert body['pending_migrations'] == []


def test_no_revision_at_all_is_not_treated_as_orphaned(migration_state):
    """A database with an empty alembic_version has no revision — that is the
    fresh-install path, not a stranded one."""
    status = migration_state(None, '080_dashboard_boards')
    assert status['orphaned_revision'] is False
    assert status['needs_migration'] is False
