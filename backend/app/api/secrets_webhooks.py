"""API endpoints for secrets manager and inbound webhook gateway."""
from datetime import datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.middleware.rbac import get_current_user, require_workspace_access, require_workspace_role
from app.services.secret_vault_service import SecretService, SecretVaultService
from app.services.webhook_gateway_service import WebhookGatewayService
from app.services.workspace_service import WorkspaceService
from app.models import User, Workspace

bp = Blueprint('secrets_webhooks', __name__)


def _current_user_id() -> int:
    """The acting user's id, via the one identity door so an API-key
    caller is attributed to the key's owner rather than to nobody."""
    user = get_current_user()
    return user.id if user else None


def _resolve_ws_value():
    """Return the raw workspace context from header or query string."""
    return request.headers.get('X-Workspace-Id') or request.args.get('workspace_id')


def _resolve_ws():
    """Resolve the active workspace context (X-Workspace-Id header or
    ?workspace_id) to a workspace id, or None for an unscoped view — mirrors the
    servers/apps scoping (#33). Lenient: a stale/unknown context degrades to
    None rather than erroring."""
    from app.models import User
    from app.services.workspace_service import WorkspaceService
    user = get_current_user()
    return WorkspaceService.resolve_workspace_id(user, _resolve_ws_value())


def _json_or_form() -> dict:
    """Return JSON body if available, otherwise an empty dict."""
    if request.is_json:
        return request.get_json(silent=True) or {}
    return {}


# Workspace roles allowed to mutate vault/webhook resources and to expose secret
# VALUES (reveal / regenerate-secret) — mirroring the admin-gated connection-URI
# reveal in databases.py.
_WS_WRITE_ROLES = ('owner', 'admin')


def _ws_visible(workspace_id, roles=None):
    """True when the caller is a panel admin or a workspace member (any role for
    reads; owner/admin when `roles` is given)."""
    user = get_current_user()
    guard = (require_workspace_role(workspace_id, user, roles) if roles
             else require_workspace_access(workspace_id, user))
    return guard is None


def _vault_gate(vault_id, roles=None):
    """Resolve a vault and enforce workspace authorization. Sealed-from-open:
    a missing vault AND one the caller can't see both 404."""
    vault = SecretVaultService.get_vault(vault_id)
    if not vault or not _ws_visible(vault.workspace_id, roles):
        return None, ({'error': 'Vault not found'}, 404)
    return vault, None


def _secret_gate(secret_id, roles=None):
    """Resolve secret -> vault and enforce workspace authorization (404-sealed)."""
    secret = SecretService.get_secret(secret_id)
    if not secret:
        return None, ({'error': 'Secret not found'}, 404)
    vault, err = _vault_gate(secret.vault_id, roles)
    if err:
        return None, ({'error': 'Secret not found'}, 404)
    return secret, None


def _endpoint_gate(endpoint_id, roles=None):
    """Resolve a webhook endpoint and enforce workspace authorization (404-sealed)."""
    endpoint = WebhookGatewayService.get_endpoint(endpoint_id)
    if not endpoint or not _ws_visible(endpoint.workspace_id, roles):
        return None, ({'error': 'Endpoint not found'}, 404)
    return endpoint, None


def _delivery_gate(delivery_id, roles=None):
    """Resolve delivery -> endpoint -> workspace and enforce authorization
    (404-sealed)."""
    delivery = WebhookGatewayService.get_delivery(delivery_id)
    if not delivery or not delivery.endpoint:
        return None, ({'error': 'Delivery not found'}, 404)
    endpoint, err = _endpoint_gate(delivery.endpoint.id, roles)
    if err:
        return None, ({'error': 'Delivery not found'}, 404)
    return delivery, None


# ---------- Secret Vaults ----------

@bp.route('/vaults', methods=['GET'])
@jwt_required()
def list_vaults():
    return {'success': True, 'vaults': SecretVaultService.list_vaults(workspace_id=_resolve_ws())}


