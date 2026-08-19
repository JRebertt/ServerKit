from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.ddns_service import DdnsService
from app.middleware.rbac import get_current_user

ddns_bp = Blueprint('ddns', __name__)


def _admin():
    user = get_current_user()
    return user if user and user.is_admin else None


# --- Management (authenticated, admin) ---

@ddns_bp.route('/hosts', methods=['GET'])
@jwt_required()
def list_hosts():
    hosts = DdnsService.list_hosts()
    return jsonify({'hosts': [h.to_dict() for h in hosts]})


@ddns_bp.route('/hosts', methods=['POST'])
@jwt_required()
def create_host():
    if not _admin():
        return jsonify({'error': 'Admin access required'}), 403
    try:
        host = DdnsService.create_host(request.get_json() or {})
        # Return the token once, on creation — it is masked everywhere else.
        return jsonify(host.to_dict(include_token=True)), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@ddns_bp.route('/hosts/<int:host_id>', methods=['DELETE'])
@jwt_required()
def delete_host(host_id):
    if not _admin():
        return jsonify({'error': 'Admin access required'}), 403
    if not DdnsService.delete_host(host_id):
        return jsonify({'error': 'Host not found'}), 404
    return jsonify({'message': 'Host deleted'})


@ddns_bp.route('/hosts/<int:host_id>/regenerate-token', methods=['POST'])
@jwt_required()
def regenerate_token(host_id):
    if not _admin():
        return jsonify({'error': 'Admin access required'}), 403
    host = DdnsService.regenerate_token(host_id)
    if not host:
        return jsonify({'error': 'Host not found'}), 404
    return jsonify(host.to_dict(include_token=True))


# --- Update endpoint (public, token-authenticated) ---

def _client_ip():
    # DDNS legitimately wants the real client IP — the same trusted seam every
    # other consumer uses (ProxyFix-corrected remote_addr, see utils.client_ip).
    from app.utils.client_ip import get_client_ip
    return get_client_ip()


@ddns_bp.route('/update', methods=['GET', 'POST'])
def update():
    """Called by a router or cron when its public IP changes. There is no JWT
    here — the per-host token is the credential. The IP can be passed explicitly
    (?ip=) or inferred from the request source address."""
    body = request.get_json(silent=True) or {}
    token = request.args.get('token') or request.headers.get('X-DDNS-Token') or body.get('token')
    if not token:
        return jsonify({'error': 'token required'}), 401

    ip = request.args.get('ip') or body.get('ip') or _client_ip()
    status, host = DdnsService.update_ip(token, ip)
    return jsonify({'status': status, 'hostname': host.hostname, 'ip': ip})
