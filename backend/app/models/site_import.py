"""Site import runs — migrating a site from another control panel.

A ``SiteImport`` row tracks one archive-to-app migration: where the archive
came from, what the analyse step discovered, the step-by-step run log, and
the final result. The heavy lifting happens in
``app.services.site_import_service`` as ``import.analyze`` / ``import.run``
jobs; this row is the durable record the wizard UI polls.
"""
import json
from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin

# Formats the importer registry may grow to support. 'cpanel' ships first;
# the others plug into the same pipeline (see app/services/site_importers/).
VALID_SOURCE_TYPES = ('auto', 'cpanel', 'directadmin', 'hestia', 'ssh',
                      'wordpress_ssh')

VALID_STATUSES = (
    'created', 'uploading', 'analyzing', 'analyzed',
    'running', 'completed', 'failed',
)


class SiteImport(JsonColumnMixin, db.Model):
    __tablename__ = 'site_imports'

    id = db.Column(db.Integer, primary_key=True)
    source_type = db.Column(db.String(30), nullable=False, default='cpanel')
    status = db.Column(db.String(20), nullable=False, default='created')

    # JSON: {'upload_path': '<relative token>'} or {'url': 'https://...'}
    source = db.Column(db.Text, nullable=True)
    # JSON: caller options (app name override, which steps to skip, ...)
    options = db.Column(db.Text, nullable=True)
    # JSON: the analyse report produced by the format importer.
    analysis = db.Column(db.Text, nullable=True)
    # JSON: run outcome ({'app_id': ..., 'databases': [...], ...})
    result = db.Column(db.Text, nullable=True)

    # Appended, newline-separated human-readable log lines.
    log_text = db.Column(db.Text, nullable=True)
    current_step = db.Column(db.String(60), nullable=True)
    error = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def get_source(self):
        return self._json_read('source', expect=dict)

    def set_source(self, value):
        self.source = json.dumps(value or {})

    def get_options(self):
        return self._json_read('options', expect=dict)

    def set_options(self, value):
        self.options = json.dumps(value or {})

    def get_analysis(self):
        return self._json_read('analysis', expect=dict)

    def set_analysis(self, value):
        self.analysis = json.dumps(value or {})

    def get_result(self):
        return self._json_read('result', expect=dict)

    def set_result(self, value):
        self.result = json.dumps(value or {})

    def append_log(self, line):
        stamp = datetime.utcnow().strftime('%H:%M:%S')
        entry = f'[{stamp}] {line}'
        self.log_text = (self.log_text + '\n' + entry) if self.log_text else entry

    def log_tail(self, max_lines=500):
        if not self.log_text:
            return ''
        lines = self.log_text.splitlines()
        return '\n'.join(lines[-max_lines:])

    def to_dict(self, log_lines=500):
        return {
            'id': self.id,
            'source_type': self.source_type,
            'status': self.status,
            'source': self.get_source(),
            'options': self.get_options(),
            'analysis': self.get_analysis() or None,
            'result': self.get_result() or None,
            'log_text': self.log_tail(log_lines),
            'current_step': self.current_step,
            'error': self.error,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<SiteImport {self.id} {self.source_type} {self.status}>'
