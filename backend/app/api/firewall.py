"""Firewall API endpoints for managing firewalld and ufw."""

from flask import Blueprint, request, jsonify

from ..middleware.rbac import admin_required, viewer_required
from ..services.firewall_service import FirewallService
from ..services.metadata_guard_service import MetadataGuardService, SETTING_KEY

firewall_bp = Blueprint('firewall', __name__)


@firewall_bp.route('/status', methods=['GET'])
@viewer_required
def get_status():
    """Get firewall status."""
    result = FirewallService.get_status()
    return jsonify(result), 200


@firewall_bp.route('/ssh-preflight', methods=['GET'])
@viewer_required
def ssh_preflight():
    """Would enabling the firewall cut off SSH?

    Lets the UI warn before the operator clicks, rather than reporting a
    lockout after it has already happened.
    """
    firewall = request.args.get('firewall') or (
        FirewallService.get_status().get('active_firewall') or 'ufw')
    return jsonify(FirewallService.check_ssh_lockout(firewall)), 200


@firewall_bp.route('/enable', methods=['POST'])
@admin_required
def enable_firewall():
    """Enable the firewall.

    Blocked with 409 when no rule covers the live SSH port — `ufw --force
    enable` suppresses ufw's own "may disrupt existing ssh connections" prompt,
    so this is the only thing standing between a click and a locked-out box.
    Resend with force=true to override.
    """
    data = request.get_json() or {}
    firewall = data.get('firewall')
    force = bool(data.get('force'))

    result = FirewallService.enable(firewall, force=force)

    if result.get('success'):
        return jsonify(result), 200
    # 409, not 400: the request is well-formed, the server state conflicts.
    if result.get('blocked_by') == 'ssh_lockout':
        return jsonify(result), 409
    return jsonify(result), 400


@firewall_bp.route('/disable', methods=['POST'])
@admin_required
def disable_firewall():
    """Disable the firewall."""
    data = request.get_json() or {}
    firewall = data.get('firewall')

    result = FirewallService.disable(firewall)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@firewall_bp.route('/rules', methods=['GET'])
@viewer_required
def get_rules():
    """Get all firewall rules."""
    firewall = request.args.get('firewall')
    result = FirewallService.get_rules(firewall)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@firewall_bp.route('/rules', methods=['POST'])
@admin_required
def add_rule():
    """Add a firewall rule."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    rule_type = data.get('type')
    if not rule_type:
        return jsonify({'success': False, 'error': 'Rule type required'}), 400

    # Extract parameters based on rule type
    kwargs = {k: v for k, v in data.items() if k != 'type'}

    result = FirewallService.add_rule(rule_type, **kwargs)

    if result.get('success'):
        return jsonify(result), 201
    return jsonify(result), 400


@firewall_bp.route('/rules/removal-preflight', methods=['POST'])
@viewer_required
def rule_removal_preflight():
    """Would removing this rule cut off SSH? Lets the UI warn before the click."""
    data = request.get_json() or {}
    rule_type = data.get('type')
    kwargs = {k: v for k, v in data.items() if k not in ('type', 'force')}
    return jsonify(FirewallService.check_ssh_rule_removal(rule_type, **kwargs)), 200


@firewall_bp.route('/rules', methods=['DELETE'])
@admin_required
def remove_rule():
    """Remove a firewall rule.

    Blocked with 409 when the rule is the last one admitting SSH on a firewall
    that is currently enforcing — deleting it would close the caller's own
    session. Resend with force=true to override.
    """
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    rule_type = data.get('type')
    if not rule_type:
        return jsonify({'success': False, 'error': 'Rule type required'}), 400

    force = bool(data.get('force'))
    kwargs = {k: v for k, v in data.items() if k not in ('type', 'force')}

    result = FirewallService.remove_rule(rule_type, force=force, **kwargs)

    if result.get('success'):
        return jsonify(result), 200
    if result.get('blocked_by') == 'ssh_lockout':
        return jsonify(result), 409
    return jsonify(result), 400


@firewall_bp.route('/block-ip', methods=['POST'])
@admin_required
def block_ip():
    """Quick block an IP address."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    ip = data.get('ip')
    if not ip:
        return jsonify({'success': False, 'error': 'IP address required'}), 400

    permanent = data.get('permanent', True)

    # request.remote_addr is the real client when TRUST_PROXY_HEADERS is on
    # (ProxyFix rewrites it); otherwise it is the proxy, which is still worth
    # refusing to block. Read here rather than in the service, so the service
    # stays free of request context.
    result = FirewallService.block_ip(ip, permanent,
                                      force=bool(data.get('force')),
                                      caller_ip=request.remote_addr)

    if result.get('success'):
        return jsonify(result), 201
    if result.get('blocked_by') == 'ssh_lockout':
        return jsonify(result), 409
    return jsonify(result), 400


