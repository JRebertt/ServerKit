from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import TimestampMixin
import json


class Workspace(JsonColumnMixin, TimestampMixin, db.Model):
    """Isolated container for servers, users, and settings."""
    __tablename__ = 'workspaces'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    slug = db.Column(db.String(128), nullable=False, unique=True)
    description = db.Column(db.Text)

    # Branding
    logo_url = db.Column(db.String(512))
    primary_color = db.Column(db.String(7))  # hex color

    # Settings
    settings_json = db.Column(db.Text)

    # Quotas
    max_servers = db.Column(db.Integer, default=0)  # 0 = unlimited
    max_users = db.Column(db.Integer, default=0)
    max_api_calls = db.Column(db.Integer, default=0)

    # Status
    STATUS_ACTIVE = 'active'
    STATUS_ARCHIVED = 'archived'
    status = db.Column(db.String(32), default=STATUS_ACTIVE)

    # Billing
    billing_notes = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    members = db.relationship('WorkspaceMember', backref='workspace', lazy='dynamic')
    api_keys = db.relationship('WorkspaceApiKey', backref='workspace', lazy='dynamic')

    @property
    def settings(self):
        return self._json_read('settings_json')

    @settings.setter
    def settings(self, v):
        self.settings_json = json.dumps(v)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'logo_url': self.logo_url,
            'primary_color': self.primary_color,
            'settings': self.settings,
            'max_servers': self.max_servers,
            'max_users': self.max_users,
            'max_api_calls': self.max_api_calls,
            'status': self.status,
            'member_count': self.members.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Workspace {self.name}>'


class WorkspaceMember(db.Model):
    """Maps users to workspaces with roles."""
    __tablename__ = 'workspace_members'

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    ROLE_OWNER = 'owner'
    ROLE_ADMIN = 'admin'
    ROLE_MEMBER = 'member'
    ROLE_VIEWER = 'viewer'
    role = db.Column(db.String(32), default=ROLE_MEMBER)

    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('workspace_memberships', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_user'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'email': self.user.email if self.user else None,
            'role': self.role,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
        }


class WorkspaceApiKey(JsonColumnMixin, db.Model):
    """API keys scoped to a single workspace."""
    __tablename__ = 'workspace_api_keys'

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    key_hash = db.Column(db.String(256), nullable=False)
    key_prefix = db.Column(db.String(16))
    scopes_json = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)

    @property
    def scopes(self):
        return self._json_read('scopes_json', [])

    @scopes.setter
    def scopes(self, v):
        self.scopes_json = json.dumps(v)

    def to_dict(self):
        return {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'name': self.name,
            'key_prefix': self.key_prefix,
            'scopes': self.scopes,
            'is_active': self.is_active,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }


class ResourceGrant(db.Model):
    """Per-resource access grant (#33 — per-site ACL): grants a user access to a
    specific resource they don't own (e.g. an application and, transitively, its
    WordPress site / databases / domains).

    Access-level for now — a granted user can see and operate the resource like an
    owner. Per-grant view/edit roles are a future refinement; the `role` column is
    reserved for it but not yet enforced.
    """
    __tablename__ = 'resource_grants'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    resource_type = db.Column(db.String(32), nullable=False)   # 'application'
    resource_id = db.Column(db.Integer, nullable=False, index=True)
    role = db.Column(db.String(16), default='editor')          # reserved for view/edit
    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'resource_type', 'resource_id', name='uq_resource_grant'),
    )

    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('resource_grants', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'email': self.user.email if self.user else None,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'role': self.role,
            'granted_by': self.granted_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
