"""Unified connection registry — one normalized, read-only list of every
external account ServerKit is connected to (source, DNS, infra, registrar,
storage, container registries). The individual write paths still live in their
own blueprints; this is the single source of truth for "what's connected".

Container-registry credentials (for private image pulls) are the one write path
that lives *here*, since a registry is just another external account and has no
other natural home — see ``container_registry_service``.
"""

from flask import Blueprint, jsonify, request

from app.middleware.rbac import admin_required, auth_required, get_current_user
from app.services.connection_registry import ConnectionRegistry
from app.services.connection_provider_sdk import (
    ConnectionProviderRegistry,
    ConnectionRef,
)
# Register built-in provider adapters before serving SDK schema/operations.
from app.services import connection_providers  # noqa: F401
from app.services.container_registry_service import ContainerRegistryService
from app.services.workspace_service import WorkspaceService

connections_bp = Blueprint('connections', __name__)


@connections_bp.route('', methods=['GET'])
@connections_bp.route('/', methods=['GET'])
@admin_required
def list_connections():
    """List every connected external account (secret-free). Admin-only — these are
    server-wide credentials (Cloudflare tokens, cloud keys, …), not personal
    settings, so the whole Connections surface lives under Administration."""
    user = get_current_user()
    return jsonify({'connections': ConnectionRegistry.list_all(
        user_id=user.id if user else None)})


# ── Container registries ─────────────────────────────────────────────────────
# CRUD + a login round-trip test. Listing is available to any authenticated user
# (the app-create flow needs it to offer a registry picker); mutations are
# admin-only, matching every other credential store.

def _workspace_id():
    user = get_current_user()
    return WorkspaceService.resolve_workspace_id(
        user, request.headers.get('X-Workspace-Id') or request.args.get('workspace_id'))


def _connection_ref(kind, connection_id):
    user = get_current_user()
    normalized_id = int(connection_id) if str(connection_id).isdigit() else connection_id
    return ConnectionRef(
        kind=kind,
        connection_id=normalized_id,
        user_id=user.id if user else None,
        workspace_id=_workspace_id(),
    )


def _provider_response(result):
    if result.success:
        return jsonify(result.to_dict())
    status = {
        'validation_error': 400,
        'invalid_reference': 400,
        'not_found': 404,
        'unknown_provider': 404,
        'unsupported_operation': 405,
        'rate_limited': 429,
        'connection_test_failed': 502,
        'rotation_test_failed': 502,
    }.get(result.error_code, 502)
    response = jsonify(result.to_dict())
    if result.retry_after:
        response.headers['Retry-After'] = str(result.retry_after)
    return response, status


def _audit_provider_operation(kind, connection_id, operation, result):
    """One secret-free audit shape for provider mutations and live tests."""
    from app.services.audit_service import AuditService

    user = get_current_user()
    AuditService.log(
        action=f'connection.provider.{operation}',
        user_id=user.id if user else None,
        target_type=f'connection:{kind}',
        target_id=int(connection_id) if str(connection_id).isdigit() else None,
        details={
            'connection_id': str(connection_id),
            'operation': operation,
            'success': result.success,
            'error_code': result.error_code,
            'retryable': result.retryable,
        },
    )


# ── Provider SDK ─────────────────────────────────────────────────────────────

@connections_bp.route('/providers', methods=['GET'])
@admin_required
def list_provider_schemas():
    return jsonify({'providers': ConnectionProviderRegistry.schemas()})


@connections_bp.route('/providers/<kind>/validate', methods=['POST'])
@admin_required
def validate_provider_credentials(kind):
    result = ConnectionProviderRegistry.execute(
        kind, 'validate', payload=request.get_json() or {},
        partial=request.args.get('partial', '').lower() == 'true')
    return _provider_response(result)


