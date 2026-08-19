from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.workspace_service import WorkspaceService
from app.services.audit_service import AuditService
from app.models.audit_log import AuditLog
# The workspace guards now live in middleware/rbac.py so any resource blueprint
# can reuse them (plan 19 Decision 2). Re-exported here for existing callers.
from app.middleware.rbac import (
    admin_required, get_current_user, require_workspace_access, require_workspace_role,
)

workspaces_bp = Blueprint('workspaces', __name__)


@workspaces_bp.route('/', methods=['GET'])
@jwt_required()
def list_workspaces():
    user = get_current_user()
    include_archived = request.args.get('include_archived', 'false') == 'true'
    # Super-admins see all, others see their memberships
    if user.is_admin and request.args.get('all') == 'true':
        workspaces = WorkspaceService.get_all_workspaces_admin()
        return jsonify({'workspaces': workspaces})
    workspaces = WorkspaceService.list_workspaces(user_id=user.id, include_archived=include_archived)
    # Surface the caller's membership role and the reconciled effective role (#33)
    # so the frontend can show read-only state when a workspace caps the user to
    # viewer. effective_role is narrow-only: it never exceeds the user's global role.
    out = []
    for ws in workspaces:
        d = ws.to_dict()
        d['my_role'] = WorkspaceService.get_user_role(ws.id, user.id)
        d['my_effective_role'] = WorkspaceService.effective_role(user, ws.id)
        out.append(d)
    return jsonify({'workspaces': out})


@workspaces_bp.route('/<int:workspace_id>', methods=['GET'])
@jwt_required()
def get_workspace(workspace_id):
    user = get_current_user()
    denied = require_workspace_access(workspace_id, user)
    if denied:
        return denied
    ws = WorkspaceService.get_workspace(workspace_id)
    if not ws:
        return jsonify({'error': 'Workspace not found'}), 404
    d = ws.to_dict()
    d['my_role'] = WorkspaceService.get_user_role(ws.id, user.id)
    d['my_effective_role'] = WorkspaceService.effective_role(user, ws.id)
    return jsonify(d)


