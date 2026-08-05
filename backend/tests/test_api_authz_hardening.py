"""Persona x route authorization matrix for plan 18 (API Authorization Hardening).

This is the load-bearing proving suite for the "one canonical gate everywhere"
seal: every per-app WordPress / env-var / status-page / docker-DB route must deny
a non-owner, non-grantee caller through the shared ResourceGrantService seam,
while an admin still reaches every sealed route (Decision 8 — single-admin
installs are invariant).

The RBAC fixture defined here (owner / editor-grant / viewer-grant / foreign
non-member / admin) is intentionally reusable: plan 19 Phase 1 inherits it.
"""
import pytest


# --------------------------------------------------------------------------- #
# Reusable RBAC fixture: five personas over one shared WordPress application.
# --------------------------------------------------------------------------- #

def _mk_user(db, username, role='developer'):
    from app.models import User
    from werkzeug.security import generate_password_hash
    u = User(email=f'{username}@t.local', username=username,
             password_hash=generate_password_hash('x'), role=role, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def _token(user_id):
    from flask_jwt_extended import create_access_token
    return {'Authorization': f'Bearer {create_access_token(identity=user_id)}'}


@pytest.fixture
def rbac(app):
    """Owner + editor-grant + viewer-grant + foreign + admin over one WP app.

    Returns a namespace with per-persona auth headers and the shared ids. The WP
    site is deliberately NOT production and has no root_path, so destructive
    service calls bail out with a safe 400 rather than touching Docker — the
    security assertion only cares that the *gate* opened (anything but the auth
    404) vs. denied (404)."""
    from types import SimpleNamespace
    from app import db
    from app.models import Application, WordPressSite
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'authz_owner')
    editor = _mk_user(db, 'authz_editor')
    viewer = _mk_user(db, 'authz_viewer')
    foreign = _mk_user(db, 'authz_foreign')
    admin = _mk_user(db, 'authz_admin', role='admin')

    a = Application(name='authz-wp', app_type='wordpress', user_id=owner.id,
                    root_path='')
    db.session.add(a)
    db.session.commit()
    site = WordPressSite(application_id=a.id, is_production=False)
    db.session.add(site)
    db.session.commit()

    ResourceGrantService.grant(user_id=editor.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='editor')
    ResourceGrantService.grant(user_id=viewer.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='viewer')

    return SimpleNamespace(
        app_id=a.id,
        site_id=site.id,
        owner=_token(owner.id),
        editor=_token(editor.id),
        viewer=_token(viewer.id),
        foreign=_token(foreign.id),
        admin=_token(admin.id),
    )


# --------------------------------------------------------------------------- #
# Phase 1 — the P0 destructive <site_id> lifecycle mutations.
# Denied (viewer-grant, foreign non-member) -> 404 (sealed-from-open, Decision 5).
# Allowed (owner, editor-grant, admin) -> the gate opens (status != 404).
# --------------------------------------------------------------------------- #

def _destructive_calls(client, rbac):
    """(label, callable(headers)->response) for every P0 write route."""
    sid = rbac.site_id
    base = f'/api/v1/wordpress/sites/{sid}'
    return [
        ('delete_site', lambda h: client.delete(base, headers=h)),
        ('archive', lambda h: client.post(f'{base}/archive', headers=h)),
        ('unarchive', lambda h: client.post(f'{base}/unarchive', headers=h)),
        ('set_tags', lambda h: client.patch(f'{base}/tags', json={'tags': ['x']}, headers=h)),
        ('clone', lambda h: client.post(f'{base}/clone', json={}, headers=h)),
        ('create_env', lambda h: client.post(f'{base}/environments', json={}, headers=h)),
        ('delete_env', lambda h: client.delete(f'{base}/environments/999999', headers=h)),
    ]


@pytest.mark.parametrize('persona', ['viewer', 'foreign'])
def test_p0_destructive_denied_for_unauthorized(app, client, rbac, persona, wp_extension):
    """A viewer-grant and a foreign non-member cannot delete/alter any site —
    the regression anchor: a viewer cannot delete a site."""
    headers = getattr(rbac, persona)
    for label, call in _destructive_calls(client, rbac):
        r = call(headers)
        assert r.status_code == 404, f'{persona} reached {label} (got {r.status_code}, expected 404)'


