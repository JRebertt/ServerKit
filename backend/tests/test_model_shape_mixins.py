"""Plan 77 B1/B3 — mechanical model shapes come from one definition.

TimestampMixin must be byte-identical to the hand-written column pair it
replaced (no schema migration on adoption), and uuid_pk() is the one uuid
primary-key format.
"""
import uuid as uuid_mod
from datetime import datetime


def test_timestamp_mixin_matches_house_shape(app):
    from app.models import Domain  # a converted adopter
    created = Domain.__table__.columns['created_at']
    updated = Domain.__table__.columns['updated_at']
    # SQLAlchemy wraps the callable, so compare by name, not identity.
    assert created.default is not None and created.default.arg.__name__ == 'utcnow'
    assert created.index is not True  # default variant: no index
    assert updated.default is not None and updated.default.arg.__name__ == 'utcnow'
    assert updated.onupdate is not None and updated.onupdate.arg.__name__ == 'utcnow'


def test_timestamp_mixin_rows_get_defaults(app):
    from app import db
    from app.models.server import Server
    row = Server(name='ts-proof')
    db.session.add(row)
    db.session.commit()
    assert row.created_at is not None
    assert row.updated_at is not None


def test_uuid_pk_generates_dashed_string36(app):
    from app import db
    from app.models.server import Server
    row = Server(name='uuidpk-proof')
    db.session.add(row)
    db.session.commit()
    assert isinstance(row.id, str)
    assert len(row.id) == 36
    # round-trips as a dashed uuid4
    assert str(uuid_mod.UUID(row.id)) == row.id


def test_uuid_pk_column_shape(app):
    from app.models.server import Server
    col = Server.__table__.columns['id']
    assert col.primary_key
    assert col.type.length == 36
