"""
Database snapshot & sync-job models.

These are generic database point-in-time snapshot and environment-sync
records. They physically lived in ``wordpress_site.py`` historically; they were
relocated here (plan 52 Phase 1) so the WordPress model file no longer owns
generic machinery. The tables (``database_snapshots``, ``sync_jobs``) are
unchanged — this was a pure module move. Their foreign keys still reference
``wordpress_sites`` (the only environment kind that uses them today); that is a
stable core-managed schema seam, not a reason to keep them in the WP file.

``wordpress_site`` re-exports both names for import compatibility, so existing
``from app.models.wordpress_site import DatabaseSnapshot`` callers keep working.
"""

from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin
import json


class DatabaseSnapshot(db.Model):
    """Point-in-time database snapshots for WordPress sites."""

    __tablename__ = 'database_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=False)

    # Snapshot info
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    tag = db.Column(db.String(100))  # e.g., 'pre-deploy', 'v1.2.0', 'auto-nightly'

    # File info
    file_path = db.Column(db.String(500), nullable=False)
    size_bytes = db.Column(db.BigInteger, default=0)
    compressed = db.Column(db.Boolean, default=True)

    # Git context (optional)
    commit_sha = db.Column(db.String(40))  # Git commit at snapshot time
    commit_message = db.Column(db.Text)

    # Metadata
    tables_included = db.Column(db.Text)  # JSON list of tables
    row_count = db.Column(db.Integer)

    # Status
    status = db.Column(db.String(20), default='completed')  # creating, completed, failed, deleted
    error_message = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)  # Auto-cleanup date

    def to_dict(self):
        return {
            'id': self.id,
            'site_id': self.site_id,
            'name': self.name,
            'description': self.description,
            'tag': self.tag,
            'file_path': self.file_path,
            'size_bytes': self.size_bytes,
            'size_human': self._format_size(self.size_bytes),
            'compressed': self.compressed,
            'commit_sha': self.commit_sha,
            'commit_message': self.commit_message,
            'tables_included': json.loads(self.tables_included) if self.tables_included else None,
            'row_count': self.row_count,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }

    @staticmethod
    def _format_size(size_bytes):
        if not size_bytes:
            return '0 B'
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f'{size_bytes:.1f} {unit}'
            size_bytes /= 1024
        return f'{size_bytes:.1f} TB'

    def __repr__(self):
        return f'<DatabaseSnapshot {self.id} "{self.name}">'


class SyncJob(TimestampMixin, db.Model):
    """Scheduled database synchronization jobs between WordPress environments."""

    __tablename__ = 'sync_jobs'

    id = db.Column(db.Integer, primary_key=True)

    # Source and target sites
    source_site_id = db.Column(db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=False)
    target_site_id = db.Column(db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=False)

    # Job name
    name = db.Column(db.String(200))

    # Schedule (cron expression)
    schedule = db.Column(db.String(100))  # e.g., "0 3 * * 0" = Sunday 3 AM
    enabled = db.Column(db.Boolean, default=True)

    # Configuration (JSON)
    config = db.Column(db.Text)  # search_replace, anonymize, exclude_tables, truncate_tables

    # Execution tracking
    last_run = db.Column(db.DateTime)
    last_run_status = db.Column(db.String(20))  # success, failed, running
    last_run_duration = db.Column(db.Integer)  # seconds
    last_run_error = db.Column(db.Text)
    next_run = db.Column(db.DateTime)
    run_count = db.Column(db.Integer, default=0)

    # Timestamps

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'source_site_id': self.source_site_id,
            'target_site_id': self.target_site_id,
            'schedule': self.schedule,
            'enabled': self.enabled,
            'config': json.loads(self.config) if self.config else None,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'last_run_status': self.last_run_status,
            'last_run_duration': self.last_run_duration,
            'last_run_error': self.last_run_error,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'run_count': self.run_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'source_site': self.source_site.to_dict() if self.source_site else None,
            'target_site': self.target_site.to_dict() if self.target_site else None,
        }

    def __repr__(self):
        return f'<SyncJob {self.id} {self.source_site_id}->{self.target_site_id}>'
