"""Modules API — toggle heavy core verticals (Email, WordPress) on/off.

Read is available to any authenticated user (the frontend needs it to hide nav
and guard routes); flipping a toggle is admin-only.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services import module_service
from app.services.audit_service import AuditService
from app.models.audit_log import AuditLog
from app.middleware.rbac import get_current_user

modules_bp = Blueprint('modules', __name__)


@modules_bp.route('', methods=['GET'])
@modules_bp.route('/', methods=['GET'])
@jwt_required()
def list_modules():
    return jsonify({'modules': module_service.list_modules()})


@modules_bp.route('/<name>', methods=['PUT'])
@jwt_required()
def set_module(name):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    if name not in module_service.MODULES:
        return jsonify({'error': f'Unknown module: {name}'}), 404

    data = request.get_json() or {}
    if 'enabled' not in data:
        return jsonify({'error': 'enabled (boolean) required'}), 400

    enabled = module_service.set_module_enabled(name, bool(data['enabled']), user_id=user.id)
    AuditService.log(
        action=AuditLog.ACTION_RESOURCE_ENABLE if enabled else AuditLog.ACTION_RESOURCE_DISABLE,
        user_id=user.id,
        target_type='module',
        target_id=None,
        details={'module': name, 'enabled': enabled},
    )
    return jsonify({'name': name, 'enabled': enabled})
