"""REST API for the ServerKit Queue Bus."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.queue_bus.service import QueueBusService, QueueBusError
from app.error_reporting import unexpected_response
from app.middleware.rbac import get_current_user

queue_bus_bp = Blueprint('queue_bus', __name__)


def _is_admin(user):
    return user is not None and getattr(user, 'role', None) == 'admin'


def _ensure_group_mutable(group_slug):
    """Reject HTTP mutations against system-owned queue groups.

    System groups (jobs, notifications, webhook deliveries, ...) are managed by
    the panel itself and are read-only over the REST API. Internal producers and
    consumers call ``QueueBusService`` directly and are unaffected by this guard.
    """
    group = QueueBusService.get_group(group_slug)
    if group and group.get('owner_type') == 'system':
        raise QueueBusError('System queue groups are read-only', 403)


def _ensure_group_accessible(group_slug):
    """Reject message reads/acks against queue groups the caller doesn't own.

    System-owned groups (jobs, notifications, webhook deliveries, ...) carry
    internal payloads and are admin-only over the REST API — otherwise any user
    could pop messages (visibility timeout) and stall internal processing, or
    read/ack/kill them. User-owned groups are limited to the owning user (and
    admins). Internal producers and consumers call ``QueueBusService`` directly
    and are unaffected by this guard.
    """
    group = QueueBusService.get_group(group_slug)
    if not group:
        return  # missing group — the service call below raises the 404
    user = get_current_user()
    if _is_admin(user):
        return
    if (group.get('owner_type') == 'user' and user is not None
            and group.get('owner_id') == str(user.id)):
        return
    raise QueueBusError('Access denied', 403)


def _handle_error(e):
    """Map a caught exception to a response.

    A QueueBusError is an expected, caller-actionable failure and keeps its own
    message and status. Anything else is a crash: report it so it reaches
    /monitoring/errors, and answer the standard body instead of handing the
    caller str(e).
    """
    if isinstance(e, QueueBusError):
        return jsonify({'error': e.message}), e.status_code
    return unexpected_response(e)


# ----------------------------------------------------------------------
# Groups
# ----------------------------------------------------------------------

@queue_bus_bp.route('/groups', methods=['GET'])
@jwt_required()
def list_groups():
    try:
        owner_type = request.args.get('owner_type')
        owner_id = request.args.get('owner_id')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        groups = QueueBusService.list_groups(
            owner_type=owner_type,
            owner_id=owner_id,
            limit=limit,
            offset=offset,
        )
        return jsonify({'groups': groups}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups', methods=['POST'])
@jwt_required()
def create_group():
    try:
        data = request.get_json() or {}
        slug = data.get('slug')
        name = data.get('name')
        description = data.get('description')
        owner_type = data.get('owner_type', 'user')
        owner_id = data.get('owner_id')
        config = data.get('config')

        if not slug and not name:
            return jsonify({'error': 'name or slug is required'}), 400

        user = get_current_user()
        if not _is_admin(user):
            # Non-admins create under their own user ownership.
            owner_type = 'user'
            owner_id = str(user.id) if user else None

        group = QueueBusService.create_group(
            slug=slug,
            name=name,
            description=description,
            owner_type=owner_type,
            owner_id=owner_id,
            config=config,
        )
        return jsonify({'group': group}), 201
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>', methods=['GET'])
@jwt_required()
def get_group(group_slug):
    try:
        group = QueueBusService.get_group(group_slug)
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        return jsonify({'group': group}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>', methods=['PATCH'])
@jwt_required()
def update_group(group_slug):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        data = request.get_json() or {}
        group = QueueBusService.update_group(
            slug=group_slug,
            name=data.get('name'),
            description=data.get('description'),
            config=data.get('config'),
        )
        return jsonify({'group': group}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>', methods=['DELETE'])
@jwt_required()
def delete_group(group_slug):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        result = QueueBusService.delete_group(group_slug)
        return jsonify(result), 200
    except Exception as e:
        return _handle_error(e)


# ----------------------------------------------------------------------
# Queues
# ----------------------------------------------------------------------

@queue_bus_bp.route('/groups/<group_slug>/queues', methods=['GET'])
@jwt_required()
def list_queues(group_slug):
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        queues = QueueBusService.list_queues(group_slug, limit=limit, offset=offset)
        return jsonify({'queues': queues}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues', methods=['POST'])
@jwt_required()
def create_queue(group_slug):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        data = request.get_json() or {}
        slug = data.get('slug')
        name = data.get('name')
        description = data.get('description')
        config = data.get('config')

        if not slug and not name:
            return jsonify({'error': 'name or slug is required'}), 400

        queue = QueueBusService.create_queue(
            group_slug=group_slug,
            slug=slug,
            name=name,
            description=description,
            config=config,
        )
        return jsonify({'queue': queue}), 201
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>', methods=['GET'])
@jwt_required()
def get_queue(group_slug, queue_slug):
    try:
        queue = QueueBusService.get_queue(group_slug, queue_slug)
        if not queue:
            return jsonify({'error': 'Queue not found'}), 404
        return jsonify({'queue': queue}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>', methods=['PATCH'])
@jwt_required()
def update_queue(group_slug, queue_slug):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        data = request.get_json() or {}
        queue = QueueBusService.update_queue(
            group_slug=group_slug,
            slug=queue_slug,
            name=data.get('name'),
            description=data.get('description'),
            config=data.get('config'),
        )
        return jsonify({'queue': queue}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>', methods=['DELETE'])
@jwt_required()
def delete_queue(group_slug, queue_slug):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        result = QueueBusService.delete_queue(group_slug, queue_slug)
        return jsonify(result), 200
    except Exception as e:
        return _handle_error(e)


# ----------------------------------------------------------------------
# Messages
# ----------------------------------------------------------------------

@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages', methods=['GET'])
@jwt_required()
def list_messages(group_slug, queue_slug):
    try:
        _ensure_group_accessible(group_slug)
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        messages = QueueBusService.list_messages(
            group_slug=group_slug,
            queue_slug=queue_slug,
            status=status,
            limit=limit,
            offset=offset,
        )
        return jsonify({'messages': messages}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages', methods=['POST'])
@jwt_required()
def send_message(group_slug, queue_slug):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        data = request.get_json() or {}
        payload = data.get('payload')
        priority = data.get('priority', 0)
        delay_ms = data.get('delay_ms', 0)
        max_attempts = data.get('max_attempts')

        if payload is None:
            return jsonify({'error': 'payload is required'}), 400

        message = QueueBusService.send(
            group_slug=group_slug,
            queue_slug=queue_slug,
            payload=payload,
            priority=priority,
            delay_ms=delay_ms,
            max_attempts=max_attempts,
        )
        return jsonify({'message': message}), 201
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages/receive', methods=['POST'])
@jwt_required()
def receive_messages(group_slug, queue_slug):
    try:
        _ensure_group_accessible(group_slug)
        data = request.get_json() or {}
        visibility_timeout_ms = data.get('visibility_timeout_ms', 30000)
        max_messages = data.get('max_messages', 1)

        messages = QueueBusService.receive(
            group_slug=group_slug,
            queue_slug=queue_slug,
            visibility_timeout_ms=visibility_timeout_ms,
            max_messages=max_messages,
        )
        return jsonify({'messages': messages}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages/<message_id>', methods=['GET'])
@jwt_required()
def get_message(group_slug, queue_slug, message_id):
    try:
        _ensure_group_accessible(group_slug)
        message = QueueBusService.get_message(group_slug, queue_slug, message_id)
        if not message:
            return jsonify({'error': 'Message not found'}), 404
        return jsonify({'message': message}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages/<message_id>/complete', methods=['POST'])
@jwt_required()
def complete_message(group_slug, queue_slug, message_id):
    try:
        _ensure_group_accessible(group_slug)
        message = QueueBusService.complete(group_slug, queue_slug, message_id)
        return jsonify({'message': message}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages/<message_id>/fail', methods=['POST'])
@jwt_required()
def fail_message(group_slug, queue_slug, message_id):
    try:
        _ensure_group_accessible(group_slug)
        data = request.get_json() or {}
        message = QueueBusService.fail(
            group_slug=group_slug,
            queue_slug=queue_slug,
            message_id=message_id,
            error_message=data.get('error_message'),
            requeue=data.get('requeue', False),
        )
        return jsonify({'message': message}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages/<message_id>/requeue', methods=['POST'])
@jwt_required()
def requeue_message(group_slug, queue_slug, message_id):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        message = QueueBusService.requeue(group_slug, queue_slug, message_id)
        return jsonify({'message': message}), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/messages/<message_id>', methods=['DELETE'])
@jwt_required()
def delete_message(group_slug, queue_slug, message_id):
    try:
        _ensure_group_mutable(group_slug)
        _ensure_group_accessible(group_slug)
        result = QueueBusService.delete_message(group_slug, queue_slug, message_id)
        return jsonify(result), 200
    except Exception as e:
        return _handle_error(e)


# ----------------------------------------------------------------------
# Shorthand routes
# ----------------------------------------------------------------------

@queue_bus_bp.route('/<group_slug>/<queue_slug>/messages', methods=['POST'])
@jwt_required()
def send_message_shorthand(group_slug, queue_slug):
    return send_message(group_slug, queue_slug)


@queue_bus_bp.route('/<group_slug>/<queue_slug>/messages/receive', methods=['POST'])
@jwt_required()
def receive_messages_shorthand(group_slug, queue_slug):
    return receive_messages(group_slug, queue_slug)


# ----------------------------------------------------------------------
# Stats
# ----------------------------------------------------------------------

@queue_bus_bp.route('/stats', methods=['GET'])
@jwt_required()
def global_stats():
    try:
        stats = QueueBusService.get_stats()
        return jsonify(stats), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/stats', methods=['GET'])
@jwt_required()
def group_stats(group_slug):
    try:
        stats = QueueBusService.get_stats(group_slug=group_slug)
        return jsonify(stats), 200
    except Exception as e:
        return _handle_error(e)


@queue_bus_bp.route('/groups/<group_slug>/queues/<queue_slug>/stats', methods=['GET'])
@jwt_required()
def queue_stats(group_slug, queue_slug):
    try:
        stats = QueueBusService.get_stats(group_slug=group_slug, queue_slug=queue_slug)
        return jsonify(stats), 200
    except Exception as e:
        return _handle_error(e)
