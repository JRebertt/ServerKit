"""Coverage for invitation use cases moved out of the HTTP controller."""

import pytest


def _invitation(db, inviter_id, *, email='invitee@example.test', status='pending'):
    from app.models import Invitation

    invitation = Invitation(
        email=email,
        role='developer',
        invited_by=inviter_id,
        status=status,
    )
    db.session.add(invitation)
    db.session.commit()
    return invitation


@pytest.mark.parametrize(
    ('email', 'status', 'reason'),
    [
        ('invitee@example.test', 'accepted', 'not_pending'),
        (None, 'pending', 'missing_email'),
    ],
)
def test_resend_candidate_rules_live_in_service(
        app, db_session, auth_headers, email, status, reason):
    from app.models import User
    from app.services.invitation_service import InvitationService

    inviter = User.query.filter_by(username='testadmin').one()
    invitation = _invitation(
        db_session,
        inviter.id,
        email=email,
        status=status,
    )

    result = InvitationService.get_resend_candidate(invitation.id)

    assert result == {
        'success': False,
        'reason': reason,
        'error': (
            'Can only resend pending invitations'
            if reason == 'not_pending'
            else 'Invitation has no email address'
        ),
    }


def test_resend_candidate_returns_pending_email_invitation(
        app, db_session, auth_headers):
    from app.models import User
    from app.services.invitation_service import InvitationService

    inviter = User.query.filter_by(username='testadmin').one()
    invitation = _invitation(db_session, inviter.id)

    result = InvitationService.get_resend_candidate(invitation.id)

    assert result['success'] is True
    assert result['invitation'].id == invitation.id


def test_resend_endpoint_delegates_candidate_lookup_and_delivery(
        client, auth_headers, monkeypatch):
    from app.services.invitation_service import InvitationService

    candidate = type('InvitationStub', (), {'email': 'invitee@example.test'})()
    monkeypatch.setattr(
        InvitationService,
        'get_resend_candidate',
        staticmethod(lambda invitation_id: {
            'success': True,
            'invitation': candidate,
        }),
    )
    delivered = []
    monkeypatch.setattr(
        InvitationService,
        'send_invitation_email',
        staticmethod(lambda invitation, base_url: delivered.append(
            (invitation, base_url)
        ) or {'success': True}),
    )

    response = client.post(
        '/api/v1/admin/invitations/resend/42',
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.get_json() == {'message': 'Invitation email resent'}
    assert delivered and delivered[0][0] is candidate
