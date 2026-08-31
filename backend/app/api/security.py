# Bucket: PER-APP (plan 29 #9). Per-app scan/security routes gate on the shared
# app-access seam; host-level surfaces stay admin-only.
#
# Lean core (plan 47 Ph3b-4 / plan 55 Phase 3): this blueprint keeps only the
# baseline that works with zero host packages — status/config, legacy
# integrity, suspicious activity, events, SSH keys, IP lists, the audit and
# scoped FIM. The install-gated tool surfaces (/clamav/*, /scan/*,
# /quarantine/*, /yara/*, /fail2ban/*, /lynis/*, /auto-updates/*,
# /image-scans/*, /sboms/*) are mounted at this same /api/v1/security prefix
# by their extensions (serverkit-clamav, serverkit-fail2ban, serverkit-lynis,
# serverkit-auto-updates, serverkit-image-scan) and 404 when absent.
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.middleware.rbac import admin_required
from app.services.security_service import SecurityService
from app.error_reporting import unexpected_response

security_bp = Blueprint('security', __name__)


# ==========================================
# STATUS & CONFIG
# ==========================================
@security_bp.route('/status', methods=['GET'])
@jwt_required()
def get_security_status():
    """Get overall security status summary."""
    summary = SecurityService.get_security_summary()
    return jsonify(summary), 200


@security_bp.route('/config', methods=['GET'])
@admin_required
def get_config():
    """Get security configuration."""
    config = SecurityService.get_config()
    return jsonify(config), 200


@security_bp.route('/config', methods=['PUT'])
@admin_required
def update_config():
    """Update security configuration."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    current_config = SecurityService.get_config()

    # Update nested config sections
    for key in ['clamav', 'file_integrity', 'suspicious_activity', 'notifications']:
        if key in data:
            current_config[key] = {**current_config.get(key, {}), **data[key]}

    result = SecurityService.save_config(current_config)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# FILE INTEGRITY
# ==========================================
@security_bp.route('/integrity/initialize', methods=['POST'])
@admin_required
def initialize_integrity():
    """Create baseline for file integrity monitoring."""
    data = request.get_json() or {}
    paths = data.get('paths')
    result = SecurityService.initialize_integrity_database(paths)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/integrity/check', methods=['GET'])
@admin_required
def check_integrity():
    """Check files against integrity database."""
    result = SecurityService.check_file_integrity()
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# SUSPICIOUS ACTIVITY
# ==========================================
@security_bp.route('/failed-logins', methods=['GET'])
@admin_required
def check_failed_logins():
    """Check for failed login attempts."""
    hours = request.args.get('hours', 24, type=int)
    result = SecurityService.check_failed_logins(hours)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# EVENTS & ALERTS
# ==========================================
@security_bp.route('/events', methods=['GET'])
@jwt_required()
def get_security_events():
    """Get recent security events/alerts."""
    limit = request.args.get('limit', 100, type=int)
    result = SecurityService.get_security_events(limit)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# SSH KEYS
# ==========================================
@security_bp.route('/ssh-keys', methods=['GET'])
@admin_required
def get_ssh_keys():
    """Get SSH authorized keys."""
    user = request.args.get('user', 'root')
    result = SecurityService.get_ssh_keys(user)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ssh-keys', methods=['POST'])
@admin_required
def add_ssh_key():
    """Add an SSH public key."""
    data = request.get_json()
    if not data or 'key' not in data:
        return jsonify({'error': 'SSH key required'}), 400

    user = data.get('user', 'root')
    result = SecurityService.add_ssh_key(data['key'], user)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ssh-keys/<int:key_id>', methods=['DELETE'])
@admin_required
def remove_ssh_key(key_id):
    """Remove an SSH key."""
    user = request.args.get('user', 'root')
    result = SecurityService.remove_ssh_key(key_id, user)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# IP ALLOWLIST/BLOCKLIST
# ==========================================
@security_bp.route('/ip-lists', methods=['GET'])
@admin_required
def get_ip_lists():
    """Get IP allowlist and blocklist."""
    result = SecurityService.get_ip_lists()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ip-lists/<list_type>', methods=['POST'])
@admin_required
def add_to_ip_list(list_type):
    """Add IP to allowlist or blocklist."""
    data = request.get_json()
    if not data or 'ip' not in data:
        return jsonify({'error': 'IP address required'}), 400

    comment = data.get('comment', '')
    result = SecurityService.add_to_ip_list(data['ip'], list_type, comment)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ip-lists/<list_type>/<ip>', methods=['DELETE'])
@admin_required
def remove_from_ip_list(list_type, ip):
    """Remove IP from allowlist or blocklist."""
    result = SecurityService.remove_from_ip_list(ip, list_type)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# SECURITY AUDIT
# ==========================================
@security_bp.route('/audit', methods=['GET'])
@admin_required
def generate_audit():
    """Generate a security audit report."""
    result = SecurityService.generate_security_audit()
    return jsonify(result), 200 if result['success'] else 400


# FILE INTEGRITY MONITORING (SCOPED FIM)
# ==========================================
# Baseline-and-diff over ServerKit-managed paths (nginx / systemd /
# opted-in app docroots). The legacy /integrity/* endpoints above are kept
# as-is for compatibility; this is the scoped surface the UI uses.

@security_bp.route('/fim', methods=['GET'])
@jwt_required()
def get_fim_status():
    """Get FIM scopes, baselines and last check results."""
    from app.services.file_integrity_service import FileIntegrityService
    return jsonify(FileIntegrityService.get_status()), 200


@security_bp.route('/fim/<scope>/baseline', methods=['POST'])
@admin_required
def fim_baseline(scope):
    """Create (or recreate) the baseline for a scope."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    data = request.get_json(silent=True) or {}
    options = data.get('options') if isinstance(data.get('options'), dict) else None
    try:
        result = FileIntegrityService.baseline(scope, options=options)
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
    return jsonify(result), 200


@security_bp.route('/fim/<scope>/check', methods=['POST'])
@admin_required
def fim_check(scope):
    """Diff the scope against its baseline."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    try:
        result = FileIntegrityService.check(scope)
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
    return jsonify(result), 200


@security_bp.route('/fim/<scope>/accept', methods=['POST'])
@admin_required
def fim_accept(scope):
    """Accept current state (re-baseline the scope)."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    try:
        result = FileIntegrityService.accept(scope)
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
    return jsonify(result), 200


@security_bp.route('/fim/apps', methods=['PUT'])
@admin_required
def fim_set_app_optins():
    """Set the per-app FIM opt-in list: {app_ids: [1, 2, ...]}."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    data = request.get_json(silent=True)
    if not data or 'app_ids' not in data:
        return jsonify({'error': 'app_ids required'}), 400
    try:
        ids = FileIntegrityService.set_app_optins(data['app_ids'])
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'app_optins': ids}), 200
