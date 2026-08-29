from datetime import datetime

from app import db
from app.models.mixins import EncryptedSecret


class ContainerRegistry(db.Model):
    """Stored credentials for a private container registry.

    Lets ServerKit run ``docker login`` before pulling a private image — GitHub
    Container Registry (GHCR), a private Docker Hub repo, GitLab registry, AWS
    ECR, or any generic registry. The secret (password / PAT / token) is
    Fernet-encrypted at rest via ``app.utils.crypto``, mirroring
    ``SourceConnection.access_token_encrypted``; :meth:`to_dict` never returns
    it (it exposes a ``has_secret`` flag instead).

    ``provider`` is a plain string (no enum), matching ``SourceConnection``:
    ``ghcr`` | ``dockerhub`` | ``gitlab`` | ``ecr`` | ``generic``.
    """

    __tablename__ = 'container_registries'

    # Docker Hub's canonical login host, used when registry_url is left blank.
    DOCKERHUB_HOST = 'index.docker.io'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    provider = db.Column(db.String(40), nullable=False, default='generic', index=True)
    # Host to `docker login` against, e.g. 'ghcr.io', 'registry.gitlab.com',
    # '123456.dkr.ecr.us-east-1.amazonaws.com'. Empty => Docker Hub.
    registry_url = db.Column(db.String(255), nullable=True)
    username = db.Column(db.String(180), nullable=True)
    secret_encrypted = db.Column(db.Text, nullable=True)
    secret = EncryptedSecret('secret_encrypted', legacy_plaintext=True)
    # Nullable FK — a registry can be scoped to one workspace, or global (NULL).
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    last_tested_at = db.Column(db.DateTime, nullable=True)
    last_test_ok = db.Column(db.Boolean, nullable=True)
    last_test_error = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def login_host(self):
        """The host to pass to ``docker login`` (blank ``registry_url`` => Docker Hub)."""
        return (self.registry_url or '').strip() or self.DOCKERHUB_HOST

    def login_username(self):
        """The username for ``docker login``. ECR uses the fixed ``AWS`` user; any
        other registry uses the stored username (``None`` if unset)."""
        if self.username:
            return self.username
        if self.provider == 'ecr':
            return 'AWS'
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'provider': self.provider,
            'registry_url': self.registry_url,
            'login_host': self.login_host(),
            'username': self.username,
            # Never serialize the secret — expose only whether one is stored.
            'has_secret': bool(self.secret_encrypted),
            'workspace_id': self.workspace_id,
            'created_by': self.created_by,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'last_tested_at': self.last_tested_at.isoformat() if self.last_tested_at else None,
            'last_test_ok': self.last_test_ok,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<ContainerRegistry {self.name} ({self.provider})>'
