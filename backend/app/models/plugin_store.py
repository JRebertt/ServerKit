"""Per-plugin key/value storage.

An extension that needed to remember anything previously had to add a model to
core plus an Alembic migration — which is why extension tables like
``ext_serverkit_minecraft_*`` live in the core migration history. That is a
steep tax on small extensions and it puts plugin schema in the panel's own
upgrade path.

One row here is one key for one plugin. ``value`` is a native JSON column (the
dominant pattern in this codebase, and dialect-agnostic across SQLite and
PostgreSQL), so a plugin stores dicts, lists and scalars without serialising by
hand. Keys are opaque to the panel; namespace inside your own key space
(``world:1:seed``) if you want structure.

This does NOT replace ``InstalledPlugin.config``: config is panel-owned settings
an admin edits from the Marketplace, whereas the store is the plugin's own
state, written at runtime by the plugin itself.
"""

from datetime import datetime

from app import db


class PluginStore(db.Model):
    """One key/value pair belonging to one installed plugin."""

    __tablename__ = 'plugin_store'

    id = db.Column(db.Integer, primary_key=True)
    # Not a ForeignKey to installed_plugins: rows must survive the plugin row
    # being deleted and re-created by a reinstall, which is the whole point of
    # keeping data across an uninstall that wasn't asked to purge.
    plugin_slug = db.Column(db.String(128), nullable=False, index=True)
    key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('plugin_slug', 'key', name='uq_plugin_store_slug_key'),
    )

    def to_dict(self):
        return {
            'plugin_slug': self.plugin_slug,
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<PluginStore {self.plugin_slug}:{self.key}>'
