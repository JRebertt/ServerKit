"""Plan 77 B5 — ManagedDatabase soft delete: tombstone, restore, purge.

DELETE keeps the actual database and its backup policy (recoverable);
?drop=true stays the immediate destructive path; PURGE removes the policy
but never database content.
"""
import pytest

from app import db
from app.models.managed_database import ManagedDatabase
from app.services import recycle_bin_service
from app.services.managed_database_service import ManagedDatabaseService


def _mk(name='sd-db', engine='mysql'):
    row = ManagedDatabase(engine=engine, name=name, host='localhost')
    db.session.add(row)
    db.session.commit()
    return row


def test_soft_delete_hides_from_reads_but_keeps_row(app):
    row = _mk()
    ManagedDatabaseService.delete(row, user_id=42)

    assert row.deleted_at is not None and row.deleted_by_id == 42
    assert ManagedDatabaseService.get(row.id) is None
    assert row.id not in [m.id for m in ManagedDatabase.query_active().all()]
    # tombstone still physically present
    assert ManagedDatabase.query.get(row.id) is not None


def test_recycle_bin_lists_and_restores(app):
    row = _mk(name='sd-restore')
    ManagedDatabaseService.delete(row)

    listed = recycle_bin_service.list_deleted('managed_database')
    assert any(item['id'] == row.id for item in listed)

    result = recycle_bin_service.restore('managed_database', row.id)
    assert result.get('error') is None if isinstance(result, dict) else True
    assert ManagedDatabaseService.get(row.id) is not None


def test_purge_removes_row_and_policy_never_content(app, monkeypatch):
    row = _mk(name='sd-purge')
    dropped = []
    from app.services.database_service import DatabaseService
    monkeypatch.setattr(DatabaseService, 'mysql_drop_database',
                        staticmethod(lambda name: dropped.append(name)), raising=False)
    policy_removed = []
    monkeypatch.setattr(ManagedDatabaseService, '_delete_managed_policy',
                        staticmethod(lambda managed: policy_removed.append(managed.id)))

    ManagedDatabaseService.delete(row)
    recycle_bin_service.purge('managed_database', row.id)

    assert ManagedDatabase.query.get(row.id) is None
    assert policy_removed == [row.id]
    assert dropped == [], 'purge must never drop database content'


def test_drop_true_stays_immediately_destructive(app, monkeypatch):
    row = _mk(name='sd-drop')
    dropped = []
    from app.services.database_service import DatabaseService
    monkeypatch.setattr(DatabaseService, 'mysql_drop_database',
                        staticmethod(lambda name: dropped.append(name)), raising=False)
    monkeypatch.setattr(ManagedDatabaseService, '_delete_managed_policy',
                        staticmethod(lambda managed: None))

    ManagedDatabaseService.delete(row, drop=True)
    assert dropped == ['sd-drop']
    assert ManagedDatabase.query.get(row.id) is None, 'drop=true is a hard delete'
