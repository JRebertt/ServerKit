"""ORM models for the ServerKit Queue Bus."""
import json
import uuid
from datetime import datetime

from app import db


class QueueGroup(db.Model):
    """A namespace for related queues."""

    __tablename__ = 'queue_groups'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = db.Column(db.String(128), nullable=False, unique=True, index=True)
    name = db.Column(db.String(256), nullable=False)
    description = db.Column(db.Text)
    owner_type = db.Column(db.String(32), default='system', nullable=False)
    owner_id = db.Column(db.String(128), nullable=True)
    config_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    queues = db.relationship('Queue', back_populates='group', lazy='dynamic', cascade='all, delete-orphan')

    def get_config(self):
        if self.config_json:
            try:
                return json.loads(self.config_json)
            except (TypeError, json.JSONDecodeError):
                return {}
        return {}

    def set_config(self, value):
        self.config_json = json.dumps(value) if value is not None else None

    def to_dict(self, include_stats=False):
        data = {
            'id': self.id,
            'slug': self.slug,
            'name': self.name,
            'description': self.description,
            'owner_type': self.owner_type,
            'owner_id': self.owner_id,
            'config': self.get_config(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_stats:
            data['stats'] = {
                'queues': self.queues.count(),
            }
        return data


class Queue(db.Model):
    """A named message pipe inside a QueueGroup."""

    __tablename__ = 'queues'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    group_id = db.Column(db.String(36), db.ForeignKey('queue_groups.id'), nullable=False, index=True)
    slug = db.Column(db.String(128), nullable=False, index=True)
    name = db.Column(db.String(256), nullable=False)
    description = db.Column(db.Text)
    config_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    group = db.relationship('QueueGroup', back_populates='queues')
    messages = db.relationship('QueueMessage', back_populates='queue', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('group_id', 'slug', name='uix_queue_group_slug'),
    )

    def get_config(self):
        if self.config_json:
            try:
                return json.loads(self.config_json)
            except (TypeError, json.JSONDecodeError):
                return {}
        return {}

    def set_config(self, value):
        self.config_json = json.dumps(value) if value is not None else None

    def to_dict(self, include_stats=False):
        data = {
            'id': self.id,
            'group_id': self.group_id,
            'group_slug': self.group.slug if self.group else None,
            'slug': self.slug,
            'name': self.name,
            'description': self.description,
            'config': self.get_config(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_stats:
            from sqlalchemy import func
            data['stats'] = {
                'pending': self.messages.filter(QueueMessage.status == QueueMessage.STATUS_PENDING).count(),
                'in_flight': self.messages.filter(QueueMessage.status == QueueMessage.STATUS_IN_FLIGHT).count(),
                'completed': self.messages.filter(QueueMessage.status == QueueMessage.STATUS_COMPLETED).count(),
                'failed': self.messages.filter(QueueMessage.status == QueueMessage.STATUS_FAILED).count(),
                'dead_letter': self.messages.filter(QueueMessage.status == QueueMessage.STATUS_DEAD_LETTER).count(),
                'total': self.messages.count(),
            }
        return data


class QueueMessage(db.Model):
    """A single message in a Queue."""

    __tablename__ = 'queue_messages'

    STATUS_PENDING = 'pending'
    STATUS_IN_FLIGHT = 'in_flight'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_DEAD_LETTER = 'dead_letter'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    queue_id = db.Column(db.String(36), db.ForeignKey('queues.id'), nullable=False, index=True)
    group_id = db.Column(db.String(36), db.ForeignKey('queue_groups.id'), nullable=False, index=True)
    status = db.Column(db.String(32), default=STATUS_PENDING, nullable=False, index=True)
    priority = db.Column(db.Integer, default=0, nullable=False, index=True)
    payload_json = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.Text)
    error_message = db.Column(db.Text)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=3, nullable=False)
    visible_after = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    invisible_until = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    queue = db.relationship('Queue', back_populates='messages')
    # Parent-side backref so the delete-cascade policy covers the NOT NULL
    # group FK directly (the queue chain already cascades, this closes the FK).
    group = db.relationship('QueueGroup',
                            backref=db.backref('messages', lazy='dynamic'))

    def get_payload(self):
        if self.payload_json:
            try:
                return json.loads(self.payload_json)
            except (TypeError, json.JSONDecodeError):
                return {}
        return {}

    def set_payload(self, value):
        self.payload_json = json.dumps(value) if value is not None else '{}'

    def get_result(self):
        if self.result_json:
            try:
                return json.loads(self.result_json)
            except (TypeError, json.JSONDecodeError):
                return {}
        return {}

    def set_result(self, value):
        self.result_json = json.dumps(value) if value is not None else None

    def to_dict(self, include_payload=True):
        data = {
            'id': self.id,
            'queue_id': self.queue_id,
            'group_id': self.group_id,
            'group_slug': self.group.slug if self.group else None,
            'queue_slug': self.queue.slug if self.queue else None,
            'status': self.status,
            'priority': self.priority,
            'attempts': self.attempts,
            'max_attempts': self.max_attempts,
            'error_message': self.error_message,
            'visible_after': self.visible_after.isoformat() if self.visible_after else None,
            'invisible_until': self.invisible_until.isoformat() if self.invisible_until else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_payload:
            data['payload'] = self.get_payload()
            data['result'] = self.get_result()
        return data
