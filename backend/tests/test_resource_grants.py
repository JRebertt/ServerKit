"""Tests for per-resource access grants (#33 — per-site ACL)."""


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


def test_grant_makes_app_visible_and_accessible(app, client):
    from app import db
    from app.models import Application

    owner = _mk_user(db, 'g_owner')
    grantee = _mk_user(db, 'g_grantee')
    a = Application(name='shared-app', app_type='php', user_id=owner.id)
    db.session.add(a)
    db.session.commit()
    app_id = a.id

    # Before the grant: the grantee neither sees nor can open the app.
    r = client.get('/api/v1/apps', headers=_token(grantee.id))
    assert 'shared-app' not in {x['name'] for x in r.get_json()['apps']}
    r = client.get(f'/api/v1/apps/{app_id}', headers=_token(grantee.id))
    assert r.status_code == 403

    # Owner shares it.
    r = client.post(f'/api/v1/apps/{app_id}/grants', json={'user_id': grantee.id}, headers=_token(owner.id))
    assert r.status_code == 201

    # Now the grantee sees it in their list and can open it.
    r = client.get('/api/v1/apps', headers=_token(grantee.id))
    assert 'shared-app' in {x['name'] for x in r.get_json()['apps']}
    r = client.get(f'/api/v1/apps/{app_id}', headers=_token(grantee.id))
    assert r.status_code == 200

    # An unrelated user still can't.
    other = _mk_user(db, 'g_other')
    r = client.get(f'/api/v1/apps/{app_id}', headers=_token(other.id))
    assert r.status_code == 403


def test_grant_management_permissions(app, client):
    from app import db
    from app.models import Application

    owner = _mk_user(db, 'm_owner')
    grantee = _mk_user(db, 'm_grantee')
    stranger = _mk_user(db, 'm_stranger')
    a = Application(name='m-app', app_type='php', user_id=owner.id)
    db.session.add(a)
    db.session.commit()
    app_id = a.id

    # A non-owner non-admin can't manage sharing.
    r = client.post(f'/api/v1/apps/{app_id}/grants', json={'user_id': grantee.id}, headers=_token(stranger.id))
    assert r.status_code == 403

    # Owner grants, lists, and the owner can't be granted to themselves.
    r = client.post(f'/api/v1/apps/{app_id}/grants', json={'user_id': grantee.id}, headers=_token(owner.id))
    assert r.status_code == 201
    grant_id = r.get_json()['grant']['id']

    r = client.get(f'/api/v1/apps/{app_id}/grants', headers=_token(owner.id))
    assert r.status_code == 200 and len(r.get_json()['grants']) == 1

    r = client.post(f'/api/v1/apps/{app_id}/grants', json={'user_id': owner.id}, headers=_token(owner.id))
    assert r.status_code == 400

    # Revoke -> the grantee loses access.
    r = client.delete(f'/api/v1/apps/{app_id}/grants/{grant_id}', headers=_token(owner.id))
    assert r.status_code == 200
    r = client.get(f'/api/v1/apps/{app_id}', headers=_token(grantee.id))
    assert r.status_code == 403


def test_grant_is_idempotent(app, client):
    from app import db
    from app.models import Application
    from app.models.workspace import ResourceGrant

    owner = _mk_user(db, 'i_owner')
    grantee = _mk_user(db, 'i_grantee')
    a = Application(name='i-app', app_type='php', user_id=owner.id)
    db.session.add(a)
    db.session.commit()

    client.post(f'/api/v1/apps/{a.id}/grants', json={'user_id': grantee.id}, headers=_token(owner.id))
    client.post(f'/api/v1/apps/{a.id}/grants', json={'user_id': grantee.id}, headers=_token(owner.id))
    assert ResourceGrant.query.filter_by(resource_type='application', resource_id=a.id, user_id=grantee.id).count() == 1


def test_viewer_grant_is_read_only(app, client):
    from app import db
    from app.models import Application
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'v_owner')
    viewer = _mk_user(db, 'v_viewer')
    a = Application(name='v-app', app_type='php', user_id=owner.id, root_path='/srv/v')
    db.session.add(a)
    db.session.commit()
    ResourceGrantService.grant(user_id=viewer.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='viewer')

    # A viewer can read the app and its linked list...
    assert client.get(f'/api/v1/apps/{a.id}', headers=_token(viewer.id)).status_code == 200
    assert client.get(f'/api/v1/apps/{a.id}/linked', headers=_token(viewer.id)).status_code == 200
    # ...but operating it (editor-only) is denied.
    assert client.post(f'/api/v1/apps/{a.id}/start', headers=_token(viewer.id)).status_code == 403


