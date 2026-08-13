"""Shared model mixins.

SoftDeleteMixin is the app's one answer to "delete" for records a person can
destroy by hand. Deleting is the only action in a control panel that cannot be
undone by repeating it, so records that took effort to create keep a tombstone
instead of vanishing, and the Recycle Bin gives them back.

Adopting it on a model is three steps:

    class Domain(SoftDeleteMixin, db.Model):
        ...

    # 2. an Alembic migration adding deleted_at / deleted_by_id
    # 3. register it so the Recycle Bin can see it:
    #    recycle_bin_service.register('domain', Domain, label=lambda d: d.name)

WHAT DOES NOT COME FREE: every existing query still sees deleted rows. Use
`Model.query_active()` in place of `Model.query` on the read paths that should
hide them — the mixin cannot do this for you without a global query filter,
which would silently change behaviour everywhere including the Recycle Bin's
own lookups.

UNIQUE CONSTRAINTS: a column that is `unique=True` will block re-creating a
record whose tombstone still holds the value (you could not re-add a domain you
just deleted). Those constraints have to become PARTIAL unique indexes with a
`deleted_at IS NULL` predicate — supported by both SQLite (3.8+) and Postgres.
See migration 083 for the pattern.
"""
from datetime import datetime

from app import db


class SoftDeleteMixin:
    """Adds a tombstone (`deleted_at`) plus who did it, and restore/purge."""

    @db.declared_attr
    def deleted_at(cls):  # noqa: N805
        return db.Column(db.DateTime, nullable=True, index=True)

    @db.declared_attr
    def deleted_by_id(cls):  # noqa: N805
        # No FK: the actor may be removed later, and losing the user must not
        # cascade into losing the tombstone.
        return db.Column(db.Integer, nullable=True)

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    # `is_active` reads better at call sites and matches the vocabulary already
    # used across the app (api_key.is_active, workspace status filters).
    @property
    def is_active(self):
        return self.deleted_at is None

    def soft_delete(self, user_id=None):
        if self.deleted_at is None:
            self.deleted_at = datetime.utcnow()
            self.deleted_by_id = user_id
        return self

    def restore(self):
        self.deleted_at = None
        self.deleted_by_id = None
        return self

    @classmethod
    def query_active(cls):
        return cls.query.filter(cls.deleted_at.is_(None))

    @classmethod
    def query_deleted(cls):
        return cls.query.filter(cls.deleted_at.isnot(None))

    def soft_delete_dict(self):
        return {
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'deleted_by_id': self.deleted_by_id,
            'is_active': self.is_active,
        }
