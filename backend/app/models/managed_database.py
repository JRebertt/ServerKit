from datetime import datetime

from app import db
from app.models.mixins import EncryptedSecret, SoftDeleteMixin

# Engines whose lifecycle ServerKit actually drives (Mongo stays read-first).
VALID_DB_ENGINES = ('mysql', 'postgresql', 'mongodb')


class ManagedDatabase(SoftDeleteMixin, db.Model):
    """A database ServerKit tracks as a first-class resource.

    Adds durable state (backups, connection strings, ownership) **beside** the
    live introspection in ``database_service`` — it does NOT replace that
    discovery/browse surface. ``origin`` records whether ServerKit provisioned it
    (``provisioned``) or adopted a live-discovered one (``adopted``).

    The admin secret is Fernet-encrypted at rest (same helper as
    ``SourceConnection``); it is masked in API responses and revealed only through
    an explicit, audited action.

    Soft-deletable (plan 77 B5): a plain delete tombstones the row into the
    Recycle Bin — the actual database server-side is untouched and any managed
    backup policy keeps running, so restore brings everything back intact. The
    explicit ``?drop=true`` path stays immediately destructive. Read paths use
    ``query_active()``.
    """

    __tablename__ = 'managed_databases'

    # Default listening ports per engine, used when a row doesn't pin one.
    DEFAULT_PORTS = {'mysql': 3306, 'postgresql': 5432, 'mongodb': 27017}
    # URI scheme per engine for build_connection_uri.
    URI_SCHEMES = {'mysql': 'mysql', 'postgresql': 'postgresql', 'mongodb': 'mongodb'}

    id = db.Column(db.Integer, primary_key=True)
    engine = db.Column(db.String(20), nullable=False, index=True)   # mysql|postgresql|mongodb
    name = db.Column(db.String(200), nullable=False)                # database name on the server
    host_kind = db.Column(db.String(20), nullable=False, default='host')  # host|docker
    container_ref = db.Column(db.String(200), nullable=True)        # container name/id when docker
    host = db.Column(db.String(255), nullable=False, default='localhost')
    port = db.Column(db.Integer, nullable=True)
    # The app this DB backs, if any. SET NULL on app delete so the tracked DB
    # survives its app being removed.
    owner_application_id = db.Column(
        db.Integer, db.ForeignKey('applications.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    origin = db.Column(db.String(20), nullable=False, default='provisioned')  # provisioned|adopted
    admin_username = db.Column(db.String(180), nullable=True)
    admin_secret_encrypted = db.Column(db.Text, nullable=True)
    admin_secret = EncryptedSecret('admin_secret_encrypted', legacy_plaintext=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('engine', 'host', 'name', name='uq_managed_database'),
    )

    def effective_port(self):
        return self.port or self.DEFAULT_PORTS.get(self.engine)

    def to_dict(self, connection_uri=None):
        data = {
            'id': self.id,
            'engine': self.engine,
            'name': self.name,
            'host_kind': self.host_kind,
            'container_ref': self.container_ref,
            'host': self.host,
            'port': self.effective_port(),
            'owner_application_id': self.owner_application_id,
            'origin': self.origin,
            'admin_username': self.admin_username,
            # Never serialize the secret — expose only whether one is stored.
            'has_secret': bool(self.admin_secret_encrypted),
            'workspace_id': self.workspace_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if connection_uri is not None:
            data['connection_uri'] = connection_uri
        return data

    def __repr__(self):
        return f'<ManagedDatabase {self.engine}:{self.name}@{self.host}>'
