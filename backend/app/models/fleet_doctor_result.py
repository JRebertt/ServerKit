"""Fleet-doctor per-server result model."""
from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class FleetDoctorResult(JsonColumnMixin, db.Model):
    """One row per ``(server_id, check_key)`` recorded by the fleet health sweep
    (Fleet Parity Sweep, plan 26 Phase 2, Decision 3).

    The panel-host doctor keeps its ``doctor_last_report`` settings blob; the
    fleet sweep instead records each remote server's per-check outcome as a ROW
    here so the report API can merge the two and the repair layer can act on an
    individual finding.

    ``status`` is one of ``ok`` / ``warn`` / ``fail`` / ``error``. ``repairable``
    marks findings the allowlisted repair layer can act on; ``repair_ref`` carries
    the JSON descriptor of that repair action.
    """

    __tablename__ = 'fleet_doctor_results'

    STATUS_OK = 'ok'
    STATUS_WARN = 'warn'
    STATUS_FAIL = 'fail'
    STATUS_ERROR = 'error'
    STATUSES = (STATUS_OK, STATUS_WARN, STATUS_FAIL, STATUS_ERROR)

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.String(36), db.ForeignKey('servers.id'),
                          nullable=False, index=True)
    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    server = db.relationship('Server',
                             backref=db.backref('fleet_doctor_results', lazy='dynamic'))
    check_key = db.Column(db.String(160), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, server_default='ok')
    title = db.Column(db.String(200), nullable=True)
    detail = db.Column(db.Text, nullable=True)
    repairable = db.Column(db.Boolean, nullable=False, server_default=db.false())
    repair_ref = db.Column(db.Text, nullable=True)
    ran_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                       index=True)

    __table_args__ = (
        db.UniqueConstraint('server_id', 'check_key',
                            name='uq_fleet_doctor_server_check'),
    )

    def get_repair_ref(self):
        return self._json_read('repair_ref', None)

    def set_repair_ref(self, ref):
        self._json_write('repair_ref', ref)

    def to_dict(self):
        return {
            'id': self.id,
            'server_id': self.server_id,
            'check_key': self.check_key,
            'status': self.status,
            'title': self.title,
            'detail': self.detail,
            'repairable': bool(self.repairable),
            'repair_ref': self.get_repair_ref(),
            'ran_at': self.ran_at.isoformat() + 'Z' if self.ran_at else None,
        }

    def __repr__(self):
        return f'<FleetDoctorResult {self.server_id} {self.check_key} {self.status}>'
