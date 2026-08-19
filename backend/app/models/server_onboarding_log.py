"""Append-only progress log for the server onboarding state machine.

Each row records one transition or step outcome (started / succeeded / failed)
so the wizard UI can show a live, ordered timeline of how a server moved through
``pending -> validating -> installing_prerequisites -> installing_docker ->
pairing_agent -> ready`` (or where it stopped at ``failed``).

The owning ``Server`` carries the *current* state (``onboarding_state``); this
table is the history behind it.
"""
import json
from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class ServerOnboardingLog(JsonColumnMixin, db.Model):
    __tablename__ = 'server_onboarding_logs'

    STATUS_STARTED = 'started'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # No hard FK so onboarding history survives if a server row is recreated
    # during re-pairing; matches the loose-ownership style used elsewhere.
    server_id = db.Column(db.String(36), nullable=False, index=True)

    state = db.Column(db.String(40), nullable=False)        # which lifecycle step
    status = db.Column(db.String(20), nullable=False)       # started | succeeded | failed
    message = db.Column(db.Text, nullable=True)
    detail_json = db.Column(db.Text, nullable=True)         # JSON blob of structured detail

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def get_detail(self):
        return self._json_read('detail_json')

    def set_detail(self, detail):
        self.detail_json = json.dumps(detail or {})

    def to_dict(self):
        return {
            'id': self.id,
            'server_id': self.server_id,
            'state': self.state,
            'status': self.status,
            'message': self.message,
            'detail': self.get_detail(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<ServerOnboardingLog {self.server_id} {self.state}/{self.status}>'
