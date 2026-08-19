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
import logging
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)


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


class EncryptedSecret:
    """Descriptor giving a model ONE way to handle a Fernet-encrypted column.

    Usage::

        class Server(db.Model):
            api_secret_encrypted = db.Column(db.Text)
            api_secret = EncryptedSecret('api_secret_encrypted')

        server.api_secret = 'plaintext'   # encrypts via utils/crypto — RAISES on failure
        server.api_secret                 # decrypts; None when empty or undecryptable
        Server.api_secret.is_set(server)  # has-a-secret masking for to_dict()

    Contracts (plan 77 C1):

    - **Assignment raises on encrypt failure.** The historical hand-rolled
      accessors caught the exception and ``print()``-ed it, silently storing
      nothing — a data-loss path (an agent that "paired" but can never verify
      a signature). A failed encrypt must fail the request that carried the
      secret.
    - **Read is tolerant.** A row written under a lost/rotated key returns
      ``None`` (with a real log line, not print) so auth paths degrade the
      same way they always have instead of 500ing every reader.
    - Assigning ``None`` (or ``''``) clears the column.
    """

    def __init__(self, column_name: str):
        self.column_name = column_name
        self.attr_name = column_name  # overwritten by __set_name__

    def __set_name__(self, owner, name):
        self.attr_name = f'{owner.__name__}.{name}'

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        raw = getattr(obj, self.column_name)
        if not raw:
            return None
        from app.utils.crypto import decrypt_secret
        try:
            return decrypt_secret(raw)
        except Exception:
            logger.warning(
                "Failed to decrypt %s (wrong key or corrupt ciphertext); returning None",
                self.attr_name, exc_info=True,
            )
            return None

    def __set__(self, obj, value):
        if value is None or value == '':
            setattr(obj, self.column_name, None)
            return
        from app.utils.crypto import encrypt_secret
        # No try/except: an encrypt failure must propagate, never be swallowed.
        setattr(obj, self.column_name, encrypt_secret(value))

    def is_set(self, obj) -> bool:
        """True when ciphertext is stored — the `has_secret` masking flag."""
        return bool(getattr(obj, self.column_name))
