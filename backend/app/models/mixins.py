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
import uuid
from datetime import datetime

from app import db
from app.models import status as _status

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

    def __init__(self, column_name: str, legacy_plaintext: bool = False):
        self.column_name = column_name
        self.attr_name = column_name  # overwritten by __set_name__
        # Columns that predate encryption-at-rest may still hold plaintext
        # rows. legacy_plaintext=True mirrors utils.crypto.decrypt_secret_safe:
        # an undecryptable value is returned unchanged instead of None, so
        # not-yet-rewritten rows keep working until their next write.
        self.legacy_plaintext = legacy_plaintext

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
            if self.legacy_plaintext:
                return raw
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


def uuid_pk():
    """The ONE uuid primary-key shape: String(36), dashed uuid4 text.

    Every uuid-keyed model uses this factory (plan 77 B3) so the format
    decision is made once — a second format (e.g. 32-char hex) would break
    FK joins against String(36) columns. The lone pre-existing deviant is
    ai.py's String(64) hex ids, grandfathered until a data migration.

        class Server(db.Model):
            id = uuid_pk()
    """
    return db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class TimestampMixin:
    """created_at / updated_at in the ONE house shape (plan 77 B1).

    Byte-identical to the hand-written pair::

        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    so adoption needs NO schema migration — it only centralizes the
    ``datetime.utcnow`` default, making the eventual tz-aware migration
    (utcnow is deprecated on Python 3.13) a one-file edit instead of ~270.
    Set ``__timestamp_index__ = True`` on the model for the indexed
    created_at variant. Models with only created_at, or a deviant shape
    (e.g. sanitization_profile's default-less updated_at), keep their own
    columns — adding a column via mixin WOULD be a schema change.
    """

    __timestamp_index__ = False

    @db.declared_attr
    def created_at(cls):  # noqa: N805
        return db.Column(db.DateTime, default=datetime.utcnow,
                         index=bool(getattr(cls, '__timestamp_index__', False)))

    @db.declared_attr
    def updated_at(cls):  # noqa: N805
        return db.Column(db.DateTime, default=datetime.utcnow,
                         onupdate=datetime.utcnow)


class RunLifecycleMixin:
    """State transitions for run-shaped models (plan 77 D2).

    Ten run models hand-write ``status`` + ``started_at``/``completed_at``
    (+ duration) transitions today; this mixin is the one place they happen::

        job.mark_running()
        job.mark_succeeded()          # or mark_failed(error=...), mark_cancelled()

    Status spellings come from models/status.py. A domain still storing a
    legacy spelling (e.g. deployment jobs' 'succeeded') overrides the class
    attributes below until its per-domain data migration lands — adoption
    must NOT silently change stored strings.

    Column-name variance is absorbed, not forced: completed-at goes to
    ``__completed_at_attr__`` (default 'completed_at'; set 'finished_at'
    where that is the column), and a duration is stored only when the model
    actually has a 'duration_seconds' or 'duration' COLUMN (properties are
    left alone).
    """

    __status_running__ = _status.RUNNING
    __status_success__ = _status.SUCCESS
    __status_failed__ = _status.FAILED
    __status_cancelled__ = _status.CANCELLED
    __completed_at_attr__ = 'completed_at'
    __error_attr__ = 'error'

    def mark_running(self, when=None):
        self.status = self.__status_running__
        self.started_at = when or datetime.utcnow()
        return self

    def mark_succeeded(self, when=None):
        return self._finish(self.__status_success__, when)

    def mark_failed(self, error=None, when=None):
        self._finish(self.__status_failed__, when)
        if error is not None and self.__error_attr__ in self.__table__.columns:
            setattr(self, self.__error_attr__, str(error))
        return self

    def mark_cancelled(self, when=None):
        return self._finish(self.__status_cancelled__, when)

    def _finish(self, status, when=None):
        when = when or datetime.utcnow()
        self.status = status
        if self.__completed_at_attr__ in self.__table__.columns:
            setattr(self, self.__completed_at_attr__, when)
        started = getattr(self, 'started_at', None)
        if started is not None:
            for dattr in ('duration_seconds', 'duration'):
                if dattr in self.__table__.columns:
                    setattr(self, dattr, (when - started).total_seconds())
                    break
        return self
