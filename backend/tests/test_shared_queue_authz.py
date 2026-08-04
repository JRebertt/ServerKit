"""GHSA-6w78-q5vm-rfmh-class — shared variable groups and the queue bus must
enforce scope/ownership-level authorization, not just authentication.

shared_resources (/api/v1/shared/variable-groups...):
  - group reads gate on the group's scope (workspace membership / app access)
  - group + variable mutations gate on workspace write roles (can_edit_app for
    application scope)
  - attach/detach additionally gate on the TARGET resource — attaching a group
    injects its variables into the target at deploy time
  - an unscoped group listing spans every workspace -> panel admins only

queue_bus (/api/v1/queue/groups/<g>/queues/<q>/messages...):
  - receive/complete/fail/list/get on system-owned groups are admin-only
    (payload theft / internal-processing stalls otherwise)
  - user-owned groups are limited to the owning user (and panel admins)
"""
import pytest

G = '/api/v1/shared/variable-groups'
Q = '/api/v1/queue/groups'


@pytest.fixture
def sr_rbac(app, scoping_rbac):
    """A workspace-scoped variable group (+ one secret var) in scoping_rbac's
    workspace, plus a second application owned by the foreign user."""
    from types import SimpleNamespace
    from app import db
    from app.models import Application, User
    from app.services.workspace_service import WorkspaceService
    from app.services.shared_resource_service import SharedResourceService as S

    # The scoping fixture's creator has no WorkspaceMember row (production adds
    # one via WorkspaceService.create_workspace); add it so the owner persona
    # resolves to the 'owner' workspace role.
    owner = User.query.filter_by(username='scope_owner').first()
    WorkspaceService.add_member(scoping_rbac.ws_id, owner.id, role='owner')

    foreign = User.query.filter_by(username='scope_foreign').first()
    foreign_app = Application(name='foreign-app', app_type='php',
                              user_id=foreign.id, root_path='/srv/foreign')
    db.session.add(foreign_app)
    db.session.commit()

    group = S.create_group('workspace', str(scoping_rbac.ws_id), 'Shared Creds')
    var = S.set_variable(group.id, 'API_TOKEN', 'secret-value', is_secret=True)

    return SimpleNamespace(
        s=scoping_rbac, group_id=group.id, var_id=var.id,
        foreign_app_id=foreign_app.id,
    )


@pytest.fixture
def qb(app, scoping_rbac):
    """A system-owned queue with one internal message, plus a user-owned queue
    owned by the scoping 'owner' persona with one message."""
    from types import SimpleNamespace
    from app.models import User
    from app.queue_bus.service import QueueBusService

    QueueBusService.reset_broker()

    QueueBusService.ensure_queue('sys-group', 'sys-queue')
    QueueBusService.send('sys-group', 'sys-queue', {'job': 'internal'})

    owner = User.query.filter_by(username='scope_owner').first()
    QueueBusService.create_group('user-group', name='User Group',
                                 owner_type='user', owner_id=str(owner.id))
    QueueBusService.create_queue('user-group', 'user-queue', name='User Queue')
    QueueBusService.send('user-group', 'user-queue', {'hello': 'world'})

    return SimpleNamespace(s=scoping_rbac)


# ----------------------------------------------------------- shared resources

def test_get_group_read_personas(client, sr_rbac):
    """Anyone with a path to the workspace reads the (masked) group; a foreign
    caller is denied."""
    s = sr_rbac.s
    url = f'{G}/{sr_rbac.group_id}'
    for persona in ('owner', 'member', 'viewer', 'admin'):
        assert client.get(url, headers=getattr(s, persona)).status_code == 200, persona
    assert client.get(url, headers=s.foreign).status_code == 403


def test_get_group_missing_404(client, sr_rbac):
    assert client.get(f'{G}/999999', headers=sr_rbac.s.admin).status_code == 404


def test_update_group_requires_write_role(client, sr_rbac):
    s = sr_rbac.s
    url = f'{G}/{sr_rbac.group_id}'
    for persona in ('owner', 'member', 'admin'):
        assert client.put(url, json={'description': 'x'},
                          headers=getattr(s, persona)).status_code == 200, persona
    for persona in ('viewer', 'foreign'):
        assert client.put(url, json={'description': 'x'},
                          headers=getattr(s, persona)).status_code == 403, persona


