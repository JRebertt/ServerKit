from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.agent_plugin_service import AgentPluginService
from app.services.audit_service import AuditService
from app.models.audit_log import AuditLog
from app.middleware.rbac import get_current_user

agent_plugins_bp = Blueprint('agent_plugins', __name__)


@agent_plugins_bp.route('/', methods=['GET'])
@jwt_required()
def list_plugins():
    status = request.args.get('status')
    plugins = AgentPluginService.list_plugins(status=status)
    return jsonify({'plugins': [p.to_dict() for p in plugins]})


@agent_plugins_bp.route('/<int:plugin_id>', methods=['GET'])
@jwt_required()
def get_plugin(plugin_id):
    plugin = AgentPluginService.get_plugin(plugin_id)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404
    return jsonify(plugin.to_dict())


@agent_plugins_bp.route('/', methods=['POST'])
@jwt_required()
def create_plugin():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    # Validate manifest
    errors = AgentPluginService.validate_manifest(data)
    if errors:
        return jsonify({'error': 'Invalid manifest', 'details': errors}), 400

    try:
        plugin = AgentPluginService.create_plugin(data)
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user.id,
            target_type='agent_plugin',
            target_id=plugin.id,
            details={'name': plugin.name, 'version': plugin.version}
        )
        return jsonify(plugin.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@agent_plugins_bp.route('/<int:plugin_id>', methods=['PUT'])
@jwt_required()
def update_plugin(plugin_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json()
    plugin = AgentPluginService.update_plugin(plugin_id, data)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404

    return jsonify(plugin.to_dict())


@agent_plugins_bp.route('/<int:plugin_id>', methods=['DELETE'])
@jwt_required()
def delete_plugin(plugin_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    try:
        result = AgentPluginService.delete_plugin(plugin_id)
        if not result:
            return jsonify({'error': 'Plugin not found'}), 404
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_DELETE,
            user_id=user.id,
            target_type='agent_plugin',
            target_id=plugin_id,
            details={}
        )
        return jsonify({'message': 'Plugin deleted'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@agent_plugins_bp.route('/validate', methods=['POST'])
@jwt_required()
def validate_manifest():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Manifest data required'}), 400
    errors = AgentPluginService.validate_manifest(data)
    return jsonify({'valid': len(errors) == 0, 'errors': errors})


# --- Installation endpoints ---

@agent_plugins_bp.route('/<int:plugin_id>/install', methods=['POST'])
@jwt_required()
def install_plugin(plugin_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json() or {}
    server_id = data.get('server_id')
    if not server_id:
        return jsonify({'error': 'server_id required'}), 400

    try:
        install = AgentPluginService.install_plugin(
            plugin_id, server_id, config=data.get('config')
        )
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user.id,
            target_type='agent_plugin_install',
            target_id=install.id,
            details={'plugin_id': plugin_id, 'server_id': server_id}
        )
        return jsonify(install.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@agent_plugins_bp.route('/<int:plugin_id>/bulk-install', methods=['POST'])
@jwt_required()
def bulk_install_plugin(plugin_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json() or {}
    server_ids = data.get('server_ids', [])
    if not server_ids:
        return jsonify({'error': 'server_ids required'}), 400

    results = AgentPluginService.bulk_install(plugin_id, server_ids, config=data.get('config'))
    return jsonify({'results': results})


@agent_plugins_bp.route('/<int:plugin_id>/installations', methods=['GET'])
@jwt_required()
def get_plugin_installations(plugin_id):
    installs = AgentPluginService.get_plugin_installations(plugin_id)
    return jsonify({'installations': [i.to_dict() for i in installs]})


@agent_plugins_bp.route('/installs/<int:install_id>', methods=['GET'])
@jwt_required()
def get_install(install_id):
    install = AgentPluginService.get_install(install_id)
    if not install:
        return jsonify({'error': 'Installation not found'}), 404
    return jsonify(install.to_dict())


@agent_plugins_bp.route('/installs/<int:install_id>/enable', methods=['POST'])
@jwt_required()
def enable_install(install_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    install = AgentPluginService.enable_plugin(install_id)
    if not install:
        return jsonify({'error': 'Installation not found'}), 404
    return jsonify(install.to_dict())


@agent_plugins_bp.route('/installs/<int:install_id>/disable', methods=['POST'])
@jwt_required()
def disable_install(install_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    install = AgentPluginService.disable_plugin(install_id)
    if not install:
        return jsonify({'error': 'Installation not found'}), 404
    return jsonify(install.to_dict())


@agent_plugins_bp.route('/installs/<int:install_id>', methods=['DELETE'])
@jwt_required()
def uninstall_plugin(install_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    result = AgentPluginService.uninstall_plugin(install_id)
    if not result:
        return jsonify({'error': 'Installation not found'}), 404
    return jsonify({'message': 'Plugin uninstall initiated'})


@agent_plugins_bp.route('/installs/<int:install_id>/config', methods=['PUT'])
@jwt_required()
def update_install_config(install_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json()
    if not data or 'config' not in data:
        return jsonify({'error': 'config required'}), 400

    install = AgentPluginService.update_install_config(install_id, data['config'])
    if not install:
        return jsonify({'error': 'Installation not found'}), 404
    return jsonify(install.to_dict())


@agent_plugins_bp.route('/server/<int:server_id>', methods=['GET'])
@jwt_required()
def get_server_plugins(server_id):
    installs = AgentPluginService.get_server_plugins(server_id)
    return jsonify({'plugins': [i.to_dict() for i in installs]})


@agent_plugins_bp.route('/spec', methods=['GET'])
@jwt_required()
def get_plugin_spec():
    """Return the plugin specification interface."""
    return jsonify(AgentPluginService.PLUGIN_SPEC)
