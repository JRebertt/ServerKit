"""Deployment job models.

Tracks cross-server deployment work independently from versioned app deploys.
"""

from datetime import datetime
import json

from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import RunLifecycleMixin


class DeploymentJob(RunLifecycleMixin, JsonColumnMixin, db.Model):
    """A runnable deployment job with status, target, plan, and result."""

    __tablename__ = 'deployment_jobs'

    # Run envelope kind (plan 77 E1): rooms/events key on (run_kind, id).
    __run_kind__ = 'deploy'

    # Stored spelling predates the canonical vocabulary (plan 77 D1);
    # override until this domain's data migration rewrites 'succeeded'.
    __status_success__ = 'succeeded'
    __error_attr__ = 'error_message'

    id = db.Column(db.String(36), primary_key=True)
    kind = db.Column(db.String(50), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)

    # Target
    target_server_id = db.Column(db.String(36), db.ForeignKey('servers.id'), nullable=True, index=True)
    app_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=True, index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    trigger = db.Column(db.String(30), default='manual')

    # Links to the release ledgers (§3 unification): the DeploymentJob is the
    # canonical execution record; Deployment / GitDeployment remain the
    # version/release ledgers it produces. All nullable — a template-install job
    # has none of these set.
    deployment_id = db.Column(db.Integer, db.ForeignKey('deployments.id'), nullable=True, index=True)
    git_deployment_id = db.Column(db.Integer, db.ForeignKey('git_deployments.id'), nullable=True, index=True)
    webhook_id = db.Column(db.Integer, db.ForeignKey('git_webhooks.id'), nullable=True, index=True)
    commit_hash = db.Column(db.String(40), nullable=True)
    image_tag = db.Column(db.String(255), nullable=True)
    container_id = db.Column(db.String(100), nullable=True)

    # Execution progress
    total_steps = db.Column(db.Integer, default=0)
    current_step = db.Column(db.Integer, default=0)
    current_step_name = db.Column(db.String(200), nullable=True)

    # Serialized plan/result
    plan = db.Column(db.Text, default='{}')
    result = db.Column(db.Text, default='{}')
    error_message = db.Column(db.Text, nullable=True)

    # Correlation ID for grouping this deployment with related telemetry events.
    correlation_id = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    target_server = db.relationship('Server', backref=db.backref('deployment_jobs', lazy='dynamic'))
    app = db.relationship('Application', backref=db.backref('deployment_jobs', lazy='dynamic'))
    requester = db.relationship('User', backref=db.backref('deployment_jobs', lazy='dynamic'))
    logs = db.relationship(
        'DeploymentJobLog',
        back_populates='job',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='DeploymentJobLog.created_at',
    )

    def get_plan(self):
        return self._json_read('plan')

    def set_plan(self, plan):
        self.plan = json.dumps(plan)
        steps = plan.get('steps', []) if isinstance(plan, dict) else []
        self.total_steps = len(steps)

    def get_result(self):
        return self._json_read('result')

    def set_result(self, result):
        self.result = json.dumps(result or {})

    @property
    def duration(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def progress_percent(self):
        if not self.total_steps:
            return 0
        return min(100, int((self.current_step / self.total_steps) * 100))

    @property
    def target_server_name(self):
        return self.target_server.name if self.target_server else 'Local server'

    def to_dict(self, include_plan=False, include_logs=False):
        result = self.get_result()
        plan = self.get_plan() if include_plan or self.kind == 'recipe.run' else None
        recipe = (plan.get('recipe')
                  if self.kind == 'recipe.run' and isinstance(plan, dict)
                  else None)
        handoff = result.get('handoff') if isinstance(result, dict) else None
        data = {
            'id': self.id,
            'kind': self.kind,
            'status': self.status,
            'target_server_id': self.target_server_id,
            'target_server_name': self.target_server_name,
            'app_id': self.app_id,
            'app_name': self.app.name if self.app else None,
            'requested_by': self.requested_by,
            'trigger': self.trigger,
            'deployment_id': self.deployment_id,
            'git_deployment_id': self.git_deployment_id,
            'webhook_id': self.webhook_id,
            'commit_hash': self.commit_hash,
            'image_tag': self.image_tag,
            'container_id': self.container_id,
            'total_steps': self.total_steps,
            'current_step': self.current_step,
            'current_step_name': self.current_step_name,
            'progress_percent': self.progress_percent,
            'result': result,
            'error_message': self.error_message,
            'correlation_id': self.correlation_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'duration': self.duration,
            'requires_action': self.status == 'waiting' and bool(handoff),
            'needs_attention': self.status == 'waiting' or self.status == 'failed',
        }
        if recipe:
            data['title'] = f"Recipe: {recipe.get('title') or recipe.get('slug') or 'Guided outcome'}"
            data['recipe'] = recipe
            data['handoff'] = handoff
        if include_plan:
            data['plan'] = plan
        if include_logs:
            data['logs'] = [log.to_dict() for log in self.logs.all()]
        return data


class DeploymentJobLog(JsonColumnMixin, db.Model):
    """A timestamped deployment job log entry."""

    __tablename__ = 'deployment_job_logs'

    # BigInteger on SQLite is NOT a rowid alias, so it never autoincrements and
    # every insert fails with "NOT NULL constraint failed: deployment_job_logs.id".
    # Use a real Integer PK on SQLite (rowid alias → autoincrement works).
    id = db.Column(
        db.BigInteger().with_variant(db.Integer, 'sqlite'),
        primary_key=True,
        autoincrement=True,
    )
    job_id = db.Column(db.String(36), db.ForeignKey('deployment_jobs.id'), nullable=False, index=True)
    step_index = db.Column(db.Integer, nullable=True)
    level = db.Column(db.String(10), default='info')
    message = db.Column(db.Text, nullable=False)
    data = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    job = db.relationship('DeploymentJob', back_populates='logs')

    def get_data(self):
        return self._json_read('data', None)

    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'step_index': self.step_index,
            'level': self.level,
            'message': self.message,
            'data': self.get_data(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