def test_editor_grant_can_operate(app, client):
    from app import db
    from app.models import Application
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'e_owner')
    editor = _mk_user(db, 'e_editor')
    a = Application(name='e-app', app_type='php', user_id=owner.id, root_path='/srv/e')
    db.session.add(a)
    db.session.commit()
    ResourceGrantService.grant(user_id=editor.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='editor')

    # An editor passes the operate access gate (the start action itself may fail
    # without Docker, but it must NOT be a 403 access denial).
    assert client.post(f'/api/v1/apps/{a.id}/start', headers=_token(editor.id)).status_code != 403
    # ...but delete stays owner-only — even an editor cannot delete the app.
    assert client.delete(f'/api/v1/apps/{a.id}', headers=_token(editor.id)).status_code == 403


def test_grant_role_validation_and_default(app, client):
    from app import db
    from app.models import Application

    owner = _mk_user(db, 'rv_owner')
    g1 = _mk_user(db, 'rv_g1')
    g2 = _mk_user(db, 'rv_g2')
    a = Application(name='rv-app', app_type='php', user_id=owner.id)
    db.session.add(a)
    db.session.commit()

    # Default role is editor.
    r = client.post(f'/api/v1/apps/{a.id}/grants', json={'user_id': g1.id}, headers=_token(owner.id))
    assert r.status_code == 201 and r.get_json()['grant']['role'] == 'editor'

    # Explicit viewer is honored.
    r = client.post(f'/api/v1/apps/{a.id}/grants', json={'user_id': g2.id, 'role': 'viewer'}, headers=_token(owner.id))
    assert r.status_code == 201 and r.get_json()['grant']['role'] == 'viewer'

    # An unknown role is rejected.
    r = client.post(f'/api/v1/apps/{a.id}/grants', json={'user_id': g2.id, 'role': 'superuser'}, headers=_token(owner.id))
    assert r.status_code == 400


def test_grant_extends_to_other_app_blueprints(app, client):
    """The grant-aware helper now gates the other app blueprints too — verify the
    sweep wired it into builds.py (a separate blueprint from apps.py)."""
    from app import db
    from app.models import Application
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'bp_owner')
    grantee = _mk_user(db, 'bp_grantee')
    stranger = _mk_user(db, 'bp_stranger')
    a = Application(name='bp-app', app_type='php', user_id=owner.id)
    db.session.add(a)
    db.session.commit()

    url = f'/api/v1/builds/apps/{a.id}/deployments'  # GET, read
    assert client.get(url, headers=_token(stranger.id)).status_code == 403
    assert client.get(url, headers=_token(owner.id)).status_code == 200

    ResourceGrantService.grant(user_id=grantee.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='viewer')
    assert client.get(url, headers=_token(grantee.id)).status_code == 200


def test_grant_opens_python_read_gate(app, client):
    """python.py's get_app_or_404 (the shared read gate) honors grants; its mutating
    endpoints are independently @admin_required, so a grant only opens the reads."""
    from app import db
    from app.models import Application
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'py_owner')
    grantee = _mk_user(db, 'py_grantee')
    stranger = _mk_user(db, 'py_stranger')
    a = Application(name='py-app', app_type='flask', user_id=owner.id, root_path='/srv/py')
    db.session.add(a)
    db.session.commit()

    url = f'/api/v1/python/apps/{a.id}/packages'  # GET, read (no @admin_required)
    assert client.get(url, headers=_token(stranger.id)).status_code == 403  # gate denies
    ResourceGrantService.grant(user_id=grantee.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id, role='viewer')
    # The grantee passes the read gate (the read itself may be empty, but not a 403).
    assert client.get(url, headers=_token(grantee.id)).status_code != 403


def test_grant_enables_wordpress_per_site_routes(app, client, wp_extension):
    from app import db
    from app.models import Application, WordPressSite
    from app.services.resource_grant_service import ResourceGrantService

    owner = _mk_user(db, 'wpg_owner')
    grantee = _mk_user(db, 'wpg_grantee')
    a = Application(name='wpg-app', app_type='wordpress', user_id=owner.id)
    db.session.add(a)
    db.session.commit()
    db.session.add(WordPressSite(application_id=a.id, is_production=True))
    db.session.commit()

    # A WP per-site route (guarded by _owner_or_admin_app) is denied before the grant.
    r = client.get(f'/api/v1/wordpress/sites/{a.id}/updates', headers=_token(grantee.id))
    assert r.status_code == 403

    # After a grant, the same route is reachable — one helper covers every WP route.
    ResourceGrantService.grant(user_id=grantee.id, resource_type='application',
                               resource_id=a.id, granted_by=owner.id)
    r = client.get(f'/api/v1/wordpress/sites/{a.id}/updates', headers=_token(grantee.id))
    assert r.status_code == 200