@pytest.mark.parametrize('persona', ['owner', 'editor', 'admin'])
def test_p0_destructive_allowed_for_authorized(app, client, rbac, persona, wp_extension):
    """Owner, editor-grantee, and admin all pass the write gate (the operation
    itself may 400 without Docker, but it must NOT be the auth 404)."""
    headers = getattr(rbac, persona)
    for label, call in _destructive_calls(client, rbac):
        r = call(headers)
        assert r.status_code != 404, f'{persona} was denied {label} (got 404)'


def test_p0_destructive_missing_site_is_404_even_for_admin(app, client, rbac, wp_extension):
    """A non-existent site is 404 for everyone, including admin (no info leak /
    no crash) — the guard resolves the app before acting."""
    r = client.delete('/api/v1/wordpress/sites/987654', headers=rbac.admin)
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Phase 2 — WordPress read holes + convergence.
# --------------------------------------------------------------------------- #

def _sealed_denied(r):
    """True iff the sealed-from-open gate (Decision 5) denied the caller — a 404
    whose body is exactly the gate's `{'error': 'Not found'}`. Distinguishes the
    gate's 404 from a service-level 404 (e.g. 'Not a production site')."""
    return r.status_code == 404 and (r.get_json() or {}).get('error') == 'Not found'


def test_sealed_reads_hidden_from_foreign(app, client, rbac, wp_extension):
    """Previously-open <site_id>/<app_id> reads now hide behind the gate for a
    foreign caller (404 'Not found') and open for any grant (Decision 5)."""
    sid, aid = rbac.site_id, rbac.app_id
    sealed_reads = [
        f'/api/v1/wordpress/sites/{sid}',
        f'/api/v1/wordpress/sites/{sid}/environments',
        f'/api/v1/wordpress/sites/{aid}/page-cache',
        f'/api/v1/wordpress/sites/{aid}/object-cache',
        f'/api/v1/wordpress/sites/{aid}/plugins/managed',
    ]
    for url in sealed_reads:
        assert _sealed_denied(client.get(url, headers=rbac.foreign)), f'foreign reached {url}'
        # A viewer-grant (read) and admin pass the gate — a service-level 404
        # (non-production, no docker) is fine; only the gate's 404 is a denial.
        assert not _sealed_denied(client.get(url, headers=rbac.viewer)), f'viewer denied {url}'
        assert not _sealed_denied(client.get(url, headers=rbac.admin)), f'admin denied {url}'


def test_convergence_reads_403_for_foreign_grant_opens(app, client, rbac, wp_extension):
    """The eight formerly-inline `role != 'admin'` feature reads keep their 403 on
    denial (Decision 5) but now honor grants (Decision 3): a viewer-grant reaches
    them, exactly as it already reaches the app's volumes/deployments."""
    aid = rbac.app_id
    converged_reads = [
        f'/api/v1/wordpress/sites/{aid}/php',
        f'/api/v1/wordpress/sites/{aid}/status-page',
        f'/api/v1/wordpress/sites/{aid}/analytics',
        f'/api/v1/wordpress/sites/{aid}/vulnerabilities',
        f'/api/v1/wordpress/sites/{aid}/info',
        f'/api/v1/wordpress/sites/{aid}/plugins',
        f'/api/v1/wordpress/sites/{aid}/themes',
        f'/api/v1/wordpress/sites/{aid}/backups',
    ]
    for url in converged_reads:
        assert client.get(url, headers=rbac.foreign).status_code == 403, f'foreign reached {url}'
        assert client.get(url, headers=rbac.viewer).status_code != 403, f'grant did not open {url}'
        assert client.get(url, headers=rbac.admin).status_code != 403, f'admin denied {url}'


# --------------------------------------------------------------------------- #
# Phase 3 — env vars convergence (read = can_access_app, write = can_edit_app).
# --------------------------------------------------------------------------- #

