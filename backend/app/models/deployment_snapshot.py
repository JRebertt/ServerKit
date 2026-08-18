"""
DeploymentSnapshot Model - Immutable snapshots of an app's resolved config.

Before every deployment we capture a point-in-time, immutable snapshot of the
application's *resolved configuration* — env var keys (with masked values),
domains, image/tag, build method/plan, volumes, and nginx overrides — together
with a SHA-256 hash of the canonical config. This lets us:

- show a deployment timeline with a "config changed" indicator,
- diff two snapshots without ever leaking secret values, and
- restore a previous configuration (env vars + domains) and redeploy.

This is intentionally SEPARATE from ``DeploymentDiff`` (which tracks FILE-level
git diffs). Snapshots are about *configuration*, not source files.
"""

from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class DeploymentSnapshot(JsonColumnMixin, db.Model):
    """An immutable snapshot of an application's resolved configuration."""
    __tablename__ = 'deployment_snapshots'

    id = db.Column(db.Integer, primary_key=True)

    # The app this snapshot belongs to (indexed for "list snapshots for app").
    application_id = db.Column(
        db.Integer, db.ForeignKey('applications.id'), nullable=False, index=True
    )

    # The deployment this snapshot was captured for, if any. Nullable because a
    # snapshot may be captured outside a deploy (e.g. a manual checkpoint) and
    # because a deploy that fails before its Deployment row is created should
    # still be able to record a snapshot.
    deployment_id = db.Column(
        db.Integer, db.ForeignKey('deployments.id'), nullable=True, index=True
    )

    # SHA-256 hex digest of the canonical config JSON. Used for dedupe + a stable
    # "did the config change?" signal.
    snapshot_hash = db.Column(db.String(64), nullable=False)

    # The full resolved config as canonical JSON (sorted keys). Secret *values*
    # are already masked before this is written — the row never stores plaintext
    # secrets.
    config_json = db.Column(db.Text, nullable=False, default='{}')

    # Short human label describing what changed vs the previous snapshot,
    # e.g. "3 env vars changed" or "image updated". Best-effort, may be empty.
    summary = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Use a UNIQUE backref name so we don't have to edit application.py /
    # deployment.py (another agent owns those). The Application gains a
    # ``config_snapshots`` collection; the Deployment gains ``config_snapshots``
    # too via a distinct backref.
    application = db.relationship(
        'Application', backref=db.backref('config_snapshots', lazy='dynamic')
    )
    deployment = db.relationship(
        'Deployment', backref=db.backref('config_snapshots', lazy='dynamic')
    )

    def get_config(self):
        """Return the parsed config dict (empty dict on any parse error)."""
        return self._json_read('config_json')

    def to_dict(self, include_config=True):
        """Convert to dictionary for API responses."""
        result = {
            'id': self.id,
            'application_id': self.application_id,
            'deployment_id': self.deployment_id,
            'snapshot_hash': self.snapshot_hash,
            'summary': self.summary,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_config:
            result['config'] = self.get_config()
        return result

    @classmethod
    def get_latest(cls, application_id):
        """Return the most recent snapshot for an app, or None."""
        return (
            cls.query.filter_by(application_id=application_id)
            .order_by(cls.created_at.desc(), cls.id.desc())
            .first()
        )

    def __repr__(self):
        return (
            f'<DeploymentSnapshot app={self.application_id} '
            f'hash={self.snapshot_hash[:8] if self.snapshot_hash else "?"}>'
        )
