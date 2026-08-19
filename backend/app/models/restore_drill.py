from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class RestoreDrill(JsonColumnMixin, db.Model):
    """A single restore *drill* — a real restore of a policy's latest restorable
    point into a scratch location (temp dir / scratch DB), probe-verified, then
    torn down. Never touches the live target.

    A successful drill is the strongest proof a backup is restorable: it promotes
    the drilled :class:`BackupRun` to ``verify_level='drilled'`` and stamps the
    policy's ``last_drill_*`` cache. Drilling the latest point implicitly proves
    the whole chain (incrementals are useless without their base).

    See docs/plans/23_BACKUP_TRUST_RESTORE_DRILLS_PLAN.md (Decision 4).
    """

    __tablename__ = 'restore_drills'

    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey('backup_policies.id'), nullable=False, index=True)
    # The run whose restore-point (chain endpoint) was drilled.
    run_id = db.Column(db.Integer, db.ForeignKey('backup_runs.id'), nullable=True, index=True)
    job_id = db.Column(db.String(36), nullable=True, index=True)

    # 'running' | 'success' | 'failed' | 'skipped_no_space'
    status = db.Column(db.String(24), nullable=False, default='running')
    trigger = db.Column(db.String(20), nullable=True)  # 'manual' | 'scheduled'

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)

    # Space accounting (operator's own disk — raw bytes, never a fee).
    bytes_required = db.Column(db.BigInteger, nullable=True)   # estimated extracted size
    bytes_free = db.Column(db.BigInteger, nullable=True)       # free space at precheck
    bytes_restored = db.Column(db.BigInteger, nullable=True)   # actually written to scratch

    scratch_ref = db.Column(db.Text, nullable=True)  # scratch dir path / scratch DB name
    probes_json = db.Column(db.Text, default='{}')   # probe results + error tail
    error = db.Column(db.Text, nullable=True)

    def get_probes(self):
        return self._json_read('probes_json')

    def set_probes(self, value):
        self._json_write('probes_json', value, falsy='{}')

    def to_dict(self):
        return {
            'id': self.id,
            'policy_id': self.policy_id,
            'run_id': self.run_id,
            'job_id': self.job_id,
            'status': self.status,
            'trigger': self.trigger,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'duration_seconds': self.duration_seconds,
            'bytes_required': self.bytes_required,
            'bytes_free': self.bytes_free,
            'bytes_restored': self.bytes_restored,
            'scratch_ref': self.scratch_ref,
            'probes': self.get_probes(),
            'error': self.error,
        }

    def __repr__(self):
        return f'<RestoreDrill {self.id} policy={self.policy_id} {self.status}>'