@pytest.fixture
def env_rbac(app):
    """Same five personas over a plain (non-WP) app for the env-var surface."""
    from types import SimpleNamespace
    from app import db
    from app.models import Application
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'env_owner')
    editor = _mk_user(db, 'env_editor')
    viewer = _mk_user(db, 'env_viewer')
    foreign = _mk_user(db, 'env_foreign')
    admin = _mk_user(db, 'env_admin', role='admin')

    a = Application(name='env-app', app_type='php', user_id=owner.id, root_path='/srv/env')
    db.session.add(a)
    db.session.commit()
    ResourceGrantService.grant(user_id=editor.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='editor')
    ResourceGrantService.grant(user_id=viewer.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='viewer')

    return SimpleNamespace(
        app_id=a.id,
        owner=_token(owner.id), editor=_token(editor.id), viewer=_token(viewer.id),
        foreign=_token(foreign.id), admin=_token(admin.id),
    )


def test_env_read_matrix(app, client, env_rbac):
    """Reads: owner/admin/editor/viewer reach env vars; a foreign caller is 403."""
    url = f'/api/v1/apps/{env_rbac.app_id}/env'
    for persona in ('owner', 'admin', 'editor', 'viewer'):
        assert client.get(url, headers=getattr(env_rbac, persona)).status_code == 200, persona
    assert client.get(url, headers=env_rbac.foreign).status_code == 403


def test_env_write_matrix(app, client, env_rbac):
    """Writes: owner/admin/editor can create; viewer-grant and foreign are 403
    (viewer is read-only — the editor-vs-viewer split is the whole point)."""
    url = f'/api/v1/apps/{env_rbac.app_id}/env'
    # Allowed to write.
    for i, persona in enumerate(('owner', 'admin', 'editor')):
        r = client.post(url, json={'key': f'K{i}', 'value': 'v'}, headers=getattr(env_rbac, persona))
        assert r.status_code in (200, 201), f'{persona} could not write env ({r.status_code})'
    # Denied write.
    assert client.post(url, json={'key': 'NOPE', 'value': 'v'}, headers=env_rbac.viewer).status_code == 403
    assert client.post(url, json={'key': 'NOPE', 'value': 'v'}, headers=env_rbac.foreign).status_code == 403


def test_env_secret_masking_preserved(app, client, env_rbac):
    """Convergence must not change secret masking: a secret's value is masked when
    ?mask=true and revealed otherwise (existing behavior)."""
    url = f'/api/v1/apps/{env_rbac.app_id}/env'
    client.post(url, json={'key': 'API_TOKEN', 'value': 'supersecret', 'is_secret': True},
                headers=env_rbac.owner)

    masked = client.get(f'{url}?mask=true', headers=env_rbac.viewer).get_json()['env_vars']
    token = next(e for e in masked if e['key'] == 'API_TOKEN')
    assert token['value'] != 'supersecret'  # masked for the reader

    clear = client.get(f'{url}?mask=false', headers=env_rbac.owner).get_json()['env_vars']
    token = next(e for e in clear if e['key'] == 'API_TOKEN')
    assert token['value'] == 'supersecret'  # unmasked path intact


# --------------------------------------------------------------------------- #
# Phase 4 — status pages (mutations admin-only, reads open) + raw docker-DB.
# --------------------------------------------------------------------------- #

# Status-page mutation authz moved to tests/test_status_extraction.py (plan 47) —
# the status blueprint now lives in the serverkit-status extension, so the test
# installs it before exercising the admin-only mutations.


def test_raw_docker_db_routes_admin_only(app, client):
    """The bare-container docker DB routes (no app linkage) are system-level and
    admin-only (Decision 7). A non-admin is 403; an admin passes the gate."""
    from app import db
    dev = _mk_user(db, 'rd_dev', role='developer')
    admin = _mk_user(db, 'rd_admin', role='admin')

    raw = [
        ('get', '/api/v1/databases/docker/ghost/databases', None),
        ('get', '/api/v1/databases/docker/ghost/wordpress/tables', None),
        ('post', '/api/v1/databases/docker/ghost/wordpress/query', {'query': 'SELECT 1'}),
    ]
    for method, url, body in raw:
        call = getattr(client, method)
        kwargs = {'json': body} if body is not None else {}
        assert call(url, headers=_token(dev.id), **kwargs).status_code == 403, f'dev reached {url}'
        # Admin passes the gate (the docker exec itself may fail, but not 403).
        assert call(url, headers=_token(admin.id), **kwargs).status_code != 403, f'admin denied {url}'


