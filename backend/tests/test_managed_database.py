"""Managed database resource — service, backup FK wiring, and API.

Covers the proving points from docs/plans/11_MANAGED_DATABASE_RESOURCE.md:
- provisioning persists a row; adopt is idempotent
- build_connection_uri is correct per engine and masks the secret by default
- sync_state flags a dropped-but-tracked DB as drifted
- a BackupPolicy for a managed DB resolves its descriptor from the row (real FK),
  while a legacy JSON-descriptor policy still resolves unchanged
- API masking, admin-gating, and an audited connection-uri reveal
"""
import pytest

from app import db
from app.models import ManagedDatabase, User
from app.services.managed_database_service import ManagedDatabaseService
from app.services.database_service import DatabaseService


@pytest.fixture
def managed(app):
    return ManagedDatabaseService.record_provisioned(
        'mysql', 'shop', host='localhost', port=3306,
        admin_username='shop_user', admin_secret='s3cr3t',
    )


# ── persistence ──────────────────────────────────────────────────────────────

def test_record_provisioned_persists_row(app, managed):
    assert managed.id is not None
    assert managed.origin == 'provisioned'
    assert managed.engine == 'mysql' and managed.name == 'shop'
    assert managed.admin_secret_encrypted and managed.admin_secret_encrypted != 's3cr3t'


def test_adopt_is_idempotent(app):
    a = ManagedDatabaseService.adopt('postgresql', 'localhost', 'analytics')
    b = ManagedDatabaseService.adopt('postgresql', 'localhost', 'analytics', admin_username='pg')
    assert a.id == b.id                                   # same row
    assert ManagedDatabase.query.filter_by(name='analytics').count() == 1
    assert b.admin_username == 'pg'                       # refreshed descriptor
    assert b.origin == 'adopted'


def test_provisioned_then_adopt_keeps_origin(app, managed):
    again = ManagedDatabaseService.adopt('mysql', 'localhost', 'shop')
    assert again.id == managed.id
    assert again.origin == 'provisioned'                 # not downgraded to adopted


# ── connection URI ───────────────────────────────────────────────────────────

def test_connection_uri_masks_secret_by_default(app, managed):
    uri = ManagedDatabaseService.build_connection_uri(managed)
    assert uri == 'mysql://shop_user:***@localhost:3306/shop'
    assert 's3cr3t' not in uri


def test_connection_uri_reveal_includes_secret(app, managed):
    uri = ManagedDatabaseService.build_connection_uri(managed, reveal=True)
    assert uri == 'mysql://shop_user:s3cr3t@localhost:3306/shop'


def test_connection_uri_postgres_scheme_and_default_port(app):
    m = ManagedDatabaseService.record_provisioned('postgresql', 'reports',
                                                  admin_username='u', admin_secret='pw')
    uri = ManagedDatabaseService.build_connection_uri(m)
    assert uri == 'postgresql://u:***@localhost:5432/reports'  # default port filled, secret masked


# ── sync_state ───────────────────────────────────────────────────────────────

def test_sync_state_flags_dropped_db_as_drifted(app, managed, monkeypatch):
    monkeypatch.setattr(DatabaseService, 'mysql_list_databases',
                        staticmethod(lambda *a, **k: [{'name': 'other'}]))
    state = ManagedDatabaseService.sync_state(managed)
    assert state['exists'] is False and state['drifted'] is True


def test_sync_state_present_db_not_drifted(app, managed, monkeypatch):
    monkeypatch.setattr(DatabaseService, 'mysql_list_databases',
                        staticmethod(lambda *a, **k: [{'name': 'shop'}]))
    state = ManagedDatabaseService.sync_state(managed)
    assert state['exists'] is True and state['drifted'] is False


# ── backup FK wiring (the headline) ──────────────────────────────────────────

