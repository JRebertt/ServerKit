"""GHSA-6w78-q5vm-rfmh class — secrets_webhooks by-id routes must enforce
workspace authorization, not just authentication.

- GET/PATCH/DELETE /api/v1/vaults/<id>                  (vault IDOR)
- GET/POST           /api/v1/vaults/<id>/secrets[...]   (secret list/create IDOR)
- GET/PATCH/DELETE   /api/v1/secrets/<id>               (secret IDOR)
- POST               /api/v1/secrets/<id>/reveal        (PLAINTEXT exposure)
- GET/PATCH/DELETE   /api/v1/webhooks/endpoints/<id>    (endpoint IDOR)
- POST               /api/v1/webhooks/endpoints/<id>/regenerate-secret
- GET                /api/v1/webhooks/endpoints/<id>/deliveries
- POST               /api/v1/webhooks/deliveries/<id>/replay

Reads require workspace membership (any role); mutations and secret-VALUE
exposure (reveal / regenerate-secret / replay) require the workspace
owner/admin role or a panel admin. Missing resources AND resources the caller
can't see both answer 404 (sealed-from-open, mirroring workspaces.py).
"""
import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash


@pytest.fixture
def vault_rbac(app, scoping_rbac):
    """One vault + secret + webhook endpoint + delivery, all scoped to
    scoping_rbac's workspace, plus a workspace-'owner' persona (the scoping
    fixture's member/viewer cover the lower workspace roles)."""
    from types import SimpleNamespace
    from app import db
    from app.models import (Secret, SecretVault, User, WebhookDelivery,
                            WebhookEndpoint)
    from app.services.workspace_service import WorkspaceService
    from app.utils.crypto import encrypt_secret

    ws_owner = User(email='scope_wsowner@t.local', username='scope_wsowner',
                    password_hash=generate_password_hash('x'),
                    role='developer', is_active=True)
    db.session.add(ws_owner)
    db.session.commit()
    WorkspaceService.add_member(scoping_rbac.ws_id, ws_owner.id, role='owner')

    vault = SecretVault(name='scope-vault', slug='scope-vault',
                        workspace_id=scoping_rbac.ws_id)
    db.session.add(vault)
    db.session.commit()

    secret = Secret(vault_id=vault.id, name='API_KEY',
                    encrypted_value=encrypt_secret('hunter2'))
    db.session.add(secret)

    endpoint = WebhookEndpoint(name='scope-endpoint', slug='scope-endpoint',
                               secret='whsec', forward_url='http://forward.local/hook',
                               workspace_id=scoping_rbac.ws_id)
    db.session.add(endpoint)
    db.session.commit()

    delivery = WebhookDelivery(endpoint_id=endpoint.id, event_id='evt-1',
                               payload='{"a": 1}', status='received')
    db.session.add(delivery)
    db.session.commit()

    return SimpleNamespace(
        vault_id=vault.id, secret_id=secret.id,
        endpoint_id=endpoint.id, delivery_id=delivery.id,
        ws_owner={'Authorization': f'Bearer {create_access_token(identity=ws_owner.id)}'},
        s=scoping_rbac,
    )


# ------------------------------- reads ----------------------------------- #

