from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.nginx_advanced_service import NginxAdvancedService
from app.middleware.rbac import get_current_user

nginx_advanced_bp = Blueprint('nginx_advanced', __name__)


@nginx_advanced_bp.route('/proxy/<domain>', methods=['GET'])
@jwt_required()
def get_proxy_rules(domain):
    result = NginxAdvancedService.get_proxy_rules(domain)
    if 'error' in result:
        return jsonify(result), 404
    return jsonify(result)


@nginx_advanced_bp.route('/proxy', methods=['POST'])
@jwt_required()
def create_proxy():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json()
    if not data or 'domain' not in data:
        return jsonify({'error': 'domain required'}), 400

    result = NginxAdvancedService.create_reverse_proxy(data)
    return jsonify(result), 201


@nginx_advanced_bp.route('/test', methods=['POST'])
@jwt_required()
def test_config():
    result = NginxAdvancedService.test_config()
    return jsonify(result)


@nginx_advanced_bp.route('/reload', methods=['POST'])
@jwt_required()
def reload():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    result = NginxAdvancedService.reload_nginx()
    return jsonify(result)


@nginx_advanced_bp.route('/diff', methods=['POST'])
@jwt_required()
def preview_diff():
    data = request.get_json() or {}
    domain = data.get('domain')
    new_config = data.get('config', '')
    if not domain:
        return jsonify({'error': 'domain required'}), 400
    result = NginxAdvancedService.preview_diff(domain, new_config)
    return jsonify(result)


@nginx_advanced_bp.route('/logs/<domain>', methods=['GET'])
@jwt_required()
def get_logs(domain):
    log_type = request.args.get('type', 'access')
    lines = request.args.get('lines', 100, type=int)
    result = NginxAdvancedService.get_vhost_logs(domain, log_type, lines)
    return jsonify(result)


@nginx_advanced_bp.route('/lb-methods', methods=['GET'])
@jwt_required()
def get_lb_methods():
    return jsonify({'methods': NginxAdvancedService.get_load_balancing_methods()})
