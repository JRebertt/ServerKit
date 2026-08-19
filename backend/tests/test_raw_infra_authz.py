"""GHSA-6w78-q5vm-rfmh — raw-infrastructure reads must not bypass the per-app
gates. Two surfaces, both admin-only by the Decision 7 precedent (no app linkage
to gate on, so they match their admin-only mutation siblings):

- GET /api/v1/docker/containers/<id>        (docker inspect leaks container env
                                             vars — app secrets)
- GET /api/v1/docker/containers/<id>/logs   (raw logs of ANY container)
- /api/v1/databases host-level raw routes   (engine lists, tables/structure,
                                             users/privileges, backups list, and
                                             the raw mysql/postgresql/sqlite
                                             query consoles — readonly SELECT
                                             against ANY database is cross-app
                                             data exfiltration)

The per-app managed-database flow (GET /databases/docker/app/<app_id>, gated via
can_access_app) must keep working for app members.
"""
from unittest.mock import patch

import pytest

from app.services.database_service import DatabaseService
from app.services.docker_service import DockerService

# Promoted to a shared one-liner (plan 77 G4); kept as a local alias so the
# call sites below read the same.
from factories import assert_admin_only as _assert_admin_only  # noqa: E402


# --------------------------------------------------------------------------- #
# docker.py — raw container inspect + logs
# --------------------------------------------------------------------------- #

def test_container_inspect_admin_only(client, scoping_rbac):
    with patch.object(DockerService, 'get_container',
                      return_value={'Id': 'abc123', 'Config': {'Env': ['SECRET=x']}}):
        _assert_admin_only(client, scoping_rbac, 'get', '/api/v1/docker/containers/abc123')


def test_container_logs_admin_only(client, scoping_rbac):
    with patch.object(DockerService, 'get_container_logs',
                      return_value={'success': True, 'logs': 'DB_PASSWORD=hunter2'}):
        _assert_admin_only(client, scoping_rbac, 'get', '/api/v1/docker/containers/abc123/logs')


def test_container_inspect_requires_auth(client):
    assert client.get('/api/v1/docker/containers/abc123').status_code == 401


# --------------------------------------------------------------------------- #
# databases.py — raw query consoles
# --------------------------------------------------------------------------- #

def test_mysql_query_admin_only(client, scoping_rbac):
    with patch.object(DatabaseService, 'mysql_execute_query',
                      return_value={'success': True, 'rows': []}):
        _assert_admin_only(client, scoping_rbac, 'post',
                           '/api/v1/databases/mysql/wordpress/query',
                           body={'query': 'SELECT 1'})


def test_pg_query_admin_only(client, scoping_rbac):
    with patch.object(DatabaseService, 'pg_execute_query',
                      return_value={'success': True, 'rows': []}):
        _assert_admin_only(client, scoping_rbac, 'post',
                           '/api/v1/databases/postgresql/appdb/query',
                           body={'query': 'SELECT 1'})


def test_sqlite_query_admin_only(client, scoping_rbac):
    with patch.object(DatabaseService, 'sqlite_execute_query',
                      return_value={'success': True, 'rows': []}):
        _assert_admin_only(client, scoping_rbac, 'post',
                           '/api/v1/databases/sqlite/query',
                           body={'path': '/srv/app/db.sqlite', 'query': 'SELECT 1'})


# --------------------------------------------------------------------------- #
# databases.py — host-level metadata reads
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('url,patch_target', [
    ('/api/v1/databases/mysql', 'mysql_list_databases'),
    ('/api/v1/databases/mysql/appdb/tables', 'mysql_get_tables'),
    ('/api/v1/databases/mysql/users', 'mysql_list_users'),
    ('/api/v1/databases/mysql/users/root/privileges', 'mysql_get_user_privileges'),
    ('/api/v1/databases/postgresql', 'pg_list_databases'),
    ('/api/v1/databases/postgresql/appdb/tables', 'pg_get_tables'),
    ('/api/v1/databases/postgresql/users', 'pg_list_users'),
    ('/api/v1/databases/sqlite', 'sqlite_list_databases'),
    ('/api/v1/databases/sqlite/tables?path=/srv/app/db.sqlite', 'sqlite_get_tables'),
    ('/api/v1/databases/backups', 'list_backups'),
])
def test_host_metadata_reads_admin_only(client, scoping_rbac, url, patch_target):
    with patch.object(DatabaseService, patch_target, return_value=[]):
        _assert_admin_only(client, scoping_rbac, 'get', url)


@pytest.mark.parametrize('url,patch_target', [
    ('/api/v1/databases/mysql/appdb/tables/users/structure', 'mysql_get_table_structure'),
    ('/api/v1/databases/postgresql/appdb/tables/users/structure', 'pg_get_table_structure'),
    ('/api/v1/databases/sqlite/tables/users/structure?path=/srv/app/db.sqlite',
     'sqlite_get_table_structure'),
])
def test_table_structure_reads_admin_only(client, scoping_rbac, url, patch_target):
    with patch.object(DatabaseService, patch_target,
                      return_value={'success': True, 'columns': []}):
        _assert_admin_only(client, scoping_rbac, 'get', url)


# --------------------------------------------------------------------------- #
# Per-app managed-database flow stays member-readable (can_access_app gate)
# --------------------------------------------------------------------------- #

def test_per_app_databases_keep_can_access_app_gate(client, scoping_rbac):
    """The scoping app is a PHP app, so a caller who PASSES the can_access_app
    gate reaches the docker-type check (400); a foreign caller is denied (403)
    before it. The gate itself must not have hardened into admin-only. (This
    route's pre-existing gate is ResourceGrantService.can_access_app — owner,
    panel admin, or an explicit resource grant; it does not fold bare workspace
    membership, so member/viewer without a grant are 403 by design.)"""
    url = f'/api/v1/databases/docker/app/{scoping_rbac.app_id}'
    for persona in ('owner', 'admin'):
        resp = client.get(url, headers=getattr(scoping_rbac, persona))
        assert resp.status_code == 400, f'{persona}: {resp.status_code}'
    assert client.get(url, headers=scoping_rbac.foreign).status_code == 403
    assert client.get('/api/v1/databases/docker/app/999999',
                      headers=scoping_rbac.admin).status_code == 404
