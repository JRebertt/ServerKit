"""
WordPress Site Models

Extended models for WordPress-specific functionality including:
- WordPress site metadata
- Database snapshots for point-in-time recovery
- Sync jobs for scheduled database synchronization
"""

from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import TimestampMixin, SerializableMixin

# DatabaseSnapshot + SyncJob were relocated to app/models/db_snapshot.py
# (plan 52 Phase 1 — generic snapshot/sync machinery no longer owned by the WP
# model file). Re-exported here so existing
# `from app.models.wordpress_site import DatabaseSnapshot` (and SyncJob) callers
# keep working, and so WordPressSite.to_dict can reference DatabaseSnapshot.
from app.models.db_snapshot import DatabaseSnapshot, SyncJob  # noqa: F401


class WordPressSite(JsonColumnMixin, TimestampMixin, db.Model):
    """Extended WordPress-specific data linked to Application."""

    __tablename__ = 'wordpress_sites'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), unique=True, nullable=False)

    # WordPress specifics
    wp_version = db.Column(db.String(20))
    multisite = db.Column(db.Boolean, default=False)
    admin_user = db.Column(db.String(100))
    admin_email = db.Column(db.String(200))

    # Database info
    db_name = db.Column(db.String(100))
    db_user = db.Column(db.String(100))
    db_host = db.Column(db.String(200), default='localhost')
    db_prefix = db.Column(db.String(20), default='wp_')

    # Git integration
    git_repo_url = db.Column(db.String(500))
    git_branch = db.Column(db.String(100), default='main')
    git_paths = db.Column(db.Text)  # JSON: paths to sync ['wp-content/themes', 'wp-content/plugins']
    auto_deploy = db.Column(db.Boolean, default=False)
    last_deploy_commit = db.Column(db.String(40))
    last_deploy_at = db.Column(db.DateTime)

    # Environment info
    is_production = db.Column(db.Boolean, default=True)
    production_site_id = db.Column(db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=True)

    # Sync settings (JSON)
    sync_config = db.Column(db.Text)  # schedule, search_replace, anonymize, etc.

    # Environment management
    environment_type = db.Column(db.String(20), default='standalone')  # standalone, production, staging, development, multidev
    multidev_branch = db.Column(db.String(200))
    is_locked = db.Column(db.Boolean, default=False)
    locked_by = db.Column(db.String(100))
    locked_reason = db.Column(db.String(200))
    lock_expires_at = db.Column(db.DateTime)

    # Docker compose tracking
    compose_project_name = db.Column(db.String(100))
    container_prefix = db.Column(db.String(100))

    # Resource limits (stored as JSON for flexibility)
    resource_limits = db.Column(db.Text)  # JSON: {memory, cpus, db_memory, db_cpus}

    # Tags / labels for agency organization (stored as JSON array of strings)
    tags = db.Column(db.Text)  # JSON: ["client-acme", "retainer", "php8"]

    # Basic Auth
    basic_auth_enabled = db.Column(db.Boolean, default=False)
    basic_auth_user = db.Column(db.String(100))
    basic_auth_password_hash = db.Column(db.String(200))

    # Health tracking
    health_status = db.Column(db.String(20), default='unknown')  # healthy, degraded, unhealthy, unknown
    last_health_check = db.Column(db.DateTime)

    # Disk usage tracking
    disk_usage_bytes = db.Column(db.BigInteger, default=0)
    disk_usage_updated_at = db.Column(db.DateTime)

    # Vulnerability scan (#28)
    last_vuln_scan_at = db.Column(db.DateTime)

    # Safe updates (#29)
    auto_update_schedule = db.Column(db.String(100))   # cron expression (null = off)
    auto_update_exclude = db.Column(db.Text)           # JSON list of plugin/theme slugs to skip

    # Auto-sync
    auto_sync_schedule = db.Column(db.String(100))  # cron expression
    auto_sync_enabled = db.Column(db.Boolean, default=False)

    # Timestamps

    # Relationships
    application = db.relationship('Application', backref=db.backref('wp_site', uselist=False))
    environments = db.relationship(
        'WordPressSite',
        backref=db.backref('production_site', remote_side=[id]),
        foreign_keys=[production_site_id]
    )
    snapshots = db.relationship('DatabaseSnapshot', backref='site', lazy='dynamic', cascade='all, delete-orphan')
    vulnerabilities = db.relationship('WordPressVulnerability', backref='site', lazy='dynamic', cascade='all, delete-orphan')
    update_runs = db.relationship('WordPressUpdateRun', backref='site', lazy='dynamic', cascade='all, delete-orphan')
    reports = db.relationship('WordPressReport', backref='site', lazy='dynamic', cascade='all, delete-orphan')
    sync_jobs_as_source = db.relationship(
        'SyncJob',
        foreign_keys='SyncJob.source_site_id',
        backref='source_site',
        lazy='dynamic'
    )
    sync_jobs_as_target = db.relationship(
        'SyncJob',
        foreign_keys='SyncJob.target_site_id',
        backref='target_site',
        lazy='dynamic'
    )

    def to_dict(self, include_environments=False, include_snapshots=False):
        result = {
            'id': self.id,
            'application_id': self.application_id,
            'wp_version': self.wp_version,
            'multisite': self.multisite,
            'admin_user': self.admin_user,
            'admin_email': self.admin_email,
            'db_name': self.db_name,
            'db_user': self.db_user,
            'db_host': self.db_host,
            'db_prefix': self.db_prefix,
            'git_repo_url': self.git_repo_url,
            'git_branch': self.git_branch,
            'git_paths': self._json_read('git_paths', None),
            'auto_deploy': self.auto_deploy,
            'last_deploy_commit': self.last_deploy_commit,
            'last_deploy_at': self.last_deploy_at.isoformat() if self.last_deploy_at else None,
            'is_production': self.is_production,
            'production_site_id': self.production_site_id,
            'sync_config': self._json_read('sync_config', None),
            'environment_type': self.environment_type,
            'multidev_branch': self.multidev_branch,
            'is_locked': self.is_locked,
            'locked_by': self.locked_by,
            'locked_reason': self.locked_reason,
            'lock_expires_at': self.lock_expires_at.isoformat() if self.lock_expires_at else None,
            'compose_project_name': self.compose_project_name,
            'container_prefix': self.container_prefix,
            'resource_limits': self._json_read('resource_limits', None),
            'tags': self._json_read('tags', []),
            'basic_auth_enabled': self.basic_auth_enabled,
            'basic_auth_user': self.basic_auth_user,
            'health_status': self.health_status,
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'disk_usage_bytes': self.disk_usage_bytes,
            'disk_usage_human': DatabaseSnapshot._format_size(self.disk_usage_bytes) if self.disk_usage_bytes else None,
            'disk_usage_updated_at': self.disk_usage_updated_at.isoformat() if self.disk_usage_updated_at else None,
            'last_vuln_scan_at': self.last_vuln_scan_at.isoformat() if self.last_vuln_scan_at else None,
            'auto_update_schedule': self.auto_update_schedule,
            'auto_update_exclude': self._json_read('auto_update_exclude', []),
            'auto_sync_schedule': self.auto_sync_schedule,
            'auto_sync_enabled': self.auto_sync_enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

        # Include application data
        if self.application:
            result['application'] = {
                'id': self.application.id,
                'name': self.application.name,
                'status': self.application.status,
                'root_path': self.application.root_path,
                'port': self.application.port,
                'domains': [d.to_dict() for d in self.application.domains]
            }

        if include_environments and self.is_production:
            result['environments'] = [env.to_dict() for env in self.environments]

        if include_snapshots:
            result['snapshots'] = [snap.to_dict() for snap in self.snapshots.order_by(DatabaseSnapshot.created_at.desc()).limit(10)]

        return result

    def __repr__(self):
        return f'<WordPressSite {self.id} app={self.application_id}>'


class WordPressVulnerability(SerializableMixin, db.Model):
    """A known vulnerability found in a WordPress site's plugin, theme, or core."""

    __tablename__ = 'wordpress_vulnerabilities'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=False, index=True)

    # What is affected
    source = db.Column(db.String(20), nullable=False)   # 'core' | 'plugin' | 'theme'
    slug = db.Column(db.String(200))                    # directory slug ('' for core)
    name = db.Column(db.String(255))                    # display name
    installed_version = db.Column(db.String(50))

    # The advisory
    advisory_id = db.Column(db.String(100))             # CVE id / WPVulnerability uuid
    title = db.Column(db.Text)
    severity = db.Column(db.String(20), default='unknown')  # critical|high|medium|low|unknown
    cvss_score = db.Column(db.String(10))
    fixed_in = db.Column(db.String(50))                 # version the fix landed in (None if unfixed)
    reference_url = db.Column(db.String(500))

    detected_at = db.Column(db.DateTime, default=datetime.utcnow)


    def __repr__(self):
        return f'<WordPressVulnerability {self.id} {self.source}:{self.slug} {self.severity}>'