@workspaces_bp.route('/', methods=['POST'])
@jwt_required()
@admin_required
def create_workspace():
    user = get_current_user()
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400
    try:
        ws = WorkspaceService.create_workspace(data, user.id)
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE, user_id=user.id,
            target_type='workspace', target_id=ws.id,
            details={'name': ws.name}
        )
        return jsonify(ws.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@workspaces_bp.route('/<int:workspace_id>', methods=['PUT'])
@jwt_required()
def update_workspace(workspace_id):
    user = get_current_user()
    role = WorkspaceService.get_user_role(workspace_id, user.id)
    if role not in ['owner', 'admin'] and not user.is_admin:
        return jsonify({'error': 'Insufficient permissions'}), 403

    data = request.get_json()
    ws = WorkspaceService.update_workspace(workspace_id, data)
    if not ws:
        return jsonify({'error': 'Workspace not found'}), 404
    return jsonify(ws.to_dict())


@workspaces_bp.route('/<int:workspace_id>/archive', methods=['POST'])
@jwt_required()
def archive_workspace(workspace_id):
    user = get_current_user()
    role = WorkspaceService.get_user_role(workspace_id, user.id)
    if role != 'owner' and not user.is_admin:
        return jsonify({'error': 'Owner access required'}), 403
    ws = WorkspaceService.archive_workspace(workspace_id)
    if not ws:
        return jsonify({'error': 'Workspace not found'}), 404
    return jsonify(ws.to_dict())


@workspaces_bp.route('/<int:workspace_id>/restore', methods=['POST'])
@jwt_required()
def restore_workspace(workspace_id):
    user = get_current_user()
    if not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    ws = WorkspaceService.restore_workspace(workspace_id)
    if not ws:
        return jsonify({'error': 'Workspace not found'}), 404
    return jsonify(ws.to_dict())


@workspaces_bp.route('/<int:workspace_id>', methods=['DELETE'])
@jwt_required()
def delete_workspace(workspace_id):
    user = get_current_user()
    if not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    result = WorkspaceService.delete_workspace(workspace_id)
    if not result:
        return jsonify({'error': 'Workspace not found'}), 404
    return jsonify({'message': 'Workspace deleted'})


# --- Members ---

@workspaces_bp.route('/<int:workspace_id>/members', methods=['GET'])
@jwt_required()
def get_members(workspace_id):
    user = get_current_user()
    denied = require_workspace_access(workspace_id, user)
    if denied:
        return denied
    members = WorkspaceService.get_members(workspace_id)
    return jsonify({'members': [m.to_dict() for m in members]})


@workspaces_bp.route('/<int:workspace_id>/members', methods=['POST'])
@jwt_required()
def add_member(workspace_id):
    user = get_current_user()
    role = WorkspaceService.get_user_role(workspace_id, user.id)
    if role not in ['owner', 'admin'] and not user.is_admin:
        return jsonify({'error': 'Insufficient permissions'}), 403

    data = request.get_json() or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    try:
        member = WorkspaceService.add_member(workspace_id, user_id, data.get('role', 'member'))
        return jsonify(member.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@workspaces_bp.route('/members/<int:member_id>/role', methods=['PUT'])
@jwt_required()
def update_member_role(member_id):
    user = get_current_user()
    member = WorkspaceService.get_member(member_id)
    if not member:
        return jsonify({'error': 'Member not found'}), 404
    denied = require_workspace_role(member.workspace_id, user, ['owner', 'admin'])
    if denied:
        return denied
    data = request.get_json() or {}
    role = data.get('role')
    if not role:
        return jsonify({'error': 'role required'}), 400
    member = WorkspaceService.update_member_role(member_id, role)
    if not member:
        return jsonify({'error': 'Member not found'}), 404
    return jsonify(member.to_dict())


@workspaces_bp.route('/members/<int:member_id>', methods=['DELETE'])
@jwt_required()
def remove_member(member_id):
    user = get_current_user()
    member = WorkspaceService.get_member(member_id)
    if not member:
        return jsonify({'error': 'Member not found'}), 404
    denied = require_workspace_role(member.workspace_id, user, ['owner', 'admin'])
    if denied:
        return denied
    try:
        result = WorkspaceService.remove_member(member_id)
        if not result:
            return jsonify({'error': 'Member not found'}), 404
        return jsonify({'message': 'Member removed'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# --- API Keys ---

@workspaces_bp.route('/<int:workspace_id>/api-keys', methods=['GET'])
@jwt_required()
def list_api_keys(workspace_id):
    user = get_current_user()
    denied = require_workspace_access(workspace_id, user)
    if denied:
        return denied
    keys = WorkspaceService.list_api_keys(workspace_id)
    return jsonify({'api_keys': [k.to_dict() for k in keys]})


@workspaces_bp.route('/<int:workspace_id>/api-keys', methods=['POST'])
@jwt_required()
def create_api_key(workspace_id):
    user = get_current_user()
    denied = require_workspace_role(workspace_id, user, ['owner', 'admin'])
    if denied:
        return denied
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name required'}), 400

    api_key, raw_key = WorkspaceService.create_api_key(
        workspace_id, name, scopes=data.get('scopes'), user_id=user.id
    )
    AuditService.log(
        action=AuditLog.ACTION_RESOURCE_CREATE, user_id=user.id,
        target_type='workspace_api_key', target_id=api_key.id,
        details={'workspace_id': workspace_id, 'name': name}
    )
    result = api_key.to_dict()
    result['key'] = raw_key  # Only returned once
    return jsonify(result), 201


@workspaces_bp.route('/api-keys/<int:key_id>/revoke', methods=['POST'])
@jwt_required()
def revoke_api_key(key_id):
    user = get_current_user()
    api_key = WorkspaceService.get_api_key(key_id)
    if not api_key:
        return jsonify({'error': 'API key not found'}), 404
    denied = require_workspace_role(api_key.workspace_id, user, ['owner', 'admin'])
    if denied:
        return denied
    result = WorkspaceService.revoke_api_key(key_id)
    if not result:
        return jsonify({'error': 'API key not found'}), 404
    AuditService.log(
        action=AuditLog.ACTION_RESOURCE_DELETE, user_id=user.id,
        target_type='workspace_api_key', target_id=key_id,
        details={'workspace_id': api_key.workspace_id}
    )
    return jsonify({'message': 'API key revoked'})
