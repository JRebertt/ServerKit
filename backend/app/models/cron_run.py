"""Cron run records — the trust layer for scheduled tasks.

One row per execution of a panel cron job whose "Track runs" toggle is on. The
``serverkit-cron-run`` shim wraps the command, captures start/end/exit-code and a
tail of the combined output, and posts it to ``POST /cron/runs/ingest``. Jobs
created outside the panel (or with tracking off) never produce rows.
"""
from datetime import datetime

from app import db
from app.models.mixins import SerializableMixin

OUTPUT_TAIL_LIMIT = 8 * 1024  # 8 KB cap on stored output tail

STATUS_RUNNING = 'running'
STATUS_SUCCESS = 'success'
STATUS_FAILURE = 'failure'


class CronRun(SerializableMixin, db.Model):
    __tablename__ = 'cron_runs'

    id = db.Column(db.Integer, primary_key=True)
    # The panel job id (metadata key), not a DB FK — cron metadata lives in a
    # JSON store, so this is a loose reference.
    job_id = db.Column(db.String(64), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    exit_code = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(16), nullable=False, default=STATUS_RUNNING)
    output_tail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return max(0.0, (self.finished_at - self.started_at).total_seconds())
        return None

    def serialize_extra(self):
        return {'duration_seconds': self.duration_seconds}