def test_vault_read_requires_membership(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/vaults/{vault_rbac.vault_id}'
    for persona in ('ws_owner', 'member', 'viewer', 'admin'):
        headers = getattr(vault_rbac, persona, None) or getattr(s, persona)
        assert client.get(url, headers=headers).status_code == 200, persona
    assert client.get(url, headers=s.foreign).status_code == 404


def test_vault_read_missing_404(client, vault_rbac):
    assert client.get('/api/v1/vaults/999999',
                      headers=vault_rbac.s.admin).status_code == 404


def test_secret_list_requires_membership(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/vaults/{vault_rbac.vault_id}/secrets'
    assert client.get(url, headers=s.viewer).status_code == 200
    assert client.get(url, headers=s.foreign).status_code == 404


def test_secret_read_requires_membership(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/secrets/{vault_rbac.secret_id}'
    for persona in ('member', 'viewer', 'admin'):
        assert client.get(url, headers=getattr(s, persona)).status_code == 200, persona
    assert client.get(url, headers=s.foreign).status_code == 404


def test_endpoint_read_requires_membership(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/webhooks/endpoints/{vault_rbac.endpoint_id}'
    assert client.get(url, headers=s.viewer).status_code == 200
    assert client.get(url, headers=s.foreign).status_code == 404


def test_deliveries_read_requires_membership(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/webhooks/endpoints/{vault_rbac.endpoint_id}/deliveries'
    assert client.get(url, headers=s.member).status_code == 200
    assert client.get(url, headers=s.foreign).status_code == 404


# --------------------- reveal (plaintext exposure) ------------------------ #

def test_reveal_secret_privileged_only(client, vault_rbac):
    """The most severe finding: plaintext of any secret in any vault was
    returned to any authenticated user. Now owner/admin-level only."""
    s = vault_rbac.s
    url = f'/api/v1/secrets/{vault_rbac.secret_id}/reveal'
    resp = client.post(url, headers=vault_rbac.ws_owner)
    assert resp.status_code == 200
    assert resp.get_json()['secret']['value'] == 'hunter2'
    resp = client.post(url, headers=s.admin)
    assert resp.status_code == 200
    assert resp.get_json()['secret']['value'] == 'hunter2'
    for persona in ('member', 'viewer', 'foreign'):
        resp = client.post(url, headers=getattr(s, persona))
        assert resp.status_code == 404, persona
        assert 'hunter2' not in resp.get_data(as_text=True)


# ----------------------------- mutations ---------------------------------- #

def test_vault_update_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/vaults/{vault_rbac.vault_id}'
    assert client.patch(url, json={'description': 'd'},
                        headers=vault_rbac.ws_owner).status_code == 200
    for persona in ('member', 'viewer', 'foreign'):
        assert client.patch(url, json={'description': 'x'},
                            headers=getattr(s, persona)).status_code == 404, persona


def test_vault_delete_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/vaults/{vault_rbac.vault_id}'
    for persona in ('member', 'viewer', 'foreign'):
        assert client.delete(url, headers=getattr(s, persona)).status_code == 404, persona
    assert client.delete(url, headers=s.admin).status_code == 200


def test_secret_create_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/vaults/{vault_rbac.vault_id}/secrets'
    body = {'name': 'NEW_KEY', 'value': 'v'}
    assert client.post(url, json=body, headers=vault_rbac.ws_owner).status_code == 201
    for persona in ('member', 'viewer', 'foreign'):
        assert client.post(url, json={'name': 'OTHER', 'value': 'v'},
                           headers=getattr(s, persona)).status_code == 404, persona


def test_secret_bulk_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/vaults/{vault_rbac.vault_id}/secrets/bulk'
    body = {'secrets': [{'name': 'BULK_KEY', 'value': 'v'}]}
    assert client.post(url, json=body, headers=vault_rbac.ws_owner).status_code == 207
    assert client.post(url, json=body, headers=s.member).status_code == 404
    assert client.post(url, json=body, headers=s.foreign).status_code == 404


def test_secret_update_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/secrets/{vault_rbac.secret_id}'
    assert client.patch(url, json={'description': 'd'},
                        headers=vault_rbac.ws_owner).status_code == 200
    for persona in ('member', 'viewer', 'foreign'):
        assert client.patch(url, json={'value': 'pwned'},
                            headers=getattr(s, persona)).status_code == 404, persona


def test_secret_delete_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/secrets/{vault_rbac.secret_id}'
    for persona in ('member', 'viewer', 'foreign'):
        assert client.delete(url, headers=getattr(s, persona)).status_code == 404, persona
    assert client.delete(url, headers=s.admin).status_code == 200


def test_secret_missing_404(client, vault_rbac):
    assert client.get('/api/v1/secrets/999999',
                      headers=vault_rbac.s.admin).status_code == 404
    assert client.post('/api/v1/secrets/999999/reveal',
                       headers=vault_rbac.s.admin).status_code == 404


# ------------------------- webhook gateway -------------------------------- #

def test_endpoint_update_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/webhooks/endpoints/{vault_rbac.endpoint_id}'
    assert client.patch(url, json={'retry_count': 5},
                        headers=vault_rbac.ws_owner).status_code == 200
    for persona in ('member', 'viewer', 'foreign'):
        assert client.patch(url, json={'retry_count': 1},
                            headers=getattr(s, persona)).status_code == 404, persona


def test_endpoint_regenerate_secret_privileged_only(client, vault_rbac):
    """Returns a new signing secret in plaintext — owner/admin-level only."""
    s = vault_rbac.s
    url = f'/api/v1/webhooks/endpoints/{vault_rbac.endpoint_id}/regenerate-secret'
    resp = client.post(url, headers=vault_rbac.ws_owner)
    assert resp.status_code == 200
    assert resp.get_json()['secret']
    for persona in ('member', 'viewer', 'foreign'):
        assert client.post(url, headers=getattr(s, persona)).status_code == 404, persona


def test_endpoint_delete_requires_owner_role(client, vault_rbac):
    s = vault_rbac.s
    url = f'/api/v1/webhooks/endpoints/{vault_rbac.endpoint_id}'
    for persona in ('member', 'viewer', 'foreign'):
        assert client.delete(url, headers=getattr(s, persona)).status_code == 404, persona
    assert client.delete(url, headers=s.admin).status_code == 200


def test_endpoint_missing_404(client, vault_rbac):
    admin = vault_rbac.s.admin
    assert client.get('/api/v1/webhooks/endpoints/999999', headers=admin).status_code == 404
    assert client.get('/api/v1/webhooks/endpoints/999999/deliveries',
                      headers=admin).status_code == 404


def test_delivery_replay_requires_owner_role(client, vault_rbac, monkeypatch):
    """Replay re-fires the payload at the forward URL — mutation-level gate.
    The actual HTTP forward is stubbed out."""
    from app.services.webhook_gateway_service import WebhookGatewayService
    monkeypatch.setattr(WebhookGatewayService, '_forward',
                        classmethod(lambda cls, e, d, p, h: {'success': True, 'status': 200, 'body': ''}))
    s = vault_rbac.s
    url = f'/api/v1/webhooks/deliveries/{vault_rbac.delivery_id}/replay'
    for persona in ('member', 'viewer', 'foreign'):
        assert client.post(url, headers=getattr(s, persona)).status_code == 404, persona
    assert client.post(url, headers=vault_rbac.ws_owner).status_code == 200
    assert client.post('/api/v1/webhooks/deliveries/999999/replay',
                       headers=s.admin).status_code == 404


# ------------------- inbound receiver (public, signature-authenticated) ----

def _sign(secret, payload):
    import hashlib
    import hmac
    return 'sha256=' + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_inbound_webhook_without_a_signature_is_rejected(client, vault_rbac, monkeypatch):
    """The receiver is unauthenticated by design — the HMAC signature IS the
    credential — so an *absent* signature has to fail exactly like a wrong one.

    It did not: the reject branch read ``if not signature_valid and
    signature_header``, which only fires for a request that bothered to sign.
    Sending no ``X-Hub-Signature-256`` at all skipped the branch entirely and
    the payload was logged, filtered and forwarded to ``forward_url``.
    """
    from app.services.webhook_gateway_service import WebhookGatewayService
    forwarded = []
    monkeypatch.setattr(WebhookGatewayService, '_forward',
                        classmethod(lambda cls, e, d, p, h: forwarded.append(p) or
                                    {'success': True, 'status': 200, 'body': ''}))

    resp = client.post('/api/v1/webhooks/receive/scope-endpoint',
                       data=b'{"a": 1}', content_type='application/json')
    assert resp.status_code == 401
    assert resp.get_json()['error'] == 'Missing signature'
    assert forwarded == [], 'an unsigned payload was forwarded upstream'


def test_inbound_webhook_with_a_wrong_signature_is_rejected(client, vault_rbac):
    resp = client.post('/api/v1/webhooks/receive/scope-endpoint',
                       data=b'{"a": 1}', content_type='application/json',
                       headers={'X-Hub-Signature-256': _sign('not-the-secret', b'{"a": 1}')})
    assert resp.status_code == 401
    assert resp.get_json()['error'] == 'Invalid signature'


def test_inbound_webhook_with_a_valid_signature_is_accepted(client, vault_rbac, monkeypatch):
    """Non-vacuity for the two rejections: a correctly signed delivery still
    reaches the forwarder."""
    from app.services.webhook_gateway_service import WebhookGatewayService
    forwarded = []
    monkeypatch.setattr(WebhookGatewayService, '_forward',
                        classmethod(lambda cls, e, d, p, h: forwarded.append(p) or
                                    {'success': True, 'status': 200, 'body': ''}))

    payload = b'{"a": 1}'
    resp = client.post('/api/v1/webhooks/receive/scope-endpoint',
                       data=payload, content_type='application/json',
                       headers={'X-Hub-Signature-256': _sign('whsec', payload)})
    assert resp.status_code == 200
    assert forwarded == [payload]
