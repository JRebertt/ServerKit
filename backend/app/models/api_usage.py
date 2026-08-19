"""API usage tracking models."""
from datetime import datetime
from app import db
from app.models.mixins import SerializableMixin


class ApiUsageLog(SerializableMixin, db.Model):
    """Raw API usage log for every request."""
    __tablename__ = 'api_usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_keys.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    method = db.Column(db.String(10), nullable=False)
    endpoint = db.Column(db.String(500), nullable=False)
    blueprint = db.Column(db.String(100), nullable=True)
    status_code = db.Column(db.Integer, nullable=False)
    response_time_ms = db.Column(db.Float, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    request_size = db.Column(db.Integer, nullable=True)
    response_size = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Serialization comes from SerializableMixin; these columns stay out
    # of API payloads (parity with the deleted hand-written to_dict).
    __serialize_exclude__ = ('request_size', 'response_size', 'user_agent')


class ApiUsageSummary(SerializableMixin, db.Model):
    """Aggregated API usage summary per hour."""
    __tablename__ = 'api_usage_summaries'

    id = db.Column(db.Integer, primary_key=True)
    period_start = db.Column(db.DateTime, nullable=False, index=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_keys.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    endpoint = db.Column(db.String(500), nullable=True)
    total_requests = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    client_error_count = db.Column(db.Integer, default=0)
    server_error_count = db.Column(db.Integer, default=0)
    avg_response_time_ms = db.Column(db.Float, nullable=True)
    max_response_time_ms = db.Column(db.Float, nullable=True)

