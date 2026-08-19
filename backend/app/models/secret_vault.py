import json
from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin
from app.utils.crypto import encrypt_secret, decrypt_secret_safe


class SecretVault(TimestampMixin, db.Model):
    """A named vault for encrypted secrets."""
    __tablename__ = 'secret_vaults'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    slug = db.Column(db.String(220), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Workspace scoping (#33): a vault belongs to a workspace. Backfilled to the
    # Default workspace by migration 021; new rows are stamped on create.
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)

    secrets = db.relationship('Secret', backref='vault', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'workspace_id': self.workspace_id,
            'secret_count': self.secrets.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Secret(TimestampMixin, db.Model):
    """An encrypted secret inside a vault."""
    __tablename__ = 'secrets'

    id = db.Column(db.Integer, primary_key=True)
    vault_id = db.Column(db.Integer, db.ForeignKey('secret_vaults.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    encrypted_value = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('vault_id', 'name', name='uq_secret_vault_name'),
    )

    @property
    def value(self):
        return decrypt_secret_safe(self.encrypted_value)

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < datetime.utcnow()

    def to_dict(self, include_value=False, mask=False):
        result = {
            'id': self.id,
            'vault_id': self.vault_id,
            'name': self.name,
            'description': self.description,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_expired': self.is_expired,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_value:
            result['value'] = '••••••••' if mask else self.value
        return result
