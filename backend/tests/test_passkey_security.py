"""Real pinned WebAuthn verifier coverage with locally signed synthetic credentials."""
import hashlib
import json

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from flask_jwt_extended import decode_token

from app import db
from app.models import PasskeyCredential
from app.services.passkey_service import PasskeyService, _b64decode_url, _b64encode_url
from factories import make_user


@pytest.fixture(autouse=True)
def relying_party(monkeypatch):
    monkeypatch.setenv('SERVERKIT_PASSKEY_RP_ID', 'localhost')
    monkeypatch.setenv('SERVERKIT_PASSKEY_ORIGIN', 'http://localhost')


def _key_material():
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    cose = cbor2.dumps({1: 2, 3: -7, -1: 1,
                       -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})
    return key, cose


def _client_data(challenge, ceremony):
    return json.dumps({'type': ceremony, 'challenge': challenge, 'origin': 'http://localhost'}).encode()


def _registration(challenge, credential_id, cose, verified):
    client_data = _client_data(challenge, 'webauthn.create')
    flags = 0x41 | (0x04 if verified else 0)
    auth_data = (hashlib.sha256(b'localhost').digest() + bytes([flags]) + bytes(4)
                 + bytes(16) + len(credential_id).to_bytes(2, 'big') + credential_id + cose)
    attestation = cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth_data})
    return {'id': _b64encode_url(credential_id), 'rawId': _b64encode_url(credential_id),
            'type': 'public-key', 'response': {'clientDataJSON': _b64encode_url(client_data),
                                            'attestationObject': _b64encode_url(attestation),
                                            'transports': ['internal']}}


def _assertion(challenge, credential_id, private_key, verified, counter=1):
    client_data = _client_data(challenge, 'webauthn.get')
    auth_data = hashlib.sha256(b'localhost').digest() + bytes([0x05 if verified else 0x01]) + counter.to_bytes(4, 'big')
    signed_data = auth_data + hashlib.sha256(client_data).digest()
    signature = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
    return {'id': _b64encode_url(credential_id), 'rawId': _b64encode_url(credential_id),
            'type': 'public-key', 'response': {'clientDataJSON': _b64encode_url(client_data),
                                            'authenticatorData': _b64encode_url(auth_data),
                                            'signature': _b64encode_url(signature)}}


def test_pinned_webauthn_generates_browser_options_and_requires_uv(app):
    with app.app_context():
        user = make_user(db)
        registration = PasskeyService.begin_registration(user)
        assert registration['authenticatorSelection']['userVerification'] == 'required'
        assert registration['attestation'] == 'none'
        assert len(_b64decode_url(registration['challenge'])) == 32
        _, cose = _key_material()
        saved = PasskeyCredential(user_id=user.id, credential_id=_b64encode_url(b'test'),
                                 public_key=_b64encode_url(cose))
        saved.set_transports(['internal', 'unknown-future-transport'])
        db.session.add(saved)
        db.session.commit()
        authentication = PasskeyService.begin_authentication(user)
        assert authentication['userVerification'] == 'required'
        assert authentication['allowCredentials'][0]['transports'] == ['internal']
        assert authentication['allowCredentials'][0]['id'] == saved.credential_id


def test_registration_enforces_uv_with_real_attestation_verifier(app):
    with app.app_context():
        user = make_user(db)
        _, cose = _key_material()
        options = PasskeyService.begin_registration(user)
        credential = _registration(options['challenge'], b'registration-test', cose, False)
        denied = PasskeyService.verify_registration(user, credential)
        assert not denied['success'] and 'verified' in denied['error'].lower()
        assert PasskeyCredential.query.count() == 0
        credential = _registration(options['challenge'], b'registration-test', cose, True)
        accepted = PasskeyService.verify_registration(user, credential)
        assert accepted['success']
        assert accepted['passkey']['transports'] == ['internal']
        assert PasskeyService._get_challenge(user.id, 'register') is None


@pytest.mark.parametrize('discoverable', [False, True])
def test_uvless_passkey_cannot_skip_mfa_but_verified_passkey_mints_revocable_pair(app, client, discoverable):
    with app.app_context():
        user = make_user(db, role='admin', totp_enabled=True, password_hash=None)
        key, cose = _key_material()
        cid = b'authentication-test'
        saved = PasskeyCredential(user_id=user.id, credential_id=_b64encode_url(cid), public_key=_b64encode_url(cose))
        db.session.add(saved)
        db.session.commit()
        identity = {} if discoverable else {'user_id': user.id}
        options_response = client.post('/api/v1/auth/passkeys/options/authenticate', json=identity)
        assert options_response.status_code == 200
        challenge = options_response.json['challenge']
        response = client.post('/api/v1/auth/passkeys/authenticate', json={
            **identity, 'credential': _assertion(challenge, cid, key, False),
        })
        assert response.status_code == 401
        assert 'access_token' not in response.json
        response = client.post('/api/v1/auth/passkeys/authenticate', json={
            **identity, 'credential': _assertion(challenge, cid, key, True),
        })
        assert response.status_code == 200, response.json
        access, refresh = response.json['access_token'], response.json['refresh_token']
        assert decode_token(access)['session_id'] == decode_token(refresh)['session_id']
        assert decode_token(access)['auth_version'] == user.auth_version
        assert PasskeyService._get_challenge(0 if discoverable else user.id, 'auth') is None
        assert client.post('/api/v1/auth/logout', headers={'Authorization': f'Bearer {access}'}).status_code == 200
        assert client.post('/api/v1/auth/refresh', headers={'Authorization': f'Bearer {refresh}'}).status_code == 401


def test_named_user_authentication_rejects_another_users_credential(app):
    with app.app_context():
        expected = make_user(db)
        foreign = make_user(db)
        key, cose = _key_material()
        cid = b'foreign-passkey'
        db.session.add(PasskeyCredential(user_id=foreign.id, credential_id=_b64encode_url(cid),
                                        public_key=_b64encode_url(cose)))
        db.session.commit()
        options = PasskeyService.begin_authentication(expected)
        assertion = _assertion(options['challenge'], cid, key, True)
        assert not PasskeyService.verify_authentication(assertion, expected)['success']
