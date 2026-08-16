"""Centralized error log endpoints: admin browsing + frontend client ingestion."""
import time
from collections import defaultdict, deque

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request

from app.middleware.rbac import admin_required
from app.services import error_log_service

error_logs_bp = Blueprint('error_logs', __name__)

# Simple in-memory rate limit for the client ingestion endpoint:
# max CLIENT_RATE_LIMIT requests per CLIENT_RATE_WINDOW seconds per client IP.
CLIENT_RATE_LIMIT = 10
CLIENT_RATE_WINDOW = 60
_client_hits = defaultdict(deque)


def _client_rate_limited(ip):
    now = time.time()
    hits = _client_hits[ip]
    while hits and now - hits[0] > CLIENT_RATE_WINDOW:
        hits.popleft()
    if len(hits) >= CLIENT_RATE_LIMIT:
        return True
    hits.append(now)
    return False


def _optional_str(data, key, max_len):
    """Validate an optional string field; raises ValueError(key) when invalid."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_len:
        raise ValueError(key)
    return value


@error_logs_bp.route('', methods=['GET'])
@jwt_required()
@admin_required
def list_error_logs():
    """List error log entries with optional filters."""
    resolved_arg = request.args.get('resolved')
    resolved = None
    if resolved_arg is not None:
        resolved = resolved_arg.lower() in ('1', 'true', 'yes')
    per_page = min(request.args.get('per_page', 25, type=int), 100)
    result = error_log_service.list_errors(
        source=request.args.get('source'),
        resolved=resolved,
        search=request.args.get('search'),
        page=request.args.get('page', 1, type=int),
        per_page=per_page,
    )
    return jsonify(result), 200


@error_logs_bp.route('/stats', methods=['GET'])
@jwt_required()
@admin_required
def error_log_stats():
    """Totals for the admin overview."""
    return jsonify(error_log_service.get_stats()), 200


@error_logs_bp.route('/<int:error_id>', methods=['GET'])
@jwt_required()
@admin_required
def get_error_log(error_id):
    """Get a single error log entry."""
    entry = error_log_service.get_error(error_id)
    if not entry:
        return jsonify({'error': 'Error log not found'}), 404
    return jsonify(entry.to_dict()), 200


@error_logs_bp.route('/<int:error_id>/resolve', methods=['POST'])
@jwt_required()
@admin_required
def resolve_error_log(error_id):
    """Set the resolved flag: body {"resolved": true|false}."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('resolved'), bool):
        return jsonify({'error': 'resolved (boolean) is required'}), 400
    entry = error_log_service.set_resolved(error_id, data['resolved'])
    if not entry:
        return jsonify({'error': 'Error log not found'}), 404
    return jsonify(entry.to_dict()), 200


@error_logs_bp.route('/<int:error_id>', methods=['DELETE'])
@jwt_required()
@admin_required
def delete_error_log(error_id):
    """Delete an error log entry."""
    if not error_log_service.delete_error(error_id):
        return jsonify({'error': 'Error log not found'}), 404
    return jsonify({'success': True}), 200


@error_logs_bp.route('/client', methods=['POST'])
def client_error_log():
    """Frontend error ingestion. Auth optional: a valid JWT attaches user_id."""
    ip = request.remote_addr or 'unknown'
    if _client_rate_limited(ip):
        return jsonify({'error': 'Rate limit exceeded'}), 429

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON body is required'}), 400

    message = data.get('message')
    if not isinstance(message, str) or not message.strip():
        return jsonify({'error': 'message is required'}), 400
    if len(message) > error_log_service.MAX_MESSAGE_LEN:
        return jsonify({'error': 'message is too long'}), 400

    try:
        exception_type = _optional_str(data, 'exception_type', 200)
        tb = _optional_str(data, 'traceback', error_log_service.MAX_TRACEBACK_LEN)
        endpoint = _optional_str(data, 'endpoint', 255)
        level = _optional_str(data, 'level', 20)
    except ValueError as exc:
        return jsonify({'error': f'invalid field: {exc}'}), 400

    context = data.get('context')
    if context is not None and not isinstance(context, dict):
        return jsonify({'error': 'invalid field: context'}), 400

    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
    except Exception:  # noqa: BLE001 - anonymous client reports are allowed
        user_id = None

    entry, deduplicated = error_log_service.record_error(
        source='frontend',
        message=message,
        exception_type=exception_type,
        traceback=tb,
        endpoint=endpoint,
        user_id=user_id,
        context=context,
        level=level or 'error',
    )
    if entry is None:
        return jsonify({'error': 'Failed to record error'}), 500
    return jsonify({'id': entry.id, 'deduplicated': deduplicated}), 201
