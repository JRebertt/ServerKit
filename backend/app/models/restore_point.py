"""Immutable checkpoints for panel-managed configuration surfaces."""

from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import SerializableMixin, TimestampMixin, uuid_pk


class RestorePoint(JsonColumnMixin, TimestampMixin, SerializableMixin, db.Model):
    """One point on a scope's linear configuration timeline."""

    __tablename__ = 'restore_points'

    id = uuid_pk()
    server_id = db.Column(
        db.String(36), db.ForeignKey('servers.id'), nullable=True, index=True,
    )
    scope_type = db.Column(db.String(32), nullable=False)
    scope_id = db.Column(db.String(255), nullable=False)
    trigger = db.Column(db.String(32), nullable=False)
    label = db.Column(db.String(255), nullable=True)
    payload_hash = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    coverage_json = db.Column(db.Text, nullable=False, default='[]')
    actor_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True, index=True,
    )
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    keep = db.Column(db.Boolean, nullable=False, default=False)

    server = db.relationship('Server')
    actor = db.relationship('User', foreign_keys=[actor_user_id])

    __table_args__ = (
        db.Index('ix_restore_points_scope', 'scope_type', 'scope_id'),
        db.Index(
            'ix_restore_points_scope_timeline',
            'server_id', 'scope_type', 'scope_id', 'created_at',
        ),
    )

    __serialize_exclude__ = ('payload_json', 'coverage_json')

    def get_payload(self):
        return self._json_read('payload_json', expect=dict)

    def get_coverage(self):
        return self._json_read('coverage_json', default=[], expect=list)

    def serialize_extra(self):
        return {
            'payload': self.get_payload(),
            'coverage': self.get_coverage(),
        }

    @classmethod
    def latest_for_scope(cls, scope_type, scope_id, server_id=None):
        query = cls.query.filter_by(
            scope_type=str(scope_type),
            scope_id=str(scope_id),
            server_id=server_id,
        )
        return query.order_by(cls.created_at.desc(), cls.id.desc()).first()
