from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin
from app.models.json_column_mixin import JsonColumnMixin
from cryptography.fernet import Fernet
import os
import base64
import hashlib


class EnvironmentVariable(TimestampMixin, JsonColumnMixin, db.Model):
    """
    Stores environment variables for applications with encrypted values.
    Supports versioning for history tracking.
    """
    __tablename__ = 'environment_variables'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    encrypted_value = db.Column(db.Text, nullable=False)
    is_secret = db.Column(db.Boolean, default=False)  # Mark sensitive values
    description = db.Column(db.String(500), nullable=True)  # Optional description
    # Compose service this var targets (NULL = all services). Lets a compose app
    # scope a variable to one service in the managed env overlay.
    target_service = db.Column(db.String(120), nullable=True)
    # Reference source (manifest fromSecret/fromService/generate). When set, the
    # real value is resolved at injection time and never stored in
    # encrypted_value — masking stays intact and a rotated secret propagates on
    # the next deploy/restart. JSON e.g. {"kind":"secret","secret":"stripe"} or
    # {"kind":"service","service":"db","property":"connectionString"}.
    value_from = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Unique constraint: one key per application
    __table_args__ = (
        db.UniqueConstraint('application_id', 'key', name='unique_app_env_key'),
    )

    # One crypto path (plan 77 C2): new writes encrypt via utils/crypto
    # (SERVERKIT_ENCRYPTION_KEY). Reads dual-read: the one path first, then
    # the legacy SECRET_KEY-derived Fernet this model historically used —
    # rows written before the fold-in decrypt forever without a bulk
    # re-encrypt pass (the PR #94 postmortem records a decrypt-all→
    # re-encrypt-all attempt double-wrapping credentials; never again).
    # Rotating SECRET_KEY still bricks only legacy rows, exactly as before.
    _legacy_fernet = None

    @classmethod
    def _get_legacy_fernet(cls):
        """The pre-C2 Fernet (key derived from SECRET_KEY via SHA256)."""
        if cls._legacy_fernet is None:
            secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
            key = hashlib.sha256(secret_key.encode()).digest()
            cls._legacy_fernet = Fernet(base64.urlsafe_b64encode(key))
        return cls._legacy_fernet

    @classmethod
    def encrypt_value(cls, value):
        """Encrypt a value for storage (the ONE key path)."""
        from app.utils.crypto import encrypt_secret
        if value is None:
            value = ''
        return encrypt_secret(value)

    @classmethod
    def decrypt_value(cls, encrypted_value):
        """Decrypt a stored value: one path first, legacy key second."""
        if not encrypted_value:
            return ''
        from app.utils.crypto import decrypt_secret
        try:
            return decrypt_secret(encrypted_value)
        except Exception:
            pass
        try:
            return cls._get_legacy_fernet().decrypt(encrypted_value.encode()).decode()
        except Exception:
            return '[DECRYPTION_ERROR]'

    @property
    def value(self):
        """Get the decrypted value."""
        return self.decrypt_value(self.encrypted_value)

    @value.setter
    def value(self, plaintext):
        """Set the value (encrypts automatically)."""
        self.encrypted_value = self.encrypt_value(plaintext)

    def get_reference(self):
        """Parsed value_from reference, or None for a plain value."""
        return self._json_read('value_from', None)

    def set_reference(self, ref):
        self._json_write('value_from', ref)

    def to_dict(self, include_value=True, mask_secrets=False):
        """Convert to dictionary, optionally masking secret values."""
        reference = self.get_reference()
        result = {
            'id': self.id,
            'application_id': self.application_id,
            'key': self.key,
            'is_secret': self.is_secret,
            'description': self.description,
            'target_service': self.target_service,
            'is_reference': bool(reference),
            'value_from': reference,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_value:
            if reference:
                # a reference's real value is never serialized here
                result['value'] = '••••••••' if mask_secrets else ''
            elif mask_secrets and self.is_secret:
                result['value'] = '••••••••'
            else:
                result['value'] = self.value

        return result

    def __repr__(self):
        return f'<EnvironmentVariable {self.key}>'


class EnvironmentVariableHistory(db.Model):
    """
    Tracks history of environment variable changes for auditing.
    """
    __tablename__ = 'environment_variable_history'

    id = db.Column(db.Integer, primary_key=True)
    env_variable_id = db.Column(db.Integer, nullable=False)  # Not FK to allow deleted vars
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # 'created', 'updated', 'deleted'
    old_value_hash = db.Column(db.String(64), nullable=True)  # SHA256 hash (not the actual value)
    new_value_hash = db.Column(db.String(64), nullable=True)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def hash_value(cls, value):
        """Create a hash of the value for comparison (not for storage of actual value)."""
        if value is None:
            return None
        return hashlib.sha256(value.encode()).hexdigest()

    @classmethod
    def record_change(cls, env_var, action, old_value=None, new_value=None, user_id=None):
        """Record a change to an environment variable."""
        history = cls(
            env_variable_id=env_var.id if env_var.id else 0,
            application_id=env_var.application_id,
            key=env_var.key,
            action=action,
            old_value_hash=cls.hash_value(old_value) if old_value else None,
            new_value_hash=cls.hash_value(new_value) if new_value else None,
            changed_by=user_id
        )
        db.session.add(history)
        return history

    def to_dict(self):
        return {
            'id': self.id,
            'env_variable_id': self.env_variable_id,
            'application_id': self.application_id,
            'key': self.key,
            'action': self.action,
            'changed_by': self.changed_by,
            'changed_at': self.changed_at.isoformat() if self.changed_at else None,
        }
