from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin
from app.models.json_column_mixin import JsonColumnMixin


class ManagedDatabaseUser(TimestampMixin, JsonColumnMixin, db.Model):
    """A database user/grant ServerKit created on a managed database.

    Live engines forget nothing, but ServerKit used to: users created through
    the panel left no durable trace, so restarts lost the mapping between a
    managed database and the credentials provisioned for it. This row is that
    trace — it powers the users panel and scopes one-click admin SSO.

    ``is_shadow`` marks short-lived, single-use credentials (e.g. the Adminer
    SSO login) that a reaper drops once ``expires_at`` passes. Passwords are
    NEVER stored here — they cross the API exactly once at creation time.
    """

    __tablename__ = 'managed_database_users'

    id = db.Column(db.Integer, primary_key=True)
    managed_database_id = db.Column(
        db.Integer, db.ForeignKey('managed_databases.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    username = db.Column(db.String(120), nullable=False)
    # JSON list of grant keywords, e.g. ["ALL"] or ["SELECT", "INSERT"].
    grants = db.Column(db.Text, nullable=False, default='["ALL"]')
    is_shadow = db.Column(db.Boolean, nullable=False, default=False)
    expires_at = db.Column(db.DateTime, nullable=True)

    # Deleting the managed database removes its user rows (ORM cascade); the
    # engine-side users are dropped explicitly by the service, never implicitly.
    managed_database = db.relationship(
        'ManagedDatabase',
        backref=db.backref('users', cascade='all, delete-orphan'),
    )

    __table_args__ = (
        db.UniqueConstraint('managed_database_id', 'username',
                            name='uq_managed_db_user'),
    )

    def get_grants(self):
        return self._json_read('grants', [], expect=list)

    def set_grants(self, grants):
        self._json_write('grants', list(grants or []), falsy='[]')

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at < datetime.utcnow())

    def to_dict(self, live=None):
        data = {
            'id': self.id,
            'managed_database_id': self.managed_database_id,
            'username': self.username,
            'grants': self.get_grants(),
            'is_shadow': self.is_shadow,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if live is not None:
            data['present'] = live.get('present')
        return data

    def __repr__(self):
        return f'<ManagedDatabaseUser {self.username} db={self.managed_database_id}>'
