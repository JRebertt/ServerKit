"""PR Preview Environments — data model.

When a Git pull request is opened/updated, ServerKit deploys an isolated
preview of that branch to a temporary domain and tears it down when the PR
closes. Preview config lives here (its own tables) rather than on Application
so the application schema stays untouched.

Two tables:
  * ``application_previews``         — one row per live PR preview.
  * ``application_preview_settings`` — per-application opt-in + domain template.
"""
from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin
from app.models.json_column_mixin import JsonColumnMixin


class ApplicationPreview(TimestampMixin, JsonColumnMixin, db.Model):
    """A single PR preview environment for an application."""
    __tablename__ = 'application_previews'

    # Status lifecycle (string column, not an enum, to match the rest of the
    # codebase's loose status columns):
    STATUS_QUEUED = 'queued'
    STATUS_BUILDING = 'building'
    STATUS_RUNNING = 'running'
    STATUS_STOPPED = 'stopped'
    STATUS_FAILED = 'failed'
    STATUS_DESTROYED = 'destroyed'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer, db.ForeignKey('applications.id'), nullable=False, index=True)
    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    application = db.relationship('Application',
                                  backref=db.backref('previews', lazy='dynamic'))

    pr_number = db.Column(db.Integer, nullable=False)
    pr_title = db.Column(db.String(500), nullable=True)
    branch = db.Column(db.String(255), nullable=True)

    status = db.Column(db.String(20), default=STATUS_QUEUED, nullable=False)
    domain = db.Column(db.String(255), nullable=True)

    # JSON-encoded list of provisioned container ids (best-effort; may be empty
    # when Docker isn't available, e.g. dev/test).
    container_ids = db.Column(db.Text, nullable=True)

    commit_sha = db.Column(db.String(64), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    deleted_at = db.Column(db.DateTime, nullable=True)

    def get_container_ids(self):
        """The provisioned container ids as a list (empty when unset/invalid)."""
        return self._json_read('container_ids', [], expect=list)

    def set_container_ids(self, ids):
        self._json_write('container_ids', list(ids or []), falsy='[]')

    def to_dict(self):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'pr_number': self.pr_number,
            'pr_title': self.pr_title,
            'branch': self.branch,
            'status': self.status,
            'domain': self.domain,
            'url': (f'https://{self.domain}' if self.domain else None),
            'container_ids': self.get_container_ids(),
            'commit_sha': self.commit_sha,
            'short_sha': self.commit_sha[:7] if self.commit_sha else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
        }

    def __repr__(self):
        return f'<ApplicationPreview app={self.application_id} PR#{self.pr_number} ({self.status})>'


class ApplicationPreviewSettings(TimestampMixin, db.Model):
    """Per-application PR-preview configuration (opt-in + domain template)."""
    __tablename__ = 'application_preview_settings'

    DEFAULT_DOMAIN_TEMPLATE = 'pr-{pr_number}.{app_domain}'

    application_id = db.Column(
        db.Integer, db.ForeignKey('applications.id'),
        primary_key=True, unique=True, nullable=False)
    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    application = db.relationship('Application',
                                  backref=db.backref('preview_settings', uselist=False))

    enabled = db.Column(db.Boolean, default=False, nullable=False)
    domain_template = db.Column(
        db.String(255), default=DEFAULT_DOMAIN_TEMPLATE, nullable=False)
    # Optional: deploy previews onto a specific server in the fleet.
    target_server_id = db.Column(db.String(36), nullable=True)
    # Optional TTL: previews are auto-destroyed this many days after creation.
    ttl_days = db.Column(db.Integer, nullable=True)


    def to_dict(self):
        return {
            'application_id': self.application_id,
            'enabled': bool(self.enabled),
            'domain_template': self.domain_template or self.DEFAULT_DOMAIN_TEMPLATE,
            'target_server_id': self.target_server_id,
            'ttl_days': self.ttl_days,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<ApplicationPreviewSettings app={self.application_id} enabled={self.enabled}>'
