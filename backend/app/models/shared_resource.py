"""Polymorphic shared resources: tags + shared variable groups.

This is the *facade layer* for cross-resource tagging and shared configuration.
It lives BESIDE the existing per-resource tables (e.g. ``environment_variables``)
and never touches them — any resource (application, database, service, wordpress
site, server) is addressed polymorphically via ``(resource_type, resource_id)``.

``resource_id`` is stored as a String so the same column can address resources
whose primary key is an int (applications, servers) or a non-int handle
(docker container names, service slugs) without schema changes.

Secret values reuse the *exact* Fernet derivation used by
``app.models.env_variable.EnvironmentVariable`` (SHA256(SECRET_KEY) →
urlsafe-b64 → Fernet) so secrets are encrypted at rest with the same key
source the rest of the panel already uses.
"""
from datetime import datetime

from app import db
from app.models.mixins import SerializableMixin
from app.models.env_variable import EnvironmentVariable

# The mask used in place of a redacted secret value. Matches the convention in
# env_variable.py / sensitive_data_filter.py.
SECRET_MASK = '••••••••'


class ResourceTag(SerializableMixin, db.Model):
    """A free-form tag attached to any resource via (resource_type, resource_id)."""
    __tablename__ = 'resource_tags'

    id = db.Column(db.Integer, primary_key=True)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.String(255), nullable=False)
    tag = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('resource_type', 'resource_id', 'tag',
                            name='uq_resource_tag'),
        db.Index('ix_resource_tag_resource', 'resource_type', 'resource_id'),
    )


    def __repr__(self):
        return f'<ResourceTag {self.resource_type}:{self.resource_id} #{self.tag}>'


class SharedVariableGroup(db.Model):
    """A named bundle of variables that can be attached to many resources.

    Scoped by ``(scope_type, scope_id)`` — e.g. a 'workspace' group, a 'project'
    group, or an 'environment' group — so the same panel can offer different
    group catalogs depending on the surface it is embedded in.
    """
    __tablename__ = 'shared_variable_groups'

    SCOPE_WORKSPACE = 'workspace'
    SCOPE_PROJECT = 'project'
    SCOPE_ENVIRONMENT = 'environment'
    VALID_SCOPES = (SCOPE_WORKSPACE, SCOPE_PROJECT, SCOPE_ENVIRONMENT)

    id = db.Column(db.Integer, primary_key=True)
    scope_type = db.Column(db.String(50), nullable=False)
    scope_id = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    variables = db.relationship(
        'SharedVariable', backref='group', lazy='select',
        cascade='all, delete-orphan',
    )
    attachments = db.relationship(
        'SharedVariableGroupAttachment', backref='group', lazy='select',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.Index('ix_shared_group_scope', 'scope_type', 'scope_id'),
    )

    def to_dict(self, include_variables=False, mask_secrets=True):
        result = {
            'id': self.id,
            'scope_type': self.scope_type,
            'scope_id': self.scope_id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'variable_count': len(self.variables),
            'attachment_count': len(self.attachments),
        }
        if include_variables:
            result['variables'] = [
                v.to_dict(mask_secrets=mask_secrets) for v in self.variables
            ]
        return result

    def __repr__(self):
        return f'<SharedVariableGroup {self.scope_type}:{self.scope_id}/{self.name}>'


class SharedVariable(db.Model):
    """A single key/value held by a :class:`SharedVariableGroup`.

    Values are encrypted at rest with the same Fernet key the per-app
    environment variables use (delegated to ``EnvironmentVariable``), so there
    is a single key source for all secret material in the panel.
    """
    __tablename__ = 'shared_variables'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('shared_variable_groups.id'),
                         nullable=False, index=True)
    key = db.Column(db.String(255), nullable=False)
    encrypted_value = db.Column(db.Text, nullable=False)
    is_secret = db.Column(db.Boolean, default=False)
    # Compose service this var targets (NULL = all services), mirroring
    # EnvironmentVariable.target_service so shared vars can also be scoped.
    target_service = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'key', name='uq_shared_var_key'),
    )

    # --- encryption (reuse the env-var Fernet helper; same key source) -------

    @property
    def value(self):
        """Decrypted plaintext value."""
        return EnvironmentVariable.decrypt_value(self.encrypted_value)

    @value.setter
    def value(self, plaintext):
        """Set the value (encrypts automatically with the shared Fernet key)."""
        self.encrypted_value = EnvironmentVariable.encrypt_value(plaintext)

    def to_dict(self, include_value=True, mask_secrets=True):
        result = {
            'id': self.id,
            'group_id': self.group_id,
            'key': self.key,
            'is_secret': self.is_secret,
            'target_service': self.target_service,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_value:
            if mask_secrets and self.is_secret:
                result['value'] = SECRET_MASK
            else:
                result['value'] = self.value
        return result

    def __repr__(self):
        return f'<SharedVariable {self.key}>'


class SharedVariableGroupAttachment(SerializableMixin, db.Model):
    """Links a :class:`SharedVariableGroup` to a resource polymorphically."""
    __tablename__ = 'shared_variable_group_attachments'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('shared_variable_groups.id'),
                         nullable=False, index=True)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'resource_type', 'resource_id',
                            name='uq_group_attachment'),
        db.Index('ix_group_attachment_resource', 'resource_type', 'resource_id'),
    )


    def __repr__(self):
        return (f'<SharedVariableGroupAttachment g{self.group_id} '
                f'{self.resource_type}:{self.resource_id}>')