class WordPressUpdateRun(JsonColumnMixin, db.Model):
    """A record of a safe-update run: snapshot -> update -> health-check -> rollback."""

    __tablename__ = 'wordpress_update_runs'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=False, index=True)

    status = db.Column(db.String(20), default='running')   # running|completed|rolled_back|failed
    trigger = db.Column(db.String(20), default='manual')   # manual|scheduled
    # JSON: {targets, excluded, updated:[{type,slug,from,to}], health_before, health_after, rolled_back}
    details = db.Column(db.Text)
    error = db.Column(db.Text)

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'site_id': self.site_id,
            'status': self.status,
            'trigger': self.trigger,
            'details': self._json_read('details'),
            'error': self.error,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }

    def __repr__(self):
        return f'<WordPressUpdateRun {self.id} site={self.site_id} {self.status}>'


class WordPressReport(JsonColumnMixin, db.Model):
    """A persisted monthly client report for a WordPress site (#33 — agency
    reports slice): a point-in-time snapshot of the site's uptime, incidents,
    update runs, backups, and security posture for one calendar month.

    Why this is persisted rather than computed live on every view: some of the
    underlying sources are point-in-time, not historical. Vulnerability findings
    (#28) are deleted-and-replaced on each scan, and the live health/disk values
    only reflect "now" — so a report regenerated months later would otherwise
    show the wrong month's posture. Generating a report snapshots the computed
    aggregates into `data` here, so the historical record stays truthful. The
    true-historical sources (HealthCheck uptime samples #26, WordPressUpdateRun
    #29, DatabaseSnapshot backups) are re-aggregated from their own tables for
    the month at generation time.
    """

    __tablename__ = 'wordpress_reports'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('wordpress_sites.id'), nullable=False, index=True)

    # Calendar-month window (naive UTC, matching every other timestamp in the app).
    # period_label is "YYYY-MM" and is unique per site (regenerating replaces the row).
    period_label = db.Column(db.String(7), nullable=False)   # e.g. "2026-05"
    period_start = db.Column(db.DateTime, nullable=False)     # first of month, 00:00 UTC
    period_end = db.Column(db.DateTime, nullable=False)       # first of next month (exclusive)

    # The full aggregated payload (JSON). Schema is owned by WpReportsService.
    data = db.Column(db.Text)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'site_id': self.site_id,
            'period_label': self.period_label,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'data': self._json_read('data'),
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
        }

    def __repr__(self):
        return f'<WordPressReport {self.id} site={self.site_id} {self.period_label}>'
