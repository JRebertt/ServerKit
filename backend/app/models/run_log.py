"""Generic run-scoped log rows (plan 77 E1).

``DeploymentJobLog`` predates this table and stays the store for the deploy
kind; every OTHER run kind (unified jobs, sandbox runs, site imports,
backups) persists its stream lines here, keyed by ``(run_kind, run_id)`` —
the same key the ``run_<kind>_<id>`` socket room and the
``GET /api/v1/runs/<kind>/<id>/logs?after_id`` polling twin use, so a client
can always resync after a dropped socket.
"""
from datetime import datetime

from app import db


class RunLogEntry(db.Model):
    __tablename__ = 'run_log_entries'

    id = db.Column(db.Integer, primary_key=True)
    run_kind = db.Column(db.String(40), nullable=False)
    run_id = db.Column(db.String(64), nullable=False)
    step_index = db.Column(db.Integer, nullable=True)
    level = db.Column(db.String(10), default='info', nullable=False)
    message = db.Column(db.Text, nullable=False, default='')
    data = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        # The one access pattern: a run's lines in id order, optionally after a
        # known id (the resync cursor).
        db.Index('ix_run_log_entries_kind_run_id', 'run_kind', 'run_id', 'id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'step_index': self.step_index,
            'level': self.level,
            'message': self.message,
            'data': self.data,
            'ts': self.created_at.isoformat() if self.created_at else None,
        }
