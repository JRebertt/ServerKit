from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import TimestampMixin


class Workflow(JsonColumnMixin, TimestampMixin, db.Model):
    __tablename__ = 'workflows'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # React Flow state stored as JSON strings
    nodes = db.Column(db.Text, nullable=True)  # JSON array of nodes
    edges = db.Column(db.Text, nullable=True)  # JSON array of edges
    viewport = db.Column(db.Text, nullable=True)  # JSON object {x, y, zoom}

    # Automation fields
    is_active = db.Column(db.Boolean, default=False)
    trigger_type = db.Column(db.String(50), default='manual')  # manual, cron, event, webhook
    trigger_config = db.Column(db.Text, nullable=True)  # JSON configuration for the trigger
    last_run_at = db.Column(db.DateTime, nullable=True)
    last_status = db.Column(db.String(20), nullable=True)  # success, failed

    # Metadata

    # Foreign keys
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    user = db.relationship('User', backref=db.backref('workflows', lazy='dynamic'))
    executions = db.relationship('WorkflowExecution', backref='workflow', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'nodes': self._json_read('nodes', []),
            'edges': self._json_read('edges', []),
            'viewport': self._json_read('viewport', None),
            'is_active': self.is_active,
            'trigger_type': self.trigger_type,
            'trigger_config': self._json_read('trigger_config'),
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'last_status': self.last_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'user_id': self.user_id,
            'node_count': len(self._json_read('nodes', [])),
            'edge_count': len(self._json_read('edges', []))
        }

    def __repr__(self):
        return f'<Workflow {self.name}>'


class WorkflowExecution(JsonColumnMixin, db.Model):
    __tablename__ = 'workflow_executions'

    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey('workflows.id'), nullable=False)
    status = db.Column(db.String(20), default='running')  # running, success, failed, cancelled
    trigger_type = db.Column(db.String(50))
    context = db.Column(db.Text, nullable=True)  # JSON data passed between steps
    results = db.Column(db.Text, nullable=True)  # JSON results of each step

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    logs = db.relationship('WorkflowLog', backref='execution', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'workflow_id': self.workflow_id,
            'status': self.status,
            'trigger_type': self.trigger_type,
            'context': self._json_read('context'),
            'results': self._json_read('results'),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration': (self.completed_at - self.started_at).total_seconds() if self.completed_at else None
        }


class WorkflowLog(db.Model):
    __tablename__ = 'workflow_logs'

    id = db.Column(db.Integer, primary_key=True)
    execution_id = db.Column(db.Integer, db.ForeignKey('workflow_executions.id'), nullable=False)
    level = db.Column(db.String(10), default='INFO')  # INFO, WARNING, ERROR, DEBUG
    message = db.Column(db.Text, nullable=False)
    node_id = db.Column(db.String(100), nullable=True)  # ID of the node that generated the log
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'execution_id': self.execution_id,
            'level': self.level,
            'message': self.message,
            'node_id': self.node_id,
            'timestamp': self.timestamp.isoformat()
        }
