"""Tests for the polymorphic shared-resources facade (tags + variable groups).

Covers the service layer directly (encryption-at-rest, masking, merge rule,
idempotency) plus a couple of API round-trips for the JWT-protected blueprint.
"""
import pytest

# Import our own models at collection time so their tables are in the
# SQLAlchemy metadata before the first `app` fixture runs `db.create_all()`
# (the service that pulls them in is otherwise imported lazily inside each test
# body, i.e. AFTER create_all). The panel wires these via `models/__init__.py`.
import app.models.shared_resource  # noqa: F401,E402

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app

# A concurrent, in-flight slice adds `applications.environment_id` (FK →
# `environments`) but has not yet wired its models into `models/__init__.py`.
# Until it does, `db.create_all()` cannot resolve that FK and the whole suite's
# schema build fails. We best-effort import those sibling models at collection
# time (before any `app` fixture runs `create_all`) so their tables join the
# SQLAlchemy metadata. This edits no application code and becomes a harmless
# no-op once the sibling slice wires its own imports.
try:  # pragma: no cover - depends on sibling slice presence
    import app.models.project  # noqa: F401
    import app.models.environment  # noqa: F401
except Exception:
    pass


@pytest.fixture(autouse=True)
def _register_blueprint(app):
    """Mount the shared-resources blueprint for every test in this module.

    The panel wires ``shared_resources_bp`` at ``/api/v1/shared`` in
    ``app/__init__.py``; until that lands we register it here (idempotently) so
    the API round-trip tests exercise the real routes without editing
    application code. Service-layer tests are unaffected.
    """
    if 'shared_resources' not in app.blueprints:
        from app.api.shared_resources import shared_resources_bp
        app.register_blueprint(shared_resources_bp, url_prefix='/api/v1/shared')
    return app


# --------------------------------------------------------------------- tags

def test_tag_add_remove_list(app):
    from app.services.shared_resource_service import SharedResourceService as S

    S.add_tag('application', 1, 'prod')
    S.add_tag('application', 1, 'critical')
    tags = S.list_tags('application', 1)
    assert {t.tag for t in tags} == {'prod', 'critical'}

    assert S.remove_tag('application', 1, 'prod') is True
    assert {t.tag for t in S.list_tags('application', 1)} == {'critical'}
    # Removing a missing tag is a no-op (False), not an error.
    assert S.remove_tag('application', 1, 'prod') is False


def test_tag_is_idempotent(app):
    from app.services.shared_resource_service import SharedResourceService as S
    from app.models.shared_resource import ResourceTag

    S.add_tag('server', 5, 'edge')
    S.add_tag('server', 5, 'edge')  # duplicate — must NOT create a second row
    assert ResourceTag.query.filter_by(
        resource_type='server', resource_id='5', tag='edge').count() == 1


def test_list_resources_by_tag_across_types(app):
    from app.services.shared_resource_service import SharedResourceService as S

    S.add_tag('application', 1, 'team-a')
    S.add_tag('database', 9, 'team-a')
    S.add_tag('service', 'redis-cache', 'team-b')

    rows = S.list_resources_by_tag('team-a')
    assert {(r.resource_type, r.resource_id) for r in rows} == {
        ('application', '1'), ('database', '9')
    }
    # resource_id stored as string supports non-int handles too.
    rows_b = S.list_resources_by_tag('team-b')
    assert (rows_b[0].resource_type, rows_b[0].resource_id) == ('service', 'redis-cache')


# ------------------------------------------------------------------- groups

def test_group_create_and_secret_encrypted_at_rest(app):
    from app.services.shared_resource_service import SharedResourceService as S
    from app.models.shared_resource import SharedVariable

    group = S.create_group('workspace', 'ws-1', 'Shared DB Creds', 'common db config')
    S.set_variable(group.id, 'DB_HOST', 'db.internal', is_secret=False)
    S.set_variable(group.id, 'DB_PASSWORD', 'super-secret-pw', is_secret=True)

    # Secret is encrypted at rest — the raw column never holds the plaintext.
    row = SharedVariable.query.filter_by(group_id=group.id, key='DB_PASSWORD').first()
    assert row.encrypted_value != 'super-secret-pw'
    assert 'super-secret-pw' not in row.encrypted_value
    # ...but decrypts back via the value property.
    assert row.value == 'super-secret-pw'

    # to_dict masks secrets but reveals non-secrets.
    secret_dict = row.to_dict(mask_secrets=True)
    assert secret_dict['value'] == '••••••••'
    host = SharedVariable.query.filter_by(group_id=group.id, key='DB_HOST').first()
    assert host.to_dict(mask_secrets=True)['value'] == 'db.internal'
    # Unmasked reveal works when explicitly asked.
    assert row.to_dict(mask_secrets=False)['value'] == 'super-secret-pw'


