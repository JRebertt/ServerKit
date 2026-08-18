from flask import Blueprint, request, jsonify
from app.middleware.rbac import admin_required
from app.services.php_service import PHPService

php_bp = Blueprint('php', __name__)


@php_bp.route('/versions', methods=['GET'])
@admin_required
def get_versions():
    """Get installed PHP versions."""
    versions = PHPService.get_installed_versions()
    default = PHPService.get_default_version()
    return jsonify({
        'versions': versions,
        'default': default,
        'supported': PHPService.SUPPORTED_VERSIONS
    }), 200


@php_bp.route('/versions/<version>/install', methods=['POST'])
@admin_required
def install_version(version):
    """Install a PHP version."""
    result = PHPService.install_version(version)
    return jsonify(result), 200 if result['success'] else 400


@php_bp.route('/versions/default', methods=['POST'])
@admin_required
def set_default_version():
    """Set default PHP version."""
    data = request.get_json()
    version = data.get('version') if data else None

    if not version:
        return jsonify({'error': 'version is required'}), 400

    result = PHPService.set_default_version(version)
    return jsonify(result), 200 if result['success'] else 400


@php_bp.route('/versions/<version>/extensions', methods=['GET'])
@admin_required
def get_extensions(version):
    """Get installed extensions for a PHP version."""
    extensions = PHPService.get_extensions(version)
    return jsonify({'extensions': extensions, 'version': version}), 200


@php_bp.route('/versions/<version>/extensions', methods=['POST'])
@admin_required
def install_extension(version):
    """Install a PHP extension."""
    data = request.get_json()
    extension = data.get('extension') if data else None

    if not extension:
        return jsonify({'error': 'extension is required'}), 400

    result = PHPService.install_extension(version, extension)
    return jsonify(result), 200 if result['success'] else 400


@php_bp.route('/versions/<version>/pools', methods=['GET'])
@admin_required
def get_pools(version):
    """Get FPM pools for a PHP version."""
    pools = PHPService.get_pools(version)
    return jsonify({'pools': pools, 'version': version}), 200


@php_bp.route('/versions/<version>/pools', methods=['POST'])
@admin_required
def create_pool(version):
    """Create a new FPM pool."""
    data = request.get_json()

    if not data or 'name' not in data:
        return jsonify({'error': 'Pool name is required'}), 400

    result = PHPService.create_pool(version, data['name'], data)
    return jsonify(result), 201 if result['success'] else 400


@php_bp.route('/versions/<version>/pools/<pool_name>', methods=['DELETE'])
@admin_required
def delete_pool(version, pool_name):
    """Delete an FPM pool."""
    result = PHPService.delete_pool(version, pool_name)
    return jsonify(result), 200 if result['success'] else 400


@php_bp.route('/versions/<version>/fpm/restart', methods=['POST'])
@admin_required
def restart_fpm(version):
    """Restart PHP-FPM service."""
    result = PHPService.restart_fpm(version)
    return jsonify(result), 200 if result['success'] else 400


@php_bp.route('/versions/<version>/fpm/reload', methods=['POST'])
@admin_required
def reload_fpm(version):
    """Reload PHP-FPM service."""
    result = PHPService.reload_fpm(version)
    return jsonify(result), 200 if result['success'] else 400


@php_bp.route('/versions/<version>/fpm/status', methods=['GET'])
@admin_required
def get_fpm_status(version):
    """Get PHP-FPM service status."""
    status = PHPService.get_fpm_status(version)
    return jsonify(status), 200


@php_bp.route('/versions/<version>/info', methods=['GET'])
@admin_required
def get_php_info(version):
    """Get PHP configuration info."""
    info = PHPService.get_php_info(version)
    if 'error' in info:
        return jsonify(info), 400
    return jsonify({'info': info, 'version': version}), 200