def test_delete_group_requires_write_role(client, sr_rbac):
    s = sr_rbac.s
    url = f'{G}/{sr_rbac.group_id}'
    for persona in ('viewer', 'foreign'):
        assert client.delete(url, headers=getattr(s, persona)).status_code == 403, persona
    assert client.delete(url, headers=s.owner).status_code == 200


def test_add_variable_requires_write_role(client, sr_rbac):
    s = sr_rbac.s
    url = f'{G}/{sr_rbac.group_id}/variables'
    assert client.post(url, json={'key': 'NEW', 'value': '1'},
                       headers=s.member).status_code == 201
    for persona in ('viewer', 'foreign'):
        assert client.post(url, json={'key': 'INJECTED', 'value': 'x'},
                           headers=getattr(s, persona)).status_code == 403, persona


def test_update_and_delete_variable_require_write_role(client, sr_rbac):
    s = sr_rbac.s
    url = f'{G}/{sr_rbac.group_id}/variables/{sr_rbac.var_id}'
    assert client.put(url, json={'value': 'pwned'}, headers=s.foreign).status_code == 403
    assert client.delete(url, headers=s.viewer).status_code == 403
    assert client.put(url, json={'value': 'changed'}, headers=s.owner).status_code == 200
    assert client.delete(url, headers=s.owner).status_code == 200


def test_attach_to_workspace_app(client, sr_rbac):
    """Workspace write personas attach a workspace group to an app in the same
    workspace; viewer/foreign cannot (group write or target write fails)."""
    s = sr_rbac.s
    url = f'{G}/{sr_rbac.group_id}/attach'
    body = {'resource_type': 'application', 'resource_id': s.app_id}
    assert client.post(url, json=body, headers=s.member).status_code == 201
    assert client.post(url, json=body, headers=s.viewer).status_code == 403
    assert client.post(url, json=body, headers=s.foreign).status_code == 403


def test_attach_to_foreign_app_denied(client, sr_rbac):
    """Even a workspace owner cannot attach their group to a foreign user's app
    (deploy-time env-var injection into someone else's resource)."""
    s = sr_rbac.s
    url = f'{G}/{sr_rbac.group_id}/attach'
    body = {'resource_type': 'application', 'resource_id': sr_rbac.foreign_app_id}
    for persona in ('owner', 'member'):
        assert client.post(url, json=body,
                           headers=getattr(s, persona)).status_code == 403, persona
    # The panel admin may still wire it up deliberately.
    assert client.post(url, json=body, headers=s.admin).status_code == 201


def test_detach_requires_group_and_target_write(client, sr_rbac):
    s = sr_rbac.s
    body = {'resource_type': 'application', 'resource_id': s.app_id}
    client.post(f'{G}/{sr_rbac.group_id}/attach', json=body, headers=s.owner)
    url = f'{G}/{sr_rbac.group_id}/detach'
    assert client.post(url, json=body, headers=s.foreign).status_code == 403
    resp = client.post(url, json=body, headers=s.owner)
    assert resp.status_code == 200
    assert resp.get_json()['detached'] is True


def test_create_group_requires_scope_write(client, sr_rbac):
    s = sr_rbac.s
    body = {'scope_type': 'workspace', 'scope_id': str(s.ws_id), 'name': 'New'}
    assert client.post(G, json=body, headers=s.member).status_code == 201
    assert client.post(G, json=body, headers=s.viewer).status_code == 403
    assert client.post(G, json=body, headers=s.foreign).status_code == 403


def test_create_group_application_scope_foreign_denied(client, sr_rbac):
    """Application-scoped groups gate on can_edit_app; a foreign caller is
    denied before the service validates the scope."""
    s = sr_rbac.s
    body = {'scope_type': 'application', 'scope_id': str(s.app_id), 'name': 'App'}
    assert client.post(G, json=body, headers=s.foreign).status_code == 403
    assert client.post(G, json=body, headers=s.viewer).status_code == 403


def test_list_groups_scoped_requires_membership(client, sr_rbac):
    s = sr_rbac.s
    url = f'{G}?scope_type=workspace&scope_id={s.ws_id}'
    for persona in ('owner', 'member', 'viewer', 'admin'):
        assert client.get(url, headers=getattr(s, persona)).status_code == 200, persona
    assert client.get(url, headers=s.foreign).status_code == 403