@connections_bp.route('/providers/<kind>/<connection_id>/health', methods=['GET'])
@admin_required
def provider_health(kind, connection_id):
    result = ConnectionProviderRegistry.execute(
        kind, 'health', ref=_connection_ref(kind, connection_id))
    return _provider_response(result)


@connections_bp.route('/providers/<kind>/<connection_id>/resources', methods=['GET'])
@admin_required
def provider_resources(kind, connection_id):
    result = ConnectionProviderRegistry.execute(
        kind, 'list_resources', ref=_connection_ref(kind, connection_id))
    return _provider_response(result)


@connections_bp.route('/providers/<kind>/<connection_id>/test', methods=['POST'])
@admin_required
def provider_test(kind, connection_id):
    result = ConnectionProviderRegistry.execute(
        kind, 'test', ref=_connection_ref(kind, connection_id))
    _audit_provider_operation(kind, connection_id, 'test', result)
    return _provider_response(result)


@connections_bp.route('/providers/<kind>/<connection_id>/rotate', methods=['POST'])
@admin_required
def provider_rotate(kind, connection_id):
    result = ConnectionProviderRegistry.execute(
        kind, 'rotate', ref=_connection_ref(kind, connection_id),
        payload=request.get_json() or {})
    _audit_provider_operation(kind, connection_id, 'rotate', result)
    return _provider_response(result)


@connections_bp.route('/providers/<kind>/<connection_id>', methods=['DELETE'])
@admin_required
def provider_disconnect(kind, connection_id):
    result = ConnectionProviderRegistry.execute(
        kind, 'disconnect', ref=_connection_ref(kind, connection_id))
    _audit_provider_operation(kind, connection_id, 'disconnect', result)
    return _provider_response(result)


@connections_bp.route('/registries', methods=['GET'])
@auth_required()
def list_registries():
    registries = ContainerRegistryService.list_registries(workspace_id=_workspace_id())
    return jsonify({'registries': [r.to_dict() for r in registries]})


@connections_bp.route('/registries', methods=['POST'])
@admin_required
def create_registry():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    user = get_current_user()
    registry = ContainerRegistryService.create(
        name=name,
        provider=data.get('provider') or 'generic',
        registry_url=data.get('registry_url'),
        username=data.get('username'),
        secret=data.get('secret'),
        workspace_id=_workspace_id(),
        created_by=user.id if user else None,
    )
    return jsonify({'registry': registry.to_dict()}), 201


@connections_bp.route('/registries/<int:registry_id>', methods=['PUT'])
@admin_required
def update_registry(registry_id):
    registry = ContainerRegistryService.get(registry_id)
    if not registry:
        return jsonify({'error': 'Registry not found'}), 404
    data = request.get_json() or {}
    registry = ContainerRegistryService.update(
        registry,
        name=data.get('name'),
        provider=data.get('provider'),
        registry_url=data.get('registry_url'),
        username=data.get('username'),
        secret=data.get('secret'),
    )
    return jsonify({'registry': registry.to_dict()})


@connections_bp.route('/registries/<int:registry_id>', methods=['DELETE'])
@admin_required
def delete_registry(registry_id):
    registry = ContainerRegistryService.get(registry_id)
    if not registry:
        return jsonify({'error': 'Registry not found'}), 404
    result = ConnectionProviderRegistry.execute(
        'registry', 'disconnect', ref=_connection_ref('registry', registry_id))
    _audit_provider_operation('registry', registry_id, 'disconnect', result)
    return _provider_response(result)


@connections_bp.route('/registries/<int:registry_id>/test', methods=['POST'])
@admin_required
def test_registry(registry_id):
    registry = ContainerRegistryService.get(registry_id)
    if not registry:
        return jsonify({'error': 'Registry not found'}), 404
    result = ConnectionProviderRegistry.execute(
        'registry', 'test', ref=_connection_ref('registry', registry_id))
    _audit_provider_operation('registry', registry_id, 'test', result)
    return _provider_response(result)
