"""Invitation API endpoints for team invitations."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.models import AuditLog
from app.middleware.rbac import admin_required
from app.services.invitation_service import InvitationService
from app.services.audit_service import AuditService

invitations_bp = Blueprint('invitations', __name__)


@invitations_bp.route('/', methods=['GET'])
@admin_required
def list_invitations():
    """List all invitations, optionally filtered by status."""
    status = request.args.get('status')
    invitations = InvitationService.list_invitations(status=status)
    return jsonify({
        'invitations': [inv.to_dict() for inv in invitations]
    }), 200


@invitations_bp.route('/', methods=['POST'])
@admin_required
def create_invitation():
    """Create a new invitation."""
    data = request.get_json()
    current_user_id = get_jwt_identity()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    email = data.get('email')  # Optional
    role = data.get('role', 'developer')
    permissions = data.get('permissions')
    expires_in_days = data.get('expires_in_days', 7)

    result = InvitationService.create_invitation(
        email=email,
        role=role,
        permissions=permissions,
        invited_by=current_user_id,
        expires_in_days=expires_in_days
    )

    if not result['success']:
        return jsonify({'error': result['error']}), 400

    invitation = result['invitation']

    # Build invite URL
    base_url = request.host_url.rstrip('/')
    invite_url = f"{base_url}/register?invite={invitation.token}"

    # Try to send email if email provided
    email_sent = False
    email_error = None
    if email:
        email_result = InvitationService.send_invitation_email(invitation, base_url)
        email_sent = email_result['success']
        if not email_sent:
            email_error = email_result.get('error')

    # Audit log
    AuditService.log(
        action=AuditLog.ACTION_INVITATION_CREATE,
        user_id=current_user_id,
        target_type='invitation',
        target_id=invitation.id,
        details={'email': email, 'role': role, 'email_sent': email_sent}
    )

    return jsonify({
        'message': 'Invitation created successfully',
        'invitation': invitation.to_dict(),
        'invite_url': invite_url,
        'email_sent': email_sent,
        'email_error': email_error,
    }), 201


@invitations_bp.route('/<int:invitation_id>', methods=['DELETE'])
@admin_required
def revoke_invitation(invitation_id):
    """Revoke a pending invitation."""
    current_user_id = get_jwt_identity()

    result = InvitationService.revoke_invitation(invitation_id)
    if not result['success']:
        return jsonify({'error': result['error']}), 400

    AuditService.log(
        action=AuditLog.ACTION_INVITATION_REVOKE,
        user_id=current_user_id,
        target_type='invitation',
        target_id=invitation_id,
    )

    return jsonify({'message': 'Invitation revoked'}), 200


@invitations_bp.route('/resend/<int:invitation_id>', methods=['POST'])
@admin_required
def resend_invitation(invitation_id):
    """Resend invitation email."""
    candidate = InvitationService.get_resend_candidate(invitation_id)
    if not candidate['success']:
        status = 404 if candidate['reason'] == 'not_found' else 400
        return jsonify({'error': candidate['error']}), status
    invitation = candidate['invitation']

    base_url = request.host_url.rstrip('/')
    result = InvitationService.send_invitation_email(invitation, base_url)

    if not result['success']:
        return jsonify({'error': result.get('error', 'Failed to send email')}), 500

    return jsonify({'message': 'Invitation email resent'}), 200


@invitations_bp.route('/validate/<token>', methods=['GET'])
def validate_invitation(token):
    """Validate an invite token (public endpoint for registration page)."""
    invitation = InvitationService.validate_token(token)
    if not invitation:
        return jsonify({'error': 'Invalid or expired invitation'}), 404

    return jsonify({
        'valid': True,
        'email': invitation.email,
        'role': invitation.role,
    }), 200
