"""Service for managing team invitations."""
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app import db
from app.models import User, Invitation


class InvitationService:
    """Stateless service for invitation operations."""

    @staticmethod
    def create_invitation(email=None, role='developer', permissions=None,
                          invited_by=None, expires_in_days=7):
        """Create a new invitation."""
        if role not in User.VALID_ROLES:
            return {'success': False, 'error': f'Invalid role: {role}'}

        # Check for duplicate pending invite with same email
        if email:
            existing = Invitation.query.filter_by(
                email=email, status=Invitation.STATUS_PENDING
            ).first()
            if existing and not existing.is_expired:
                return {'success': False, 'error': 'A pending invitation already exists for this email'}

        expires_at = None
        if expires_in_days and expires_in_days > 0:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        invitation = Invitation(
            email=email,
            role=role,
            invited_by=invited_by,
            expires_at=expires_at,
        )
        if permissions:
            invitation.set_permissions(permissions)

        db.session.add(invitation)
        db.session.commit()

        return {'success': True, 'invitation': invitation}

    @staticmethod
    def validate_token(token):
        """Validate an invite token. Returns Invitation if valid, else None."""
        invitation = Invitation.query.filter_by(token=token).first()
        if not invitation:
            return None

        # Auto-expire if past date
        if invitation.status == Invitation.STATUS_PENDING and invitation.is_expired:
            invitation.status = Invitation.STATUS_EXPIRED
            db.session.commit()
            return None

        if invitation.status != Invitation.STATUS_PENDING:
            return None

        return invitation

    @staticmethod
    def accept_invitation(token, user_id):
        """Mark an invitation as accepted."""
        invitation = InvitationService.validate_token(token)
        if not invitation:
            return {'success': False, 'error': 'Invalid or expired invitation'}

        invitation.status = Invitation.STATUS_ACCEPTED
        invitation.accepted_at = datetime.utcnow()
        invitation.accepted_by = user_id
        db.session.commit()

        return {'success': True, 'invitation': invitation}

    @staticmethod
    def revoke_invitation(invitation_id):
        """Revoke a pending invitation."""
        invitation = Invitation.query.get(invitation_id)
        if not invitation:
            return {'success': False, 'error': 'Invitation not found'}

        if invitation.status != Invitation.STATUS_PENDING:
            return {'success': False, 'error': 'Only pending invitations can be revoked'}

        invitation.status = Invitation.STATUS_REVOKED
        db.session.commit()

        return {'success': True}

    @staticmethod
    def get_resend_candidate(invitation_id):
        """Return an invitation that is eligible for another email delivery.

        Keeping the lookup and invitation-state rules here prevents transport
        handlers from reaching into the ORM just to prepare a resend.
        """
        invitation = db.session.get(Invitation, invitation_id)
        if not invitation:
            return {
                'success': False,
                'reason': 'not_found',
                'error': 'Invitation not found',
            }

        if invitation.status != Invitation.STATUS_PENDING:
            return {
                'success': False,
                'reason': 'not_pending',
                'error': 'Can only resend pending invitations',
            }

        if not invitation.email:
            return {
                'success': False,
                'reason': 'missing_email',
                'error': 'Invitation has no email address',
            }

        return {'success': True, 'invitation': invitation}

    @staticmethod
    def list_invitations(status=None):
        """List invitations, optionally filtered by status."""
        query = Invitation.query.order_by(Invitation.created_at.desc())
        if status:
            query = query.filter_by(status=status)
        return query.all()

    @staticmethod
    def send_invitation_email(invitation, base_url):
        """Send invitation email via SMTP. Returns {success, error}."""
        if not invitation.email:
            return {'success': False, 'error': 'No email address on invitation'}

        try:
            from app.services.notification_service import NotificationService
            config = NotificationService.get_config()
            email_config = config.get('email', {})
        except Exception:
            return {'success': False, 'error': 'Could not load email configuration'}

        if not email_config.get('smtp_host') or not email_config.get('from_email'):
            return {'success': False, 'error': 'SMTP not configured'}

        invite_url = f"{base_url}/register?invite={invitation.token}"

        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'You have been invited to ServerKit'
        msg['From'] = email_config['from_email']
        msg['To'] = invitation.email

        text = (
            f"You have been invited to join ServerKit as a {invitation.role}.\n\n"
            f"Click the link below to create your account:\n{invite_url}\n\n"
        )
        if invitation.expires_at:
            text += f"This invitation expires on {invitation.expires_at.strftime('%Y-%m-%d %H:%M UTC')}.\n"

        html = (
            f"<h2>You're invited to ServerKit</h2>"
            f"<p>You have been invited to join as a <strong>{invitation.role}</strong>.</p>"
            f"<p><a href=\"{invite_url}\" style=\"display:inline-block;padding:10px 20px;"
            f"background:#6366f1;color:#fff;text-decoration:none;border-radius:6px;\">"
            f"Accept Invitation</a></p>"
        )
        if invitation.expires_at:
            html += f"<p style=\"color:#888;\">Expires {invitation.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</p>"

        msg.attach(MIMEText(text, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        try:
            smtp_port = int(email_config.get('smtp_port', 587))
            use_tls = email_config.get('smtp_tls', True)

            if use_tls:
                server = smtplib.SMTP(email_config['smtp_host'], smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(email_config['smtp_host'], smtp_port)

            if email_config.get('smtp_user') and email_config.get('smtp_password'):
                server.login(email_config['smtp_user'], email_config['smtp_password'])

            server.sendmail(email_config['from_email'], [invitation.email], msg.as_string())
            server.quit()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def cleanup_expired():
        """Batch-mark expired invitations."""
        now = datetime.utcnow()
        expired = Invitation.query.filter(
            Invitation.status == Invitation.STATUS_PENDING,
            Invitation.expires_at.isnot(None),
            Invitation.expires_at < now
        ).all()

        count = 0
        for inv in expired:
            inv.status = Invitation.STATUS_EXPIRED
            count += 1

        if count:
            db.session.commit()
        return count