def test_set_variable_upserts_by_key(app):
    from app.services.shared_resource_service import SharedResourceService as S

    group = S.create_group('project', 'proj-1', 'App Config')
    S.set_variable(group.id, 'LOG_LEVEL', 'info')
    S.set_variable(group.id, 'LOG_LEVEL', 'debug')  # same key → update, not insert
    vars_ = S.list_variables(group.id)
    assert len(vars_) == 1
    assert vars_[0].value == 'debug'


# -------------------------------------------------- attach + resolve / merge

def test_attach_to_two_resource_types_and_idempotent(app):
    from app.services.shared_resource_service import SharedResourceService as S
    from app.models.shared_resource import SharedVariableGroupAttachment

    group = S.create_group('workspace', 'ws-1', 'Common')
    S.attach_group(group.id, 'application', 1)
    S.attach_group(group.id, 'database', 7)
    # Duplicate attachment is idempotent.
    S.attach_group(group.id, 'application', 1)

    assert SharedVariableGroupAttachment.query.filter_by(group_id=group.id).count() == 2

    app_groups = S.list_attached_groups('application', 1)
    db_groups = S.list_attached_groups('database', 7)
    assert [g.id for g in app_groups] == [group.id]
    assert [g.id for g in db_groups] == [group.id]


def test_resolve_merges_and_masks_with_last_attachment_wins(app):
    from app.services.shared_resource_service import SharedResourceService as S

    base = S.create_group('workspace', 'ws-1', 'Base')
    S.set_variable(base.id, 'REGION', 'us-east', is_secret=False)
    S.set_variable(base.id, 'TOKEN', 'base-token', is_secret=True)

    override = S.create_group('environment', 'prod', 'Prod Override')
    S.set_variable(override.id, 'REGION', 'eu-west', is_secret=False)  # collides
    S.set_variable(override.id, 'EXTRA', 'yes', is_secret=False)

    # Attach base first, override second → override wins on REGION.
    S.attach_group(base.id, 'service', 'web-1')
    S.attach_group(override.id, 'service', 'web-1')

    resolved = S.resolve_variables('service', 'web-1', mask_secrets=True)
    by_key = {v['key']: v for v in resolved}

    assert by_key['REGION']['value'] == 'eu-west'           # last attachment wins
    assert by_key['REGION']['group_name'] == 'Prod Override'
    assert by_key['EXTRA']['value'] == 'yes'
    assert by_key['TOKEN']['value'] == '••••••••'           # secret masked
    assert by_key['TOKEN']['is_secret'] is True

    # Unmasked resolution reveals the secret.
    revealed = S.resolve_variables('service', 'web-1', mask_secrets=False)
    assert {v['key']: v['value'] for v in revealed}['TOKEN'] == 'base-token'


def test_delete_group_cascades(app):
    from app.services.shared_resource_service import SharedResourceService as S
    from app.models.shared_resource import SharedVariable, SharedVariableGroupAttachment

    group = S.create_group('workspace', 'ws-1', 'Temp')
    S.set_variable(group.id, 'K', 'v')
    S.attach_group(group.id, 'application', 1)
    gid = group.id

    assert S.delete_group(gid) is True
    assert SharedVariable.query.filter_by(group_id=gid).count() == 0
    assert SharedVariableGroupAttachment.query.filter_by(group_id=gid).count() == 0


# ----------------------------------------------------------------- API layer