@bp.route('/vaults', methods=['POST'])
@jwt_required()
def create_vault():
    data = _json_or_form()
    name = data.get('name')
    if not name:
        return {'error': 'name is required'}, 400
    user = get_current_user()
    # Explicit workspace_id in the body takes precedence over the active context,
    # but the caller must be a member of that workspace.
    explicit_ws = data.get('workspace_id')
    if explicit_ws is not None:
        try:
            explicit_ws = int(explicit_ws)
        except (ValueError, TypeError):
            return {'error': 'workspace_id must be an integer'}, 400
        if Workspace.query.get(explicit_ws) is None:
            return {'error': 'Workspace not found'}, 404
        if not user.is_admin and WorkspaceService.get_user_role(explicit_ws, user.id) is None:
            return {'error': 'Workspace access denied'}, 403
        workspace_id = explicit_ws
    else:
        workspace_id = WorkspaceService.resolve_workspace_id(user, _resolve_ws_value())
    vault = SecretVaultService.create_vault(name, description=data.get('description'),
                                            user_id=user.id, workspace_id=workspace_id)
    return {'success': True, 'vault': vault}, 201


@bp.route('/vaults/<int:vault_id>', methods=['GET'])
@jwt_required()
def get_vault(vault_id):
    vault, err = _vault_gate(vault_id)
    if err:
        return err
    return {'success': True, 'vault': vault.to_dict()}