def test_list_groups_unscoped_admin_only(client, sr_rbac):
    """An unscoped listing spans every workspace — panel admins only (mirrors
    the global deploy-history gate)."""
    s = sr_rbac.s
    assert client.get(G, headers=s.admin).status_code == 200
    for persona in ('owner', 'member', 'viewer', 'foreign'):
        assert client.get(G, headers=getattr(s, persona)).status_code == 403, persona


# ------------------------------------------------------------------ queue bus

def test_system_queue_receive_admin_only(client, qb):
    """Non-admins must not pop messages from system queues (visibility-timeout
    theft stalls jobs/notifications/webhook deliveries)."""
    s = qb.s
    url = f'{Q}/sys-group/queues/sys-queue/messages/receive'
    for persona in ('owner', 'member', 'viewer', 'foreign'):
        assert client.post(url, json={},
                           headers=getattr(s, persona)).status_code == 403, persona
    resp = client.post(url, json={}, headers=s.admin)
    assert resp.status_code == 200
    assert resp.get_json()['messages'][0]['payload'] == {'job': 'internal'}


def test_system_queue_list_and_get_admin_only(client, qb):
    s = qb.s
    base = f'{Q}/sys-group/queues/sys-queue'
    assert client.get(f'{base}/messages', headers=s.admin).status_code == 200
    for persona in ('owner', 'member', 'viewer', 'foreign'):
        assert client.get(f'{base}/messages',
                          headers=getattr(s, persona)).status_code == 403, persona
    msg_id = client.get(f'{base}/messages', headers=s.admin).get_json()['messages'][0]['id']
    assert client.get(f'{base}/messages/{msg_id}', headers=s.admin).status_code == 200
    assert client.get(f'{base}/messages/{msg_id}', headers=s.foreign).status_code == 403


def test_system_queue_complete_and_fail_admin_only(client, qb):
    s = qb.s
    base = f'{Q}/sys-group/queues/sys-queue'
    msg = client.post(f'{base}/messages/receive', json={},
                      headers=s.admin).get_json()['messages'][0]
    assert client.post(f'{base}/messages/{msg["id"]}/complete', json={},
                       headers=s.foreign).status_code == 403
    assert client.post(f'{base}/messages/{msg["id"]}/fail', json={},
                       headers=s.owner).status_code == 403
    assert client.post(f'{base}/messages/{msg["id"]}/complete', json={},
                       headers=s.admin).status_code == 200


def test_user_queue_owner_full_access(client, qb):
    """The owning user keeps the pre-fix behavior on their own groups."""
    s = qb.s
    base = f'{Q}/user-group/queues/user-queue'
    assert client.get(f'{base}/messages', headers=s.owner).status_code == 200
    resp = client.post(f'{base}/messages/receive', json={}, headers=s.owner)
    assert resp.status_code == 200
    msg_id = resp.get_json()['messages'][0]['id']
    assert client.get(f'{base}/messages/{msg_id}', headers=s.owner).status_code == 200
    assert client.post(f'{base}/messages/{msg_id}/complete', json={},
                       headers=s.owner).status_code == 200


def test_user_queue_other_users_denied(client, qb):
    """A user-owned group's messages are not readable/ackable by other users."""
    s = qb.s
    base = f'{Q}/user-group/queues/user-queue'
    for persona in ('member', 'viewer', 'foreign'):
        headers = getattr(s, persona)
        assert client.get(f'{base}/messages', headers=headers).status_code == 403, persona
        assert client.post(f'{base}/messages/receive', json={},
                           headers=headers).status_code == 403, persona
    msg_id = client.get(f'{base}/messages', headers=s.owner).get_json()['messages'][0]['id']
    for persona in ('member', 'foreign'):
        headers = getattr(s, persona)
        assert client.get(f'{base}/messages/{msg_id}', headers=headers).status_code == 403, persona
        assert client.post(f'{base}/messages/{msg_id}/complete', json={},
                           headers=headers).status_code == 403, persona
        assert client.post(f'{base}/messages/{msg_id}/fail', json={},
                           headers=headers).status_code == 403, persona
    # The panel admin still can.
    assert client.get(f'{base}/messages', headers=s.admin).status_code == 200


def test_missing_group_still_404(client, qb):
    """The access guard defers to the service's 404 for unknown groups."""
    resp = client.post(f'{Q}/nope/queues/nope/messages/receive', json={},
                       headers=qb.s.admin)
    assert resp.status_code == 404