@pytest.fixture
def auth(app):
    """Admin JWT headers (blueprint mounted by the autouse fixture)."""
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    user = User(email='sr@test.local', username='sruser',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


def test_api_tag_and_resolve_roundtrip(app, client, auth):
    # Add a tag via the API.
    r = client.post('/api/v1/shared/tags',
                    json={'resource_type': 'application', 'resource_id': 42, 'tag': 'prod'},
                    headers=auth)
    assert r.status_code == 201

    r = client.get('/api/v1/shared/tags?resource_type=application&resource_id=42',
                   headers=auth)
    assert r.status_code == 200
    assert {t['tag'] for t in r.get_json()['tags']} == {'prod'}

    # Create a group, add a secret, attach, then resolve — secret stays masked.
    r = client.post('/api/v1/shared/variable-groups',
                    json={'scope_type': 'workspace', 'scope_id': 'ws-1', 'name': 'G'},
                    headers=auth)
    assert r.status_code == 201
    gid = r.get_json()['id']

    r = client.post(f'/api/v1/shared/variable-groups/{gid}/variables',
                    json={'key': 'API_TOKEN', 'value': 'tok-123', 'is_secret': True},
                    headers=auth)
    assert r.status_code == 201
    assert r.get_json()['value'] == '••••••••'

    r = client.post(f'/api/v1/shared/variable-groups/{gid}/attach',
                    json={'resource_type': 'application', 'resource_id': 42},
                    headers=auth)
    assert r.status_code == 201

    r = client.get('/api/v1/shared/resolved?resource_type=application&resource_id=42',
                   headers=auth)
    assert r.status_code == 200
    body = r.get_json()
    by_key = {v['key']: v for v in body['variables']}
    assert by_key['API_TOKEN']['value'] == '••••••••'


def test_api_requires_auth(app, client):
    assert client.get('/api/v1/shared/variable-groups').status_code == 401


# ----------------------------------------------------- hierarchical resolve

def test_hierarchical_precedence_workspace_to_direct(app):
    """workspace < project < environment < direct attachments (most specific wins)."""
    from app.services.shared_resource_service import SharedResourceService as S

    ws = S.create_group('workspace', 'ws-1', 'Workspace')
    S.set_variable(ws.id, 'TIER', 'workspace', is_secret=False)
    S.set_variable(ws.id, 'WS_ONLY', 'w', is_secret=False)

    proj = S.create_group('project', 'proj-1', 'Project')
    S.set_variable(proj.id, 'TIER', 'project', is_secret=False)
    S.set_variable(proj.id, 'PROJ_ONLY', 'p', is_secret=False)

    envg = S.create_group('environment', 'env-1', 'Environment')
    S.set_variable(envg.id, 'TIER', 'environment', is_secret=False)

    direct = S.create_group('workspace', 'ws-1', 'Direct Override')
    S.set_variable(direct.id, 'TIER', 'direct', is_secret=False)
    S.attach_group(direct.id, 'application', 100)

    resolved = S.resolve_hierarchical(
        'application', 100,
        context={'workspace_id': 'ws-1', 'project_id': 'proj-1',
                 'environment_id': 'env-1'},
        mask_secrets=True,
    )
    by_key = {v['key']: v for v in resolved}

    # Direct attachment wins the collision across every inherited scope.
    assert by_key['TIER']['value'] == 'direct'
    assert by_key['TIER']['source_scope'] == 'direct'
    # Inherited-only keys survive with their own provenance.
    assert by_key['WS_ONLY']['source_scope'] == 'workspace'
    assert by_key['PROJ_ONLY']['source_scope'] == 'project'


def test_hierarchical_environment_overrides_project_and_workspace(app):
    from app.services.shared_resource_service import SharedResourceService as S

    ws = S.create_group('workspace', 'ws-2', 'WS')
    S.set_variable(ws.id, 'REGION', 'global', is_secret=False)
    proj = S.create_group('project', 'proj-2', 'P')
    S.set_variable(proj.id, 'REGION', 'project-region', is_secret=False)
    envg = S.create_group('environment', 'env-2', 'E')
    S.set_variable(envg.id, 'REGION', 'eu-west', is_secret=False)

    resolved = S.resolve_hierarchical(
        'service', 'web-7',
        context={'workspace_id': 'ws-2', 'project_id': 'proj-2',
                 'environment_id': 'env-2'},
    )
    by_key = {v['key']: v for v in resolved}
    assert by_key['REGION']['value'] == 'eu-west'
    assert by_key['REGION']['source_scope'] == 'environment'


def test_hierarchical_masks_secrets_but_keeps_provenance(app):
    from app.services.shared_resource_service import SharedResourceService as S

    ws = S.create_group('workspace', 'ws-3', 'WS')
    S.set_variable(ws.id, 'API_TOKEN', 'tok-abc', is_secret=True)

    masked = S.resolve_hierarchical(
        'database', 5, context={'workspace_id': 'ws-3'}, mask_secrets=True)
    tok = {v['key']: v for v in masked}['API_TOKEN']
    assert tok['value'] == '••••••••'
    assert tok['is_secret'] is True
    assert tok['source_scope'] == 'workspace'

    revealed = S.resolve_hierarchical(
        'database', 5, context={'workspace_id': 'ws-3'}, mask_secrets=False)
    assert {v['key']: v['value'] for v in revealed}['API_TOKEN'] == 'tok-abc'


def test_hierarchical_pure_layers_helper(app):
    """The pure helper merges pre-fetched layers with provenance (no DB lookups)."""
    from app.services.shared_resource_service import SharedResourceService as S

    low = S.create_group('workspace', 'ws-pure', 'Low')
    S.set_variable(low.id, 'X', 'low', is_secret=False)
    S.set_variable(low.id, 'ONLY_LOW', 'l', is_secret=False)
    high = S.create_group('environment', 'env-pure', 'High')
    S.set_variable(high.id, 'X', 'high', is_secret=False)

    resolved = S.resolve_hierarchical_from_layers(
        [('workspace', [low]), ('environment', [high])], mask_secrets=True)
    by_key = {v['key']: v for v in resolved}
    assert by_key['X']['value'] == 'high'
    assert by_key['X']['source_scope'] == 'environment'
    assert by_key['ONLY_LOW']['source_scope'] == 'workspace'


def test_hierarchical_interpolation_of_group_refs(app):
    """{{group.KEY}} references resolve against the effective set; secrets ok."""
    from app.services.shared_resource_service import SharedResourceService as S

    g = S.create_group('workspace', 'ws-int', 'Refs')
    S.set_variable(g.id, 'HOST', 'db.internal', is_secret=False)
    S.set_variable(g.id, 'PORT', '5432', is_secret=False)
    S.set_variable(g.id, 'DSN', 'postgres://{{group.HOST}}:{{group.PORT}}/app',
                   is_secret=False)
    # Unknown refs are left verbatim.
    S.set_variable(g.id, 'KEEP', 'prefix-{{group.MISSING}}', is_secret=False)

    resolved = S.resolve_hierarchical(
        'application', 200, context={'workspace_id': 'ws-int'})
    by_key = {v['key']: v['value'] for v in resolved}
    assert by_key['DSN'] == 'postgres://db.internal:5432/app'
    assert by_key['KEEP'] == 'prefix-{{group.MISSING}}'


def test_hierarchical_api_roundtrip(app, client, auth):
    # Seed a workspace-scoped group + attach a direct override, then resolve.
    r = client.post('/api/v1/shared/variable-groups',
                    json={'scope_type': 'workspace', 'scope_id': 'ws-api',
                          'name': 'WS'}, headers=auth)
    ws_id = r.get_json()['id']
    client.post(f'/api/v1/shared/variable-groups/{ws_id}/variables',
                json={'key': 'TIER', 'value': 'workspace'}, headers=auth)

    r = client.post('/api/v1/shared/variable-groups',
                    json={'scope_type': 'workspace', 'scope_id': 'ws-api',
                          'name': 'Direct'}, headers=auth)
    direct_id = r.get_json()['id']
    client.post(f'/api/v1/shared/variable-groups/{direct_id}/variables',
                json={'key': 'TIER', 'value': 'direct'}, headers=auth)
    client.post(f'/api/v1/shared/variable-groups/{direct_id}/attach',
                json={'resource_type': 'application', 'resource_id': 99},
                headers=auth)

    r = client.get('/api/v1/shared/resolved/hierarchical'
                   '?resource_type=application&resource_id=99&workspace_id=ws-api',
                   headers=auth)
    assert r.status_code == 200
    body = r.get_json()
    by_key = {v['key']: v for v in body['variables']}
    assert by_key['TIER']['value'] == 'direct'
    assert by_key['TIER']['source_scope'] == 'direct'


# --------------------------------------------------------------- audit trail

def test_audit_rows_written_on_mutations(app):
    """Tag/group/variable/attachment mutations emit best-effort audit rows."""
    from app.services.shared_resource_service import SharedResourceService as S
    from app.models import AuditLog

    before = AuditLog.query.count()

    S.add_tag('application', 1, 'prod')
    group = S.create_group('workspace', 'ws-a', 'Audited')
    S.set_variable(group.id, 'K', 'v')
    S.attach_group(group.id, 'application', 1)
    S.detach_group(group.id, 'application', 1)
    S.remove_tag('application', 1, 'prod')
    S.delete_group(group.id)

    rows = AuditLog.query.filter(AuditLog.id > 0).all()
    ops = {r.get_details().get('op')
           for r in rows
           if r.get_details().get('feature') == 'shared_resource'}
    # Every mutation kind left a marker row.
    assert {'tag.add', 'tag.remove', 'group.create', 'variable.create',
            'group.attach', 'group.detach', 'group.delete'} <= ops
    assert AuditLog.query.count() > before


# ------------------------------------------------- tag write authorization

def test_api_tag_write_is_authorized_not_just_authenticated(app, client, db_session):
    """Tagging is a mutation on someone else's resource, so it needs the same
    ``_check_resource_write`` gate as attach/detach.

    ``POST``/``DELETE /shared/tags`` shipped behind ``@jwt_required()`` alone:
    any authenticated account could label any resource of any type. ``service``
    is the sharpest case — it has no ownership seam, so the gate resolves it to
    admin-only and a developer must be refused.
    """
    from factories import make_user, headers_for

    dev = headers_for(make_user(db_session, role='developer'))
    admin = headers_for(make_user(db_session, role='admin'))
    body = {'resource_type': 'service', 'resource_id': 'web-1', 'tag': 'prod'}

    assert client.post('/api/v1/shared/tags', json=body, headers=dev).status_code == 403
    assert client.delete('/api/v1/shared/tags', json=body, headers=dev).status_code == 403

    # Non-vacuity: the same calls succeed for a caller the gate admits.
    assert client.post('/api/v1/shared/tags', json=body, headers=admin).status_code == 201
    assert client.delete('/api/v1/shared/tags', json=body, headers=admin).status_code == 200
