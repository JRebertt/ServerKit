from flask import Blueprint, request, jsonify
from app.middleware.rbac import admin_required
from app.services.nginx_service import NginxService

nginx_bp = Blueprint('nginx', __name__)


@nginx_bp.route('/status', methods=['GET'])
@admin_required
def get_status():
    """Get Nginx service status."""
    status = NginxService.get_status()
    return jsonify(status), 200


@nginx_bp.route('/test', methods=['POST'])
@admin_required
def test_config():
    """Test Nginx configuration syntax."""
    result = NginxService.test_config()
    return jsonify(result), 200 if result['success'] else 400


@nginx_bp.route('/reload', methods=['POST'])
@admin_required
def reload_nginx():
    """Reload Nginx configuration."""
    result = NginxService.reload()
    return jsonify(result), 200 if result['success'] else 400


@nginx_bp.route('/restart', methods=['POST'])
@admin_required
def restart_nginx():
    """Restart Nginx service."""
    result = NginxService.restart()
    return jsonify(result), 200 if result['success'] else 400


@nginx_bp.route('/sites', methods=['GET'])
@admin_required
def list_sites():
    """List all Nginx sites."""
    sites = NginxService.list_sites()
    return jsonify({'sites': sites}), 200


@nginx_bp.route('/sites', methods=['POST'])
@admin_required
def create_site():
    """Create a new Nginx site configuration."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    required_fields = ['name', 'app_type', 'domains', 'root_path']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    result = NginxService.create_site(
        name=data['name'],
        app_type=data['app_type'],
        domains=data['domains'],
        root_path=data['root_path'],
        port=data.get('port'),
        php_version=data.get('php_version', '8.2')
    )

    return jsonify(result), 201 if result['success'] else 400


@nginx_bp.route('/sites/<name>/enable', methods=['POST'])
@admin_required
def enable_site(name):
    """Enable a site."""
    result = NginxService.enable_site(name)
    return jsonify(result), 200 if result['success'] else 400


@nginx_bp.route('/sites/<name>/disable', methods=['POST'])
@admin_required
def disable_site(name):
    """Disable a site."""
    result = NginxService.disable_site(name)
    return jsonify(result), 200 if result['success'] else 400


@nginx_bp.route('/sites/<name>', methods=['DELETE'])
@admin_required
def delete_site(name):
    """Delete a site configuration."""
    result = NginxService.delete_site(name)
    return jsonify(result), 200 if result['success'] else 400


@nginx_bp.route('/sites/<name>/ssl', methods=['POST'])
@admin_required
def add_ssl_to_site(name):
    """Add SSL configuration to a site."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    cert_path = data.get('cert_path')
    key_path = data.get('key_path')

    if not cert_path or not key_path:
        return jsonify({'error': 'cert_path and key_path are required'}), 400

    result = NginxService.add_ssl_to_site(name, cert_path, key_path)
    return jsonify(result), 200 if result['success'] else 400
