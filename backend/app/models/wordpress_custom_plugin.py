"""WordPress Global Plugin Library models.

A thin global layer on top of the existing per-site WP-CLI plugin management:

- ``WordPressCustomPlugin`` — one row per operator-owned plugin registered in the
  global library (sourced from a GitHub repo or a local path).
- ``WordPressSitePlugin`` — one row per (library plugin, site) installation, so
  the panel knows which installed plugins are library-managed and whether a site
  is behind the library version.
"""

from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin, SerializableMixin


class WordPressCustomPlugin(TimestampMixin, db.Model):
    """An operator-owned plugin in the global library."""

    __tablename__ = 'wordpress_custom_plugins'

    id = db.Column(db.Integer, primary_key=True)

    # Plugin folder slug, e.g. ``my-custom-plugin`` (the wp-content/plugins dir name)
    slug = db.Column(db.String(200), nullable=False, unique=True, index=True)

    # Parsed from the plugin header on sync
    name = db.Column(db.String(255))
    description = db.Column(db.Text)
    version = db.Column(db.String(50))
    author = db.Column(db.String(255))

    # Source
    source_type = db.Column(db.String(20), nullable=False, default='github')  # github | local
    source_url = db.Column(db.String(500), nullable=False)  # owner/repo, git URL, or local path
    branch = db.Column(db.String(100), default='main')      # branch or tag to track
    # Optional source connection for authenticated (private) GitHub/GitLab clones
    connection_id = db.Column(db.Integer, nullable=True)

    is_active = db.Column(db.Boolean, default=True)

    last_synced_at = db.Column(db.DateTime)
    sync_error = db.Column(db.Text)


    installations = db.relationship(
        'WordPressSitePlugin',
        backref='plugin',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )

    def install_count(self):
        return self.installations.filter(
            WordPressSitePlugin.status != 'not_installed'
        ).count()

    def to_dict(self, include_installations=False):
        result = {
            'id': self.id,
            'slug': self.slug,
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'author': self.author,
            'source_type': self.source_type,
            'source_url': self.source_url,
            'branch': self.branch,
            'connection_id': self.connection_id,
            'is_active': self.is_active,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
            'sync_error': self.sync_error,
            'install_count': self.install_count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_installations:
            result['installations'] = [i.to_dict() for i in self.installations]
        return result

    def __repr__(self):
        return f'<WordPressCustomPlugin {self.id} {self.slug}>'


class WordPressSitePlugin(SerializableMixin, db.Model):
    """A library plugin installed on a specific WordPress site."""

    __tablename__ = 'wordpress_site_plugins'
    __table_args__ = (
        db.UniqueConstraint('wordpress_site_id', 'custom_plugin_id',
                            name='uq_site_custom_plugin'),
    )

    id = db.Column(db.Integer, primary_key=True)
    wordpress_site_id = db.Column(
        db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=False, index=True)
    custom_plugin_id = db.Column(
        db.Integer, db.ForeignKey('wordpress_custom_plugins.id'), nullable=False, index=True)

    installed_version = db.Column(db.String(50))
    status = db.Column(db.String(20), default='not_installed')  # active | inactive | not_installed | error

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


    def __repr__(self):
        return f'<WordPressSitePlugin site={self.wordpress_site_id} plugin={self.custom_plugin_id} {self.status}>'
