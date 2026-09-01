import json
from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class ServerSurvey(JsonColumnMixin, db.Model):
    """One read-only survey snapshot ("flight") of a paired server (plan 27,
    Decision 3: snapshots, not live state).

    The agent flies the probe catalog and returns a structured Server Map; the
    panel normalizes it and stores it here as a versioned, immutable snapshot.
    Re-flying is manual (or an optional weekly schedule) and appends a new row,
    so any two flights of the same server can be diffed ("what changed since
    last flight").

    ``catalog_version`` records which probe-catalog version produced the map, so
    a diff can flag that the catalog itself changed between two flights.
    ``map_json`` holds the normalized Server Map (services / sites / databases /
    certs / cron / listeners / foreign_panels).
    """

    __tablename__ = 'server_surveys'

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.String(36), db.ForeignKey('servers.id'), nullable=False, index=True)
    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    server = db.relationship('Server',
                             backref=db.backref('surveys', lazy='dynamic'))
    catalog_version = db.Column(db.Integer, nullable=False, default=1)
    taken_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Normalized Server Map, stored as a JSON string for portability across the
    # SQLite/Postgres split (mirrors how other snapshot blobs are persisted).
    map_json = db.Column(db.Text, nullable=True)

    def get_map(self):
        return self._json_read('map_json')

    def set_map(self, value):
        self.map_json = json.dumps(value) if value else None

    def to_dict(self, include_map=True):
        data = {
            'id': self.id,
            'server_id': self.server_id,
            'catalog_version': self.catalog_version,
            'taken_at': self.taken_at.isoformat() + 'Z' if self.taken_at else None,
        }
        if include_map:
            data['map'] = self.get_map()
        return data

    def __repr__(self):
        return f'<ServerSurvey server={self.server_id} v{self.catalog_version} at={self.taken_at}>'
