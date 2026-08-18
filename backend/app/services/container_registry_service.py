"""Container registry credential store + ``docker login`` orchestration.

Stores per-registry credentials (Fernet-encrypted secret) and runs
``docker login`` before a private image is pulled, then ``docker logout`` to
avoid leaving a session on disk. The secret is piped via **stdin**
(``--password-stdin``) — never placed on argv (where it would leak into
``ps``/process listings) or written to logs.

A single ``docker login`` authenticates both ``docker pull`` and
``docker compose pull`` for that host, so this service backs the standalone
single-container path (``DockerService.pull_image``) and the compose path
(``apps.start_app`` / ``apps.apply_image_update``) alike.
"""
import logging
import os
import subprocess
from datetime import datetime

from app import db
from app.utils.system import run_checked
from app.models.container_registry import ContainerRegistry
from app.utils.crypto import encrypt_secret, decrypt_secret_safe

logger = logging.getLogger(__name__)


class ContainerRegistryService:
    """CRUD + docker-login helpers for private container registries."""

    # ── CRUD ──
    @staticmethod
    def list_registries(workspace_id=None):
        """All registries visible in a workspace: the workspace's own plus every
        global (``workspace_id IS NULL``) one. No workspace context => all."""
        q = ContainerRegistry.query
        if workspace_id is not None:
            q = q.filter(db.or_(
                ContainerRegistry.workspace_id == workspace_id,
                ContainerRegistry.workspace_id.is_(None),
            ))
        return q.order_by(ContainerRegistry.created_at.desc()).all()

    @staticmethod
    def get(registry_id):
        if not registry_id:
            return None
        return ContainerRegistry.query.get(registry_id)

    @staticmethod
    def create(name, provider='generic', registry_url=None, username=None,
               secret=None, workspace_id=None, created_by=None):
        reg = ContainerRegistry(
            name=(name or '').strip() or 'Registry',
            provider=(provider or 'generic').strip().lower(),
            registry_url=(registry_url or '').strip() or None,
            username=(username or '').strip() or None,
            workspace_id=workspace_id,
            created_by=created_by,
        )
        if secret:
            reg.secret_encrypted = encrypt_secret(secret)
        db.session.add(reg)
        db.session.commit()
        return reg

    @staticmethod
    def update(registry, *, name=None, provider=None, registry_url=None,
               username=None, secret=None):
        if name is not None and name.strip():
            registry.name = name.strip()
        if provider is not None and provider.strip():
            registry.provider = provider.strip().lower()
        if registry_url is not None:
            registry.registry_url = registry_url.strip() or None
        if username is not None:
            registry.username = username.strip() or None
        # Only replace the secret when a new one is actually supplied, so an edit
        # of the label/URL never wipes the stored credential.
        if secret:
            registry.secret_encrypted = encrypt_secret(secret)
        db.session.commit()
        return registry

    @staticmethod
    def delete(registry):
        db.session.delete(registry)
        db.session.commit()

    # ── secret resolution ──
    @staticmethod
    def _password(registry):
        """Plaintext password for ``docker login``. For ECR, exchange the stored
        AWS keys for a short-lived token lazily; otherwise decrypt the stored
        secret."""
        if registry.provider == 'ecr':
            token = ContainerRegistryService.ecr_password(registry)
            if token:
                return token
        if not registry.secret_encrypted:
            return None
        return decrypt_secret_safe(registry.secret_encrypted)

    # ── docker login / logout ──
    @staticmethod
    def login(registry):
        """``docker login`` the registry, piping the secret via stdin. Returns
        ``{'success': bool, 'error'?: str}``. Never logs the secret."""
        username = registry.login_username()
        if not username:
            return {'success': False, 'error': 'Registry has no username configured'}
        password = ContainerRegistryService._password(registry)
        if not password:
            return {'success': False, 'error': 'No stored secret for this registry'}

        host = registry.login_host()
        # Secret goes on stdin via --password-stdin, NEVER on argv.
        cmd = ['docker', 'login', host, '-u', username, '--password-stdin']
        result = run_checked(cmd, input=password, timeout=None)

        if result['success']:
            try:
                registry.last_used_at = datetime.utcnow()
                db.session.commit()
            except Exception:
                db.session.rollback()
            return {'success': True}
        return {'success': False, 'error': result['error'] or 'docker login failed'}

    @staticmethod
    def logout(host):
        """Best-effort ``docker logout`` of a host — cleanup, never raises."""
        if not host:
            return
        try:
            run_checked(['docker', 'logout', host], timeout=None)
        except Exception:
            pass

    @staticmethod
    def test_connection(registry):
        """``docker login`` then immediately ``docker logout`` — report
        success/failure without leaving a session behind."""
        result = ContainerRegistryService.login(registry)
        ContainerRegistryService.logout(registry.login_host())
        return result

    @staticmethod
    def ecr_password(registry):
        """Best-effort AWS ECR token via ``aws ecr get-login-password``.

        Optional/lazy: needs the AWS CLI on PATH. The stored secret may hold
        ``ACCESS_KEY_ID:SECRET_ACCESS_KEY``; if so it is passed through the
        environment for this one call. Returns a password string, or ``None`` if
        the CLI is missing or the exchange fails (kept defensive so a
        misconfigured ECR entry never crashes a deploy)."""
        try:
            host = registry.login_host()
            region = None
            parts = host.split('.')
            if 'ecr' in parts:
                idx = parts.index('ecr')
                if idx + 1 < len(parts):
                    region = parts[idx + 1]

            env = None
            secret = decrypt_secret_safe(registry.secret_encrypted or '')
            if secret and ':' in secret:
                access_key, secret_key = secret.split(':', 1)
                env = dict(os.environ)
                env['AWS_ACCESS_KEY_ID'] = access_key.strip()
                env['AWS_SECRET_ACCESS_KEY'] = secret_key.strip()

            cmd = ['aws', 'ecr', 'get-login-password']
            if region:
                cmd += ['--region', region]
            result = run_checked(cmd, env=env, timeout=None)
            if result['success']:
                return result['output'].strip()
            logger.debug('aws ecr get-login-password failed: %s', result['error'])
        except Exception as e:  # pragma: no cover - defensive
            logger.debug('ECR password exchange error: %s', e)
        return None

    # ── app helpers (compose + single-container deploy paths) ──
    @staticmethod
    def for_app(app):
        """The ContainerRegistry bound to an app via ``registry_id``, or None."""
        return ContainerRegistryService.get(getattr(app, 'registry_id', None))

    @staticmethod
    def login_for_app(app):
        """``docker login`` for an app's bound registry, if any. Best-effort:
        returns the ContainerRegistry that was logged into (so the caller can log
        out in a ``finally``), or ``None`` when the app has no registry."""
        registry = ContainerRegistryService.for_app(app)
        if registry is None:
            return None
        ContainerRegistryService.login(registry)
        return registry

    @staticmethod
    def logout_for_app(registry):
        """Counterpart to :meth:`login_for_app`; no-op when ``registry`` is None."""
        if registry is not None:
            ContainerRegistryService.logout(registry.login_host())