@bp.route('/vaults/<int:vault_id>', methods=['PATCH'])
@jwt_required()
def update_vault(vault_id):
    vault, err = _vault_gate(vault_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    data = _json_or_form()
    updated = SecretVaultService.update_vault(vault.id, name=data.get('name'), description=data.get('description'))
    return {'success': True, 'vault': updated}


@bp.route('/vaults/<int:vault_id>', methods=['DELETE'])
@jwt_required()
def delete_vault(vault_id):
    vault, err = _vault_gate(vault_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    SecretVaultService.delete_vault(vault.id)
    return {'success': True, 'message': 'Vault deleted'}


# ---------- Secrets ----------

@bp.route('/vaults/<int:vault_id>/secrets', methods=['GET'])
@jwt_required()
def list_secrets(vault_id):
    vault, err = _vault_gate(vault_id)
    if err:
        return err
    return {'success': True, 'secrets': SecretService.list_secrets(vault.id)}


@bp.route('/vaults/<int:vault_id>/secrets', methods=['POST'])
@jwt_required()
def create_secret(vault_id):
    vault, err = _vault_gate(vault_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    data = _json_or_form()
    name = data.get('name')
    value = data.get('value')
    if name is None or value is None:
        return {'error': 'name and value are required'}, 400
    expires_at = None
    if data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(data['expires_at'])
        except ValueError:
            return {'error': 'Invalid expires_at format'}, 400
    secret = SecretService.create_secret(vault.id, name, value, description=data.get('description'), expires_at=expires_at)
    return {'success': True, 'secret': secret}, 201


@bp.route('/vaults/<int:vault_id>/secrets/bulk', methods=['POST'])
@jwt_required()
def bulk_create_secrets(vault_id):
    vault, err = _vault_gate(vault_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    data = _json_or_form()
    secrets_list = data.get('secrets', [])
    if not isinstance(secrets_list, list):
        return {'error': 'secrets must be a list'}, 400
    result = SecretService.bulk_create_or_update(vault.id, secrets_list)
    return {'success': True, **result}, 207


@bp.route('/secrets/<int:secret_id>', methods=['GET'])
@jwt_required()
def get_secret(secret_id):
    secret, err = _secret_gate(secret_id)
    if err:
        return err
    return {'success': True, 'secret': secret.to_dict(mask=True)}


@bp.route('/secrets/<int:secret_id>', methods=['PATCH'])
@jwt_required()
def update_secret(secret_id):
    secret, err = _secret_gate(secret_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    data = _json_or_form()
    expires_at = None
    if data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(data['expires_at'])
        except ValueError:
            return {'error': 'Invalid expires_at format'}, 400
    updated = SecretService.update_secret(
        secret.id,
        value=data.get('value'),
        description=data.get('description'),
        expires_at=expires_at,
        rotate=data.get('rotate', False),
    )
    return {'success': True, 'secret': updated}


@bp.route('/secrets/<int:secret_id>/reveal', methods=['POST'])
@jwt_required()
def reveal_secret(secret_id):
    # Secret VALUE exposure is a privileged op (owner/admin workspace role or
    # panel admin), mirroring the admin-gated connection-URI reveal in databases.py.
    secret, err = _secret_gate(secret_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    revealed = SecretService.reveal_secret(secret.id)
    return {'success': True, 'secret': revealed}


@bp.route('/secrets/<int:secret_id>', methods=['DELETE'])
@jwt_required()
def delete_secret(secret_id):
    secret, err = _secret_gate(secret_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    SecretService.delete_secret(secret.id)
    return {'success': True, 'message': 'Secret deleted'}


# ---------- Webhook Endpoints ----------

@bp.route('/webhooks/endpoints', methods=['GET'])
@jwt_required()
def list_webhook_endpoints():
    return {'success': True, 'endpoints': WebhookGatewayService.list_endpoints(workspace_id=_resolve_ws())}


@bp.route('/webhooks/endpoints', methods=['POST'])
@jwt_required()
def create_webhook_endpoint():
    data = _json_or_form()
    name = data.get('name')
    if not name:
        return {'error': 'name is required'}, 400
    endpoint = WebhookGatewayService.create_endpoint(
        name=name,
        secret=data.get('secret'),
        forward_url=data.get('forward_url'),
        filter_paths=data.get('filter_paths'),
        retry_count=data.get('retry_count', 3),
        user_id=_current_user_id(),
        workspace_id=_resolve_ws(),
    )
    return {'success': True, 'endpoint': endpoint}, 201


@bp.route('/webhooks/endpoints/<int:endpoint_id>', methods=['GET'])
@jwt_required()
def get_webhook_endpoint(endpoint_id):
    endpoint, err = _endpoint_gate(endpoint_id)
    if err:
        return err
    return {'success': True, 'endpoint': endpoint.to_dict()}


@bp.route('/webhooks/endpoints/<int:endpoint_id>', methods=['PATCH'])
@jwt_required()
def update_webhook_endpoint(endpoint_id):
    endpoint, err = _endpoint_gate(endpoint_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    data = _json_or_form()
    updated = WebhookGatewayService.update_endpoint(
        endpoint.id,
        name=data.get('name'),
        forward_url=data.get('forward_url'),
        filter_paths=data.get('filter_paths'),
        retry_count=data.get('retry_count'),
        is_active=data.get('is_active'),
    )
    return {'success': True, 'endpoint': updated}


@bp.route('/webhooks/endpoints/<int:endpoint_id>/regenerate-secret', methods=['POST'])
@jwt_required()
def regenerate_webhook_secret(endpoint_id):
    # Returns a new signing secret in plaintext — privileged op like reveal.
    endpoint, err = _endpoint_gate(endpoint_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    result = WebhookGatewayService.regenerate_secret(endpoint.id)
    return {'success': True, **result}


@bp.route('/webhooks/endpoints/<int:endpoint_id>', methods=['DELETE'])
@jwt_required()
def delete_webhook_endpoint(endpoint_id):
    endpoint, err = _endpoint_gate(endpoint_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    WebhookGatewayService.delete_endpoint(endpoint.id)
    return {'success': True, 'message': 'Endpoint deleted'}


@bp.route('/webhooks/endpoints/<int:endpoint_id>/deliveries', methods=['GET'])
@jwt_required()
def list_webhook_deliveries(endpoint_id):
    endpoint, err = _endpoint_gate(endpoint_id)
    if err:
        return err
    limit = request.args.get('limit', 50, type=int)
    status = request.args.get('status')
    return {'success': True, 'deliveries': WebhookGatewayService.list_deliveries(endpoint.id, limit=limit, status=status)}


@bp.route('/webhooks/deliveries/<int:delivery_id>/replay', methods=['POST'])
@jwt_required()
def replay_webhook_delivery(delivery_id):
    delivery, err = _delivery_gate(delivery_id, roles=_WS_WRITE_ROLES)
    if err:
        return err
    # The replay operation succeeding and the forward succeeding are two
    # different facts; a failed forward is data, not an HTTP error.
    result = WebhookGatewayService.replay_delivery(delivery.id)
    return {'success': result['forwarded'], 'delivery': result['delivery']}


# ---------- Public webhook receiver ----------

@bp.route('/webhooks/receive/<string:slug>', methods=['POST'])
def receive_webhook(slug):
    payload = request.get_data() or b''
    headers = dict(request.headers)
    result, status = WebhookGatewayService.receive(slug, payload, headers)
    return result, status
