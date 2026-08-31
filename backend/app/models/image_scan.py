from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
import json


class ImageVulnerabilityScan(JsonColumnMixin, db.Model):
    """CVE scan result for a Docker image used by an application."""
    __tablename__ = 'image_vulnerability_scans'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False, index=True)
    image_ref = db.Column(db.String(500), nullable=False)
    scanner = db.Column(db.String(50), default='grype')
    scanner_version = db.Column(db.String(50))
    status = db.Column(db.String(20), default='pending')  # pending, running, completed, failed
    severity_counts = db.Column(db.Text)  # JSON: {'critical': 0, 'high': 1, ...}
    findings = db.Column(db.Text)  # JSON list of grype matches
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    # cascade: application_id is NOT NULL — purge must delete, not null out.
    application = db.relationship('Application', backref=db.backref(
        'image_scans', lazy='dynamic', cascade='all, delete-orphan',
        order_by='ImageVulnerabilityScan.started_at.desc()'))

    def set_counts(self, counts):
        self.severity_counts = json.dumps(counts)

    def get_counts(self):
        return self._json_read('severity_counts')

    def set_findings(self, findings):
        self._json_write('findings', findings)

    def get_findings(self):
        return self._json_read('findings', [])

    @property
    def highest_severity(self):
        counts = self.get_counts()
        for sev in ('critical', 'high', 'medium', 'low', 'negligible', 'unknown'):
            if counts.get(sev, 0) > 0:
                return sev
        return 'none'

    def to_dict(self, include_findings=False):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'image_ref': self.image_ref,
            'scanner': self.scanner,
            'scanner_version': self.scanner_version,
            'status': self.status,
            'severity_counts': self.get_counts(),
            'highest_severity': self.highest_severity,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'findings': self.get_findings() if include_findings else None,
        }


class SbomArtifact(JsonColumnMixin, db.Model):
    """Generated SPDX SBOM for a Docker image."""
    __tablename__ = 'sbom_artifacts'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False, index=True)
    image_ref = db.Column(db.String(500), nullable=False)
    generator = db.Column(db.String(50), default='syft')
    generator_version = db.Column(db.String(50))
    format = db.Column(db.String(20), default='spdx-json')
    sbom_json = db.Column(db.Text)  # SPDX 2.3 JSON
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # cascade: application_id is NOT NULL — purge must delete, not null out.
    application = db.relationship('Application', backref=db.backref(
        'sboms', lazy='dynamic', cascade='all, delete-orphan',
        order_by='SbomArtifact.created_at.desc()'))

    def to_dict(self, include_sbom=False):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'image_ref': self.image_ref,
            'generator': self.generator,
            'generator_version': self.generator_version,
            'format': self.format,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'sbom': self._json_read('sbom_json', None) if include_sbom else None,
        }
