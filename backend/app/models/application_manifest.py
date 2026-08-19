"""Persisted declarative manifest for a project.

One row per project (the manifest maps to a Project). Import stores the raw
text + normalized JSON + hash + source so nothing detected is discarded and
later pushes can re-read it. History lives in the existing DeploymentSnapshot
mechanism, not a second table.
"""

import json
from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin
from app.models.json_column_mixin import JsonColumnMixin


# status values
STATUS_PENDING = 'pending'   # a changed manifest awaiting an explicit apply
STATUS_APPLIED = 'applied'   # live state matches the declared spec
STATUS_DRIFTED = 'drifted'   # live state diverged from the manifest
STATUS_ERROR = 'error'       # last apply / parse failed


class ApplicationManifest(TimestampMixin, JsonColumnMixin, db.Model):
    __tablename__ = 'application_manifests'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)

    raw_text = db.Column(db.Text, nullable=True)          # the manifest file as committed
    normalized_json = db.Column(db.Text, nullable=True)   # ManifestSpecService.normalize() output
    manifest_hash = db.Column(db.String(64), nullable=True, index=True)

    # provenance
    source_repo = db.Column(db.String(500), nullable=True)
    source_ref = db.Column(db.String(200), nullable=True)
    source_commit = db.Column(db.String(64), nullable=True)
    source_path = db.Column(db.String(255), nullable=True, default='serverkit.yaml')

    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    last_error = db.Column(db.Text, nullable=True)
    applied_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('project_id', name='uq_application_manifest_project'),
    )

    def get_normalized(self):
        return self._json_read('normalized_json', None)

    def set_normalized(self, value):
        self.normalized_json = json.dumps(value) if value is not None else None

    def to_dict(self, include_raw=False):
        data = {
            'id': self.id,
            'project_id': self.project_id,
            'manifest_hash': self.manifest_hash,
            'status': self.status,
            'last_error': self.last_error,
            'source': {
                'repo': self.source_repo,
                'ref': self.source_ref,
                'commit': self.source_commit,
                'path': self.source_path,
            },
            'normalized': self.get_normalized(),
            'applied_at': self.applied_at.isoformat() if self.applied_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_raw:
            data['raw_text'] = self.raw_text
        return data

    def __repr__(self):
        return f'<ApplicationManifest project={self.project_id} status={self.status}>'
