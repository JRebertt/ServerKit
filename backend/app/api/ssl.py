from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.rbac import admin_required
from app.services.ssl_service import SSLService, get_acme_contact, remember_acme_contact

ssl_bp = Blueprint('ssl', __name__)


@ssl_bp.route('/acme-contact', methods=['GET'])
@jwt_required()
def acme_contact():
    """The panel-wide ACME contact, for prefilling certificate forms.

    Deliberately not admin-gated: issuing a certificate for an app you can
    edit is not an admin action, so the surfaces that need this prefill are
    reachable by non-admins too. The value is the address the operator chose
    to receive expiry notices at, not a credential.
    """
    return jsonify({'email': get_acme_contact() or ''}), 200


@ssl_bp.route('/certificates', methods=['GET'])
@jwt_required()
@admin_required
def list_certificates():
    """List all SSL certificates."""
    certificates = SSLService.list_certificates()
    return jsonify({'certificates': certificates}), 200


@ssl_bp.route('/certificates/<domain>', methods=['GET'])
@jwt_required()
@admin_required
def get_certificate(domain):
    """Get details for a specific certificate."""
    info = SSLService.get_certificate_info(domain)
    if info:
        return jsonify({'certificate': info}), 200
    return jsonify({'error': 'Certificate not found'}), 404


@ssl_bp.route('/certificates', methods=['POST'])
@jwt_required()
@admin_required
def obtain_certificate():
    """Obtain a new SSL certificate from Let's Encrypt."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    domains = data.get('domains')
    # Falls back to the stored panel-wide contact, so a caller that has one
    # configured no longer has to repeat it on every request.
    email = get_acme_contact(data.get('email'))

    if not domains or not email:
        return jsonify({'error': 'domains and email are required'}), 400

    result = SSLService.obtain_certificate(
        domains=domains,
        email=email,
        webroot_path=data.get('webroot_path'),
        use_nginx=data.get('use_nginx', True)
    )

    if result.get('success'):
        remember_acme_contact(data.get('email'), user_id=get_jwt_identity())

    return jsonify(result), 201 if result['success'] else 400


@ssl_bp.route('/certificates/<domain>/renew', methods=['POST'])
@jwt_required()
@admin_required
def renew_certificate(domain):
    """Renew a specific certificate."""
    result = SSLService.renew_certificate(domain)
    return jsonify(result), 200 if result['success'] else 400


@ssl_bp.route('/certificates/renew-all', methods=['POST'])
@jwt_required()
@admin_required
def renew_all_certificates():
    """Renew all certificates that need renewal."""
    result = SSLService.renew_certificate()
    return jsonify(result), 200 if result['success'] else 400


@ssl_bp.route('/certificates/<domain>', methods=['DELETE'])
@jwt_required()
@admin_required
def revoke_certificate(domain):
    """Revoke and delete a certificate."""
    result = SSLService.revoke_certificate(domain)
    return jsonify(result), 200 if result['success'] else 400


@ssl_bp.route('/certificates/<domain>/check', methods=['GET'])
@jwt_required()
@admin_required
def check_certificate_expiry(domain):
    """Check if a certificate is expiring soon."""
    result = SSLService.check_expiry(domain)
    return jsonify(result), 200


@ssl_bp.route('/auto-renewal', methods=['POST'])
@jwt_required()
@admin_required
def setup_auto_renewal():
    """Set up automatic certificate renewal."""
    result = SSLService.setup_auto_renewal()
    return jsonify(result), 200 if result['success'] else 400


@ssl_bp.route('/install-certbot', methods=['POST'])
@jwt_required()
@admin_required
def install_certbot():
    """Install certbot if not already installed."""
    if SSLService.is_certbot_installed():
        return jsonify({'success': True, 'message': 'Certbot is already installed'}), 200

    result = SSLService.install_certbot()
    return jsonify(result), 200 if result['success'] else 400


@ssl_bp.route('/status', methods=['GET'])
@jwt_required()
@admin_required
def get_ssl_status():
    """Get overall SSL status."""
    is_installed = SSLService.is_certbot_installed()
    certificates = SSLService.list_certificates()

    expiring_soon = []
    for cert in certificates:
        check = SSLService.check_expiry(cert['name'])
        if check.get('expiring_soon'):
            expiring_soon.append(cert['name'])

    return jsonify({
        'certbot_installed': is_installed,
        'total_certificates': len(certificates),
        'expiring_soon': expiring_soon,
        'certificates': certificates
    }), 200