def test_per_app_docker_db_read_open_to_grantee(app, client):
    """The per-app DB endpoint stays grant-checked (not admin-gated): a grantee
    reaches it, a foreign caller does not — the non-admin path the UI should use."""
    from app import db
    from app.models import Application
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'dd_owner')
    grantee = _mk_user(db, 'dd_grantee')
    foreign = _mk_user(db, 'dd_foreign')
    a = Application(name='dd-docker', app_type='docker', user_id=owner.id, root_path='/srv/dd')
    db.session.add(a)
    db.session.commit()
    ResourceGrantService.grant(user_id=grantee.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='viewer')

    url = f'/api/v1/databases/docker/app/{a.id}'
    assert client.get(url, headers=_token(grantee.id)).status_code != 403
    assert client.get(url, headers=_token(foreign.id)).status_code == 403


# --------------------------------------------------------------------------- #
# Phase 5 — the static gate (#13): no per-app WordPress route may be jwt-only
# without an access call. A structural regression net so a new per-app route
# can't silently reintroduce an open hole.
# --------------------------------------------------------------------------- #

def test_no_ungated_per_app_wordpress_route():
    """SUPERSEDED (plan 29 #10) by the generic AST sweep in
    test_authz_structural_sweep.py, which covers wordpress.py alongside the whole
    api/ surface with the complete gate family (fixing this gate's missing-verbs
    gap). This thin alias is retained for one release; delete after."""
    from test_authz_structural_sweep import test_no_ungated_per_app_route
    test_no_ungated_per_app_route()


# --------------------------------------------------------------------------- #
# Plan 29 Phase 1 — seal the leftover routes plan 18's ledger missed.
# Each is a host/system surface with no app linkage, so it converges onto
# @admin_required to match its already-admin siblings. Personas from the
# `scoping_rbac` fixture (viewer/member/foreign are non-admin; admin bypasses).
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('persona', ['viewer', 'member', 'foreign'])
def test_raw_docker_container_list_admin_only(app, client, scoping_rbac, persona):
    """#2 — `GET /databases/docker` host-container enumeration is System-level
    (no app/workspace linkage) → admin-only. Any non-admin is 403; admin passes."""
    r = client.get('/api/v1/databases/docker', headers=getattr(scoping_rbac, persona))
    assert r.status_code == 403, f'{persona} reached the raw docker list ({r.status_code})'
    assert client.get('/api/v1/databases/docker', headers=scoping_rbac.admin).status_code != 403


@pytest.mark.parametrize('persona', ['viewer', 'member', 'foreign'])
def test_raw_docker_processes_admin_only(app, client, scoping_rbac, persona):
    """#1 — the bare-container processlist read takes `X-DB-Password` and has no
    app linkage → admin-only, matching its `kill` sibling. Non-admin is 403."""
    url = '/api/v1/databases/docker/ghost/processes'
    assert client.get(url, headers=getattr(scoping_rbac, persona)).status_code == 403, persona
    # Admin passes the gate (the docker exec itself may fail, but not with 403).
    assert client.get(url, headers=scoping_rbac.admin).status_code != 403


@pytest.mark.parametrize('persona', ['viewer', 'member', 'foreign'])
def test_wordpress_standalone_host_ops_admin_only(app, client, scoping_rbac, persona, wp_extension):
    """#3 — the standalone install/uninstall/start/stop/restart host ops predate
    the per-app model and touch the host → admin-only (plan 19's host-touching
    matrix). A non-admin is 403 on every one; admin passes the gate."""
    base = '/api/v1/wordpress/standalone'
    ops = [
        ('post', f'{base}/install'),
        ('post', f'{base}/uninstall'),
        ('post', f'{base}/start'),
        ('post', f'{base}/stop'),
        ('post', f'{base}/restart'),
    ]
    headers = getattr(scoping_rbac, persona)
    for method, url in ops:
        call = getattr(client, method)
        assert call(url, json={}, headers=headers).status_code == 403, f'{persona} reached {url}'
        assert call(url, json={}, headers=scoping_rbac.admin).status_code != 403, f'admin denied {url}'


# test_status_component_check_admin_only moved to tests/test_status_extraction.py
# (plan 47) — the status blueprint is now in the serverkit-status extension.
