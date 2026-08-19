"""One door for seeding test data (plan 77 G1/G2).

Every test that needs a user/JWT/application/server/workspace mints it here,
so a schema change lands once instead of being absorbed by dozens of
hand-rolled seed blocks. All makers take ``**overrides`` — pass exactly what
the test cares about and let the defaults absorb everything else.

Usage (tests import these as top-level modules, like subprocess_stub):

    from factories import make_user, headers_for, make_application

    user = make_user(db, 'alice', role='viewer')
    resp = client.get('/api/v1/apps', headers=headers_for(user))
"""
import uuid


def _uid():
    return uuid.uuid4().hex[:8]


def make_user(db, username=None, role='developer', password='x', **overrides):
    """Create + commit a User. Unique username derived when omitted."""
    from app.models import User
    from werkzeug.security import generate_password_hash
    if username is None:
        username = f'u{_uid()}'
    fields = dict(
        email=f'{username}@t.local',
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        is_active=True,
    )
    fields.update(overrides)
    user = User(**fields)
    db.session.add(user)
    db.session.commit()
    return user


def headers_for(user):
    """JWT auth headers for a User row (or a raw user id)."""
    from flask_jwt_extended import create_access_token
    user_id = getattr(user, 'id', user)
    return {'Authorization': f'Bearer {create_access_token(identity=user_id)}'}


def make_workspace(db, name='ws', created_by=None, **overrides):
    """Create + commit a Workspace; seeds an owner user when none is given."""
    from app.models import Workspace
    if created_by is None:
        created_by = make_user(db).id
    fields = dict(name=name, slug=overrides.pop('slug', name), created_by=created_by)
    fields.update(overrides)
    ws = Workspace(**fields)
    db.session.add(ws)
    db.session.commit()
    return ws


def make_application(db, **overrides):
    """Create + commit an Application (docker-shaped defaults, the seed block
    formerly copy-pasted as ``_seed_app`` across suites). Seeds an owning
    admin user when ``user_id`` is not supplied."""
    from app.models import Application
    fields = dict(
        name='web',
        app_type='docker',
        source='manual',
        root_path='/tmp/web',
        compose_file='docker-compose.yml',
        docker_image='nginx:latest',
    )
    fields.update(overrides)
    if 'user_id' not in fields:
        from app.models import User
        fields['user_id'] = make_user(db, role=User.ROLE_ADMIN).id
    row = Application(**fields)
    db.session.add(row)
    db.session.commit()
    return row


def make_server(db, name='box1', **overrides):
    """Create + commit a Server row."""
    from app.models.server import Server
    fields = dict(name=name)
    fields.update(overrides)
    row = Server(**fields)
    db.session.add(row)
    db.session.commit()
    return row