@firewall_bp.route('/unblock-ip', methods=['POST'])
@admin_required
def unblock_ip():
    """Unblock an IP address."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    ip = data.get('ip')
    if not ip:
        return jsonify({'success': False, 'error': 'IP address required'}), 400

    permanent = data.get('permanent', True)

    result = FirewallService.unblock_ip(ip, permanent)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@firewall_bp.route('/blocked-ips', methods=['GET'])
@viewer_required
def get_blocked_ips():
    """Get list of blocked IP addresses."""
    result = FirewallService.get_blocked_ips()

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@firewall_bp.route('/allow-port', methods=['POST'])
@admin_required
def allow_port():
    """Allow a port through the firewall."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    port = data.get('port')
    if not port:
        return jsonify({'success': False, 'error': 'Port number required'}), 400

    protocol = data.get('protocol', 'tcp')
    permanent = data.get('permanent', True)

    result = FirewallService.allow_port(port, protocol, permanent)

    if result.get('success'):
        return jsonify(result), 201
    return jsonify(result), 400


@firewall_bp.route('/deny-port', methods=['POST'])
@admin_required
def deny_port():
    """Remove a port from the firewall."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    port = data.get('port')
    if not port:
        return jsonify({'success': False, 'error': 'Port number required'}), 400

    protocol = data.get('protocol', 'tcp')
    permanent = data.get('permanent', True)

    # Denying a port is implemented as removing its allow rule, so this shares
    # the SSH-lockout guard with DELETE /rules.
    result = FirewallService.deny_port(port, protocol, permanent,
                                       force=bool(data.get('force')))

    if result.get('success'):
        return jsonify(result), 200
    if result.get('blocked_by') == 'ssh_lockout':
        return jsonify(result), 409
    return jsonify(result), 400


@firewall_bp.route('/zones', methods=['GET'])
@viewer_required
def get_zones():
    """Get firewalld zones."""
    result = FirewallService.get_zones()

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@firewall_bp.route('/zones/default', methods=['POST'])
@admin_required
def set_default_zone():
    """Set default firewalld zone."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    zone = data.get('zone')
    if not zone:
        return jsonify({'success': False, 'error': 'Zone name required'}), 400

    result = FirewallService.set_default_zone(zone, force=bool(data.get('force')))

    if result.get('success'):
        return jsonify(result), 200
    if result.get('blocked_by') == 'ssh_lockout':
        return jsonify(result), 409
    return jsonify(result), 400


@firewall_bp.route('/metadata-guard', methods=['GET'])
@viewer_required
def get_metadata_guard():
    """Get cloud metadata guard status."""
    return jsonify(MetadataGuardService.status()), 200


@firewall_bp.route('/metadata-guard', methods=['PUT'])
@admin_required
def set_metadata_guard():
    """Enable or disable the cloud metadata egress guard."""
    data = request.get_json()

    if not data or 'enabled' not in data:
        return jsonify({'error': "Request body with 'enabled' required"}), 400

    enabled = bool(data['enabled'])

    from ..services.settings_service import SettingsService
    SettingsService.set(SETTING_KEY, enabled)

    result = MetadataGuardService.ensure()
    status = MetadataGuardService.status()
    if not result.get('success') and result.get('supported', True):
        status['error'] = result.get('error', 'Failed to update metadata guard')
        return jsonify(status), 500
    return jsonify(status), 200


@firewall_bp.route('/install', methods=['POST'])
@admin_required
def install_firewall():
    """Install a firewall (ufw or firewalld)."""
    data = request.get_json() or {}
    firewall = data.get('firewall', 'ufw')

    result = FirewallService.install_firewall(firewall)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400
