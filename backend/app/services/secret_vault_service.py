"""Encrypted secrets manager (vault + secret) service."""
import json
import logging
import re
import secrets
from datetime import datetime
from typing import Dict, List, Optional

from app import db
from app.exceptions import (
    ApplicationError,
    ConflictError,
    DependencyUnavailableError,
    NotFoundError,
    ValidationError,
)
from app.models import Secret, SecretVault
from app.utils.crypto import encrypt_secret, decrypt_secret_safe
from app.utils.slug import unique_slug

logger = logging.getLogger(__name__)


def _unique_slug(name: str) -> str:
    return unique_slug(
        name,
        lambda s: SecretVault.query.filter_by(slug=s).first() is not None,
        default='vault',
    )


class SecretVaultService:
    """Manage encrypted secret vaults."""

    @classmethod
    def list_vaults(cls, workspace_id: int = None) -> List[Dict]:
        query = SecretVault.query
        if workspace_id is not None:
            query = query.filter(SecretVault.workspace_id == workspace_id)
        return [v.to_dict() for v in query.order_by(SecretVault.name).all()]

    @classmethod
    def get_vault(cls, vault_id: int) -> Optional[SecretVault]:
        return SecretVault.query.get(vault_id)

    @classmethod
    def create_vault(cls, name: str, description: str = None, user_id: int = None,
                     workspace_id: int = None) -> Dict:
        if SecretVault.query.filter_by(name=name).first():
            raise ConflictError('Vault name already exists')
        vault = SecretVault(
            name=name,
            slug=_unique_slug(name),
            description=description,
            created_by=user_id,
            workspace_id=workspace_id,
        )
        db.session.add(vault)
        db.session.commit()
        return vault.to_dict()

    @classmethod
    def update_vault(cls, vault_id: int, name: str = None, description: str = None) -> Dict:
        vault = cls.get_vault(vault_id)
        if not vault:
            raise NotFoundError('Vault not found')
        if name is not None:
            existing = SecretVault.query.filter(SecretVault.name == name, SecretVault.id != vault_id).first()
            if existing:
                raise ConflictError('Vault name already exists')
            vault.name = name
        if description is not None:
            vault.description = description
        db.session.commit()
        return vault.to_dict()

    @classmethod
    def delete_vault(cls, vault_id: int) -> Dict:
        vault = cls.get_vault(vault_id)
        if not vault:
            raise NotFoundError('Vault not found')
        db.session.delete(vault)
        db.session.commit()


