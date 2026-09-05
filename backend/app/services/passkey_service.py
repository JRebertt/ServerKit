"""WebAuthn / Passkey authentication service."""
import base64
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from webauthn import generate_registration_options, verify_registration_response
from webauthn import generate_authentication_options, verify_authentication_response
from webauthn import options_to_json
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from webauthn.helpers.exceptions import InvalidRegistrationResponse, InvalidAuthenticationResponse

from app import db
from app.models import User, PasskeyCredential

logger = logging.getLogger(__name__)


def _get_rp_id() -> str:
    return os.environ.get('SERVERKIT_PASSKEY_RP_ID', os.environ.get('BASE_URL', 'localhost').replace('https://', '').replace('http://', '').split(':')[0])


def _get_rp_name() -> str:
    return os.environ.get('SERVERKIT_PASSKEY_RP_NAME', 'ServerKit')


def _get_origin() -> str:
    origin = os.environ.get('SERVERKIT_PASSKEY_ORIGIN', os.environ.get('BASE_URL', 'http://localhost'))
    return origin.rstrip('/')


def _b64encode_url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64decode_url(value: str) -> bytes:
    if not value:
        return b''
    padding = 4 - len(value) % 4
    if padding != 4:
        value += '=' * padding
    return base64.urlsafe_b64decode(value)


class PasskeyService:
    """Manage WebAuthn registration and authentication."""

    @classmethod
    def _challenge_key(cls, user_id: int, suffix: str) -> str:
        return f'passkey_{suffix}_challenge_{user_id}'

    @classmethod
    def _get_challenge(cls, user_id: int, suffix: str) -> Optional[bytes]:
        # Use SystemSettings as a simple server-side challenge store.
        # Challenges expire naturally because they are overwritten on each request.
        from app.models import SystemSettings
        setting = SystemSettings.query.filter_by(key=cls._challenge_key(user_id, suffix)).first()
        if not setting or not setting.value:
            return None
        try:
            return _b64decode_url(setting.value)
        except Exception:
            return None

    @classmethod
    def _set_challenge(cls, user_id: int, suffix: str, challenge: bytes) -> None:
        from app.models import SystemSettings
        key = cls._challenge_key(user_id, suffix)
        setting = SystemSettings.query.filter_by(key=key).first()
        if not setting:
            setting = SystemSettings(key=key, value_type='string')
            db.session.add(setting)
        setting.value = _b64encode_url(challenge)
        db.session.commit()

    @classmethod
    def _clear_challenge(cls, user_id: int, suffix: str) -> None:
        from app.models import SystemSettings
        key = cls._challenge_key(user_id, suffix)
        SystemSettings.query.filter_by(key=key).delete(synchronize_session=False)
        db.session.commit()

    @classmethod
    def get_user_passkeys(cls, user_id: int) -> List[Dict]:
        return [p.to_dict() for p in PasskeyCredential.query.filter_by(user_id=user_id, is_active=True).all()]

    @classmethod
    def begin_registration(cls, user: User) -> Dict:
        """Generate WebAuthn registration options for the user."""
        options = generate_registration_options(
            rp_id=_get_rp_id(),
            rp_name=_get_rp_name(),
            user_id=str(user.id).encode(),
            user_name=user.email,
            user_display_name=user.username or user.email,
            challenge=os.urandom(32),
            timeout=60000,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            ),
        )
        cls._set_challenge(user.id, 'register', options.challenge)
        return json.loads(options_to_json(options))

    @classmethod
    def verify_registration(cls, user: User, credential: Dict, device_name: str = '') -> Dict:
        """Verify and store a new WebAuthn credential."""
        challenge = cls._get_challenge(user.id, 'register')
        if not challenge:
            return {'success': False, 'error': 'Registration challenge expired or missing'}

        try:
            result = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=_get_rp_id(),
                expected_origin=_get_origin(),
                require_user_verification=True,
            )
        except InvalidRegistrationResponse as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.exception('Passkey registration verification failed')
            return {'success': False, 'error': str(e)}

        cls._clear_challenge(user.id, 'register')

        passkey = PasskeyCredential(
            user_id=user.id,
            credential_id=_b64encode_url(result.credential_id),
            public_key=_b64encode_url(result.credential_public_key),
            sign_count=result.sign_count,
            device_name=device_name or 'Passkey',
        )
        transports = credential.get('transports') or credential.get('response', {}).get('transports')
        if transports:
            passkey.set_transports(transports)

        db.session.add(passkey)
        db.session.commit()

        return {'success': True, 'passkey': passkey.to_dict()}

    @classmethod
    def begin_authentication(cls, user: Optional[User] = None) -> Dict:
        """Generate authentication options. If user is known, filter by their credentials."""
        allow_credentials = None
        if user:
            creds = PasskeyCredential.query.filter_by(user_id=user.id, is_active=True).all()
            allow_credentials = [
                PublicKeyCredentialDescriptor(
                    id=_b64decode_url(c.credential_id),
                    transports=[AuthenticatorTransport(t) for t in c.get_transports()
                                if t in {item.value for item in AuthenticatorTransport}],
                )
                for c in creds
            ]

        options = generate_authentication_options(
            rp_id=_get_rp_id(),
            challenge=os.urandom(32),
            timeout=60000,
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        # Store challenge globally or per-user. We store per-user if known.
        challenge_user_id = user.id if user else 0
        cls._set_challenge(challenge_user_id, 'auth', options.challenge)
        return json.loads(options_to_json(options))

    @classmethod
    def verify_authentication(cls, credential: Dict, user: Optional[User] = None) -> Dict:
        """Verify a WebAuthn assertion and return the authenticated user."""
        challenge_user_id = user.id if user else 0
        challenge = cls._get_challenge(challenge_user_id, 'auth')
        if not challenge:
            return {'success': False, 'error': 'Authentication challenge expired or missing'}

        credential_id_b64 = credential.get('id')
        if not credential_id_b64:
            return {'success': False, 'error': 'Missing credential id'}

        passkey = PasskeyCredential.query.filter_by(credential_id=credential_id_b64, is_active=True).first()
        if not passkey or (user is not None and passkey.user_id != user.id):
            return {'success': False, 'error': 'Unknown passkey'}

        try:
            result = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=_get_rp_id(),
                expected_origin=_get_origin(),
                credential_public_key=_b64decode_url(passkey.public_key),
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=True,
            )
        except InvalidAuthenticationResponse as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.exception('Passkey authentication verification failed')
            return {'success': False, 'error': str(e)}

        cls._clear_challenge(challenge_user_id, 'auth')

        passkey.sign_count = result.new_sign_count
        passkey.last_used_at = datetime.utcnow()
        db.session.commit()

        return {'success': True, 'user': passkey.user}

    @classmethod
    def remove_passkey(cls, user_id: int, passkey_id: int) -> Dict:
        passkey = PasskeyCredential.query.filter_by(id=passkey_id, user_id=user_id).first()
        if not passkey:
            return {'success': False, 'error': 'Passkey not found'}
        db.session.delete(passkey)
        db.session.commit()
        return {'success': True, 'message': 'Passkey removed'}

    @classmethod
    def is_enabled_for_user(cls, user_id: int) -> bool:
        return PasskeyCredential.query.filter_by(user_id=user_id, is_active=True).count() > 0