def test_protect_creates_policy_with_real_fk(app, managed):
    from app.services.backup_policy_service import BackupPolicyService
    policy = ManagedDatabaseService.protect(managed)
    assert policy.target_type == 'database'
    assert policy.target_id == managed.id                # real FK, not an arbitrary int
    assert policy.get_target_meta().get('managed') is True

    # The executor resolves the descriptor from the ROW (incl. decrypted secret).
    target = BackupPolicyService._resolve_target(policy)
    assert target['managed_db'].id == managed.id
    cfg = target['db_config']
    assert cfg['db_type'] == 'mysql' and cfg['db_name'] == 'shop'
    assert cfg['user'] == 'shop_user' and cfg['password'] == 's3cr3t'


def test_legacy_json_descriptor_policy_still_resolves(app):
    """A pre-existing database policy (no managed marker) resolves from
    target_meta_json exactly as before — the change is backward compatible."""
    from app.models.backup_policy import BackupPolicy
    from app.services.backup_policy_service import BackupPolicyService
    policy = BackupPolicy(target_type='database', target_id=98765, target_subtype='mysql')
    policy.set_target_meta({'db_name': 'legacy_db', 'db_type': 'mysql',
                            'user': 'legacy', 'password': 'pw', 'host': 'localhost'})
    db.session.add(policy)
    db.session.commit()

    target = BackupPolicyService._resolve_target(policy)
    assert 'managed_db' not in target
    assert target['db_config']['db_name'] == 'legacy_db'
    assert target['db_config']['user'] == 'legacy'


def test_soft_delete_keeps_policy_until_purge(app, managed):
    # Plan 77 B5: the tombstoned DB keeps its backup policy running so the
    # data stays recoverable for the Recycle Bin window; PURGE removes it.
    from app.models.backup_policy import BackupPolicy
    from app.services import recycle_bin_service
    ManagedDatabaseService.protect(managed)
    assert BackupPolicy.query.filter_by(target_type='database', target_id=managed.id).count() == 1
    ManagedDatabaseService.delete(managed, drop=False)
    assert BackupPolicy.query.filter_by(target_type='database', target_id=managed.id).count() == 1
    recycle_bin_service.purge('managed_database', managed.id)
    assert BackupPolicy.query.filter_by(target_type='database', target_id=managed.id).count() == 0
    assert ManagedDatabase.query.get(managed.id) is None


# ── API ──────────────────────────────────────────────────────────────────────

def test_api_list_masks_secret(client, auth_headers, app, managed):
    resp = client.get('/api/v1/databases/managed', headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.get_json()['databases']
    assert any(r['name'] == 'shop' for r in rows)
    for r in rows:
        assert 'admin_secret_encrypted' not in r and 'secret' not in r
        assert 'has_secret' in r


def test_api_connection_uri_reveal_is_audited(client, auth_headers, app, managed):
    from app.models.audit_log import AuditLog
    before = AuditLog.query.count()
    resp = client.post(f'/api/v1/databases/managed/{managed.id}/connection-uri', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['connection_uri'] == 'mysql://shop_user:s3cr3t@localhost:3306/shop'
    assert AuditLog.query.count() == before + 1          # reveal emitted an audit row


def test_api_adopt_requires_admin(client, app):
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash
    dev = User(email='dbdev@test.local', username='dbdev',
               password_hash=generate_password_hash('x'),
               role=User.ROLE_DEVELOPER, is_active=True)
    db.session.add(dev)
    db.session.commit()
    headers = {'Authorization': f'Bearer {create_access_token(identity=dev.id)}'}
    resp = client.post('/api/v1/databases/managed/adopt', headers=headers,
                       json={'engine': 'mysql', 'name': 'x'})
    assert resp.status_code == 403


def test_api_untrack(client, auth_headers, app, managed):
    resp = client.delete(f'/api/v1/databases/managed/{managed.id}', headers=auth_headers)
    assert resp.status_code == 200
    # Plan 77 B5: a plain delete tombstones into the Recycle Bin — hidden
    # from active reads, physically retained until purge.
    row = ManagedDatabase.query.get(managed.id)
    assert row is not None and row.is_deleted
    from app.services.managed_database_service import ManagedDatabaseService
    assert ManagedDatabaseService.get(managed.id) is None