class SecretService:
    """Manage encrypted secrets inside vaults."""

    _NAME_RE = re.compile(r'^[A-Z_][A-Z0-9_]*$', re.IGNORECASE)

    @classmethod
    def list_secrets(cls, vault_id: int) -> List[Dict]:
        return [s.to_dict(include_value=True, mask=True) for s in Secret.query.filter_by(vault_id=vault_id).order_by(Secret.name).all()]

    @classmethod
    def get_secret(cls, secret_id: int) -> Optional[Secret]:
        return Secret.query.get(secret_id)

    @classmethod
    def get_secret_by_name(cls, vault_id: int, name: str) -> Optional[Secret]:
        return Secret.query.filter_by(vault_id=vault_id, name=name).first()

    @classmethod
    def _validate_name(cls, name: str) -> None:
        if not name:
            raise ValidationError('Name is required')
        if not cls._NAME_RE.match(name):
            raise ValidationError('Name must start with a letter or underscore and contain only letters, digits, and underscores')

    @classmethod
    def create_secret(cls, vault_id: int, name: str, value: str,
                      description: str = None, expires_at=None) -> Dict:
        if not SecretVault.query.get(vault_id):
            raise NotFoundError('Vault not found')
        cls._validate_name(name)
        if Secret.query.filter_by(vault_id=vault_id, name=name).first():
            raise ConflictError('Secret name already exists in this vault')
        try:
            encrypted = encrypt_secret(value)
        except Exception as e:
            raise ValidationError(str(e), code='encryption_error') from e
        secret = Secret(
            vault_id=vault_id,
            name=name,
            encrypted_value=encrypted,
            description=description,
            expires_at=expires_at,
        )
        db.session.add(secret)
        db.session.commit()
        return secret.to_dict(include_value=True, mask=True)

    @classmethod
    def update_secret(cls, secret_id: int, value: str = None, description: str = None,
                      expires_at=None, rotate: bool = False) -> Dict:
        secret = cls.get_secret(secret_id)
        if not secret:
            raise NotFoundError('Secret not found')
        if value is not None:
            try:
                secret.encrypted_value = encrypt_secret(value)
            except Exception as e:
                raise ValidationError(str(e), code='encryption_error') from e
            secret.updated_at = datetime.utcnow()
        if description is not None:
            secret.description = description
        if expires_at is not None:
            secret.expires_at = expires_at
        if rotate:
            decrypted = secret.value
            if decrypted:
                try:
                    secret.encrypted_value = encrypt_secret(decrypted)
                except Exception as e:
                    raise ValidationError(str(e), code='encryption_error') from e
                secret.updated_at = datetime.utcnow()
        db.session.commit()
        return secret.to_dict(include_value=True, mask=True)

    @classmethod
    def delete_secret(cls, secret_id: int) -> Dict:
        secret = cls.get_secret(secret_id)
        if not secret:
            raise NotFoundError('Secret not found')
        db.session.delete(secret)
        db.session.commit()

    @classmethod
    def upsert_internal_secret(cls, vault_id: int, name: str, value: str, *,
                               description: str = None, expires_at=None) -> Secret:
        """Create-or-update a service-owned secret, returning the model row.

        For internal writers (Recipe run handoffs today) that namespace their
        own machine-generated names inside a dedicated vault slug — the human
        display-name grammar does not apply, but the encryption still lives
        here so this service stays the one door to it.
        """
        encrypted = encrypt_secret(value)
        secret = cls.get_secret_by_name(vault_id, name)
        if secret is None:
            secret = Secret(vault_id=vault_id, name=name)
            db.session.add(secret)
        secret.encrypted_value = encrypted
        if description is not None:
            secret.description = description
        secret.expires_at = expires_at
        db.session.commit()
        return secret

    @classmethod
    def reveal_secret(cls, secret_id: int) -> Dict:
        secret = cls.get_secret(secret_id)
        if not secret:
            raise NotFoundError('Secret not found')
        value = secret.value
        if value is None:
            raise DependencyUnavailableError('Unable to decrypt secret')
        return secret.to_dict(include_value=True, mask=False)

    @classmethod
    def bulk_create_or_update(cls, vault_id: int, secrets_list: List[Dict]) -> Dict:
        """Create or update many secrets. Each item needs name and value.

        Per-item failures are collected, not raised — a bulk import reports
        what it could and could not apply."""
        if not SecretVault.query.get(vault_id):
            raise NotFoundError('Vault not found')
        results = []
        errors = []
        for item in secrets_list:
            name = item.get('name')
            value = item.get('value')
            if not name or value is None:
                errors.append({'name': name, 'error': 'name and value required'})
                continue
            existing = cls.get_secret_by_name(vault_id, name)
            try:
                if existing:
                    results.append(cls.update_secret(existing.id, value=value))
                else:
                    results.append(cls.create_secret(
                        vault_id, name, value, description=item.get('description')))
            except ApplicationError as e:
                errors.append({'name': name, 'error': e.message})
        return {'secrets': results, 'errors': errors}

    @classmethod
    def resolve_env_dict(cls, vault_id: int, prefix: str = '') -> Dict[str, str]:
        """Resolve vault secrets to an env-style dict (server-side use only)."""
        secrets = Secret.query.filter_by(vault_id=vault_id).all()
        env = {}
        for s in secrets:
            if s.is_expired:
                continue
            value = s.value
            if value is None:
                continue
            key = f'{prefix}{s.name}'
            env[key] = value
        return env
