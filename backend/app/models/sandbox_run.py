from datetime import datetime

from app import db


class SandboxRun(db.Model):
    """One Test Sandbox execution: a set of distro containers running the
    installer / script test suites, driven from the Test Sandbox UI.

    ``results`` is a JSON object keyed by distro id:
    ``{"ubuntu22": {"status": "passed|failed|running|queued|skipped",
                     "detail": "...", "duration_s": 12.3}, ...}``
    Per-distro full logs live on disk under
    ``instance/sandbox-runs/<id>/<distro>.log`` (see test_sandbox_service).
    """
    __tablename__ = 'sandbox_runs'

    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(16), nullable=False, default='quick')  # quick | full
    distros = db.Column(db.JSON)  # list of distro keys requested
    # running | done | error | cancelled
    status = db.Column(db.String(16), nullable=False, default='running', index=True)
    results = db.Column(db.JSON)
    error = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    finished_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'mode': self.mode,
            'distros': self.distros or [],
            'status': self.status,
            'results': self.results or {},
            'error': self.error,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }
