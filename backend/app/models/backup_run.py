from datetime import datetime
from decimal import Decimal

from app import db
from app.models.json_column_mixin import JsonColumnMixin


def _num(value):
    """Serialize a Numeric/Decimal column to a JSON-friendly float (or None)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


class BackupRun(JsonColumnMixin, db.Model):
    """A single backup execution produced by a :class:`BackupPolicy`.

    This is the source of truth for the Protection panel's history view. Each run
    records what was produced (size, paths, cost), whether it was a ``full`` or
    ``incremental`` backup, and links back to the unified job (``job_id``) that
    ran it so the UI can deep-link into Jobs.
    """

    __tablename__ = 'backup_runs'

    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey('backup_policies.id'), nullable=False, index=True)
    job_id = db.Column(db.String(36), nullable=True, index=True)

    kind = db.Column(db.String(20), nullable=False)  # 'full' | 'incremental'
    status = db.Column(db.String(20), nullable=False)  # 'running' | 'success' | 'failed' | 'verifying'
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)

    size_local = db.Column(db.BigInteger, default=0)
    size_remote = db.Column(db.BigInteger, default=0)
    cost_local = db.Column(db.Numeric(10, 4), default=0)
    cost_remote = db.Column(db.Numeric(10, 4), default=0)

    storage_path = db.Column(db.Text, nullable=True)  # local archive directory/path
    remote_key = db.Column(db.Text, nullable=True)
    verified = db.Column(db.Boolean, default=False)  # remote-side evidence (legacy S3 HEAD)

    # Verification ladder (plan 23). 'none' → 'listed' (tar -t readable) → 'hashed'
    # (manifest sha256 spot-check passed) → 'drilled' (a real restore drill of a
    # chain ending at this run succeeded). Only a drill ever sets 'drilled'.
    verify_level = db.Column(db.String(12), nullable=False, default='none')
    verified_at = db.Column(db.DateTime, nullable=True)
    verify_error = db.Column(db.Text, nullable=True)
    # sha256 of the primary archive, computed at build time (Decision 3).
    checksum_sha256 = db.Column(db.String(64), nullable=True)

    error_message = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, default='{}')  # tables, files, compression, etc.

    # Ordered verification levels, weakest → strongest.
    VERIFY_LEVELS = ('none', 'listed', 'hashed', 'drilled')

    @classmethod
    def _verify_rank(cls, level):
        try:
            return cls.VERIFY_LEVELS.index(level or 'none')
        except ValueError:
            return 0

    def effective_verify_level(self):
        """Verify level mapping the legacy ``verified`` boolean forward: a run
        with no explicit level but a remote-verified copy reads as 'listed' (the
        remote HEAD proves it exists + size-matches) so old rows aren't 'none'."""
        level = self.verify_level or 'none'
        if level == 'none' and self.verified:
            return 'listed'
        return level

    def get_metadata(self):
        return self._json_read('metadata_json')

    def set_metadata(self, value):
        self._json_write('metadata_json', value, falsy='{}')

    def to_dict(self):
        meta = self.get_metadata()
        cost_local = _num(self.cost_local) or 0
        cost_remote = _num(self.cost_remote) or 0
        return {
            'id': self.id,
            'policy_id': self.policy_id,
            'job_id': self.job_id,
            'kind': self.kind,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'duration_seconds': self.duration_seconds,
            'size_local': self.size_local or 0,
            'size_remote': self.size_remote or 0,
            'size_total': (self.size_local or 0) + (self.size_remote or 0),
            'cost_local': cost_local,
            'cost_remote': cost_remote,
            'cost_total': round(cost_local + cost_remote, 4),
            'storage_path': self.storage_path,
            'remote_key': self.remote_key,
            'verified': self.verified,
            'verify_level': self.effective_verify_level(),
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'verify_error': self.verify_error,
            'checksum_sha256': self.checksum_sha256,
            'error_message': self.error_message,
            'compression': meta.get('compression'),
            'tables': meta.get('tables'),
            'metadata': meta,
        }

    def __repr__(self):
        return f'<BackupRun {self.id} policy={self.policy_id} {self.kind}/{self.status}>'
