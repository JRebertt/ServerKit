from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import TimestampMixin
import json


class AgentPlugin(JsonColumnMixin, TimestampMixin, db.Model):
    """Represents a plugin that can be installed on agents."""
    __tablename__ = 'agent_plugins'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    display_name = db.Column(db.String(256), nullable=False)
    version = db.Column(db.String(32), nullable=False)
    description = db.Column(db.Text)
    author = db.Column(db.String(128))
    homepage = db.Column(db.String(512))

    # Plugin manifest
    manifest_json = db.Column(db.Text)

    # Capabilities
    capabilities_json = db.Column(db.Text)  # metrics, health_checks, commands, scheduled_tasks, event_hooks

    # Dependencies
    dependencies_json = db.Column(db.Text)  # other plugins required

    # Permissions
    permissions_json = db.Column(db.Text)  # filesystem, network, docker, etc.

    # Resource limits
    max_memory_mb = db.Column(db.Integer, default=128)
    max_cpu_percent = db.Column(db.Integer, default=10)

    # Status
    STATUS_AVAILABLE = 'available'
    STATUS_DEPRECATED = 'deprecated'
    status = db.Column(db.String(32), default=STATUS_AVAILABLE)


    # Relationships
    installations = db.relationship('AgentPluginInstall', backref='plugin', lazy='dynamic')

    @property
    def manifest(self):
        return self._json_read('manifest_json')

    @manifest.setter
    def manifest(self, value):
        self.manifest_json = json.dumps(value)

    @property
    def capabilities(self):
        return self._json_read('capabilities_json', [])

    @capabilities.setter
    def capabilities(self, value):
        self.capabilities_json = json.dumps(value)

    @property
    def dependencies(self):
        return self._json_read('dependencies_json', [])

    @dependencies.setter
    def dependencies(self, value):
        self.dependencies_json = json.dumps(value)

    @property
    def permissions(self):
        return self._json_read('permissions_json', [])

    @permissions.setter
    def permissions(self, value):
        self.permissions_json = json.dumps(value)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'version': self.version,
            'description': self.description,
            'author': self.author,
            'homepage': self.homepage,
            'manifest': self.manifest,
            'capabilities': self.capabilities,
            'dependencies': self.dependencies,
            'permissions': self.permissions,
            'max_memory_mb': self.max_memory_mb,
            'max_cpu_percent': self.max_cpu_percent,
            'status': self.status,
            'install_count': self.installations.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<AgentPlugin {self.name}@{self.version}>'


class AgentPluginInstall(JsonColumnMixin, db.Model):
    """Tracks plugin installations on specific agents/servers."""
    __tablename__ = 'agent_plugin_installs'

    id = db.Column(db.Integer, primary_key=True)
    plugin_id = db.Column(db.Integer, db.ForeignKey('agent_plugins.id'), nullable=False, index=True)
    server_id = db.Column(db.Integer, db.ForeignKey('servers.id'), nullable=False, index=True)

    # Installation state
    STATUS_INSTALLING = 'installing'
    STATUS_ENABLED = 'enabled'
    STATUS_DISABLED = 'disabled'
    STATUS_ERROR = 'error'
    STATUS_UNINSTALLING = 'uninstalling'
    status = db.Column(db.String(32), default=STATUS_INSTALLING)

    installed_version = db.Column(db.String(32))
    config_json = db.Column(db.Text)
    error_message = db.Column(db.Text)

    installed_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Plugin runtime data
    last_health_check = db.Column(db.DateTime)
    health_status = db.Column(db.String(32), default='unknown')  # healthy, degraded, unhealthy, unknown
    metrics_json = db.Column(db.Text)

    server = db.relationship('Server', backref=db.backref('plugin_installs', lazy='dynamic'))

    @property
    def config(self):
        return self._json_read('config_json')

    @config.setter
    def config(self, value):
        self.config_json = json.dumps(value)

    @property
    def metrics(self):
        return self._json_read('metrics_json')

    def to_dict(self):
        return {
            'id': self.id,
            'plugin_id': self.plugin_id,
            'plugin': self.plugin.to_dict() if self.plugin else None,
            'server_id': self.server_id,
            'server_name': self.server.name if self.server else None,
            'status': self.status,
            'installed_version': self.installed_version,
            'config': self.config,
            'error_message': self.error_message,
            'installed_at': self.installed_at.isoformat() if self.installed_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'health_status': self.health_status,
            'metrics': self.metrics,
        }

    def __repr__(self):
        return f'<AgentPluginInstall plugin={self.plugin_id} server={self.server_id}>'
