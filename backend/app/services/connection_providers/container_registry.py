"""Connection-provider adapter for private container registries."""

from datetime import datetime

from app.models.container_registry import ContainerRegistry
from app.services.connection_provider_sdk import (
    ConnectionProvider,
    ConnectionProviderRegistry,
    ProviderOperationError,
)
from app.services.container_registry_service import ContainerRegistryService


@ConnectionProviderRegistry.register
class ContainerRegistryProvider(ConnectionProvider):
    kind = 'registry'
    display_name = 'Container registry'
    permission_scopes = ('image:pull',)
    credential_schema = {
        'type': 'object',
        'required': ['secret'],
        'properties': {
            'secret': {'type': 'string', 'secret': True, 'minLength': 1},
        },
        'additionalProperties': False,
    }

    @staticmethod
    def _get(ref):
        if ref is None:
            raise ProviderOperationError('Connection reference is required', code='invalid_reference')
        registry = ContainerRegistryService.get(ref.connection_id)
        if not registry:
            raise ProviderOperationError('Registry not found', code='not_found')
        if ref.workspace_id is not None and registry.workspace_id not in (None, ref.workspace_id):
            raise ProviderOperationError('Registry not found', code='not_found')
        return registry

    def validate(self, payload, *, partial=False):
        errors = {}
        secret = payload.get('secret')
        if not partial and not isinstance(secret, str):
            errors['secret'] = 'secret is required'
        elif secret is not None and (not isinstance(secret, str) or not secret.strip()):
            errors['secret'] = 'secret must be a non-empty string'
        extra = sorted(set(payload) - {'secret'})
        if extra:
            errors['_schema'] = f"unknown credential fields: {', '.join(extra)}"
        if errors:
            raise ProviderOperationError(
                'Credential validation failed', code='validation_error',
                details={'field_errors': errors})
        return {'valid': True}

    def test(self, ref):
        registry = self._get(ref)
        result = ContainerRegistryService.test_connection(registry)
        if not result.get('success'):
            raise ProviderOperationError(
                result.get('error') or 'Registry login failed',
                code=result.get('error_code') or 'connection_test_failed',
                retryable=bool(result.get('retryable')),
                retry_after=result.get('retry_after'),
                rate_limit=result.get('rate_limit'),
            )
        return {'message': f'Logged in to {registry.login_host()}', 'health': 'healthy'}

    def health(self, ref):
        registry = self._get(ref)
        if registry.last_test_ok is True:
            status = 'healthy'
        elif registry.last_test_ok is False:
            status = 'unhealthy'
        else:
            status = 'unknown'
        return {
            'status': status,
            'checked_at': registry.last_tested_at.isoformat() if registry.last_tested_at else None,
            'message': registry.last_test_error,
            'configured': bool(registry.secret_encrypted and registry.login_username()),
        }

    def rotate(self, ref, payload):
        self.validate(payload)
        registry = self._get(ref)
        result = ContainerRegistryService.rotate_secret(registry, payload['secret'])
        if not result.get('success'):
            raise ProviderOperationError(
                result.get('error') or 'New credential failed validation',
                code=result.get('error_code') or 'rotation_test_failed',
                retryable=bool(result.get('retryable')),
                retry_after=result.get('retry_after'),
                rate_limit=result.get('rate_limit'),
            )
        return {
            'rotated_at': datetime.utcnow().isoformat(),
            'health': 'healthy',
        }

    def disconnect(self, ref):
        registry = self._get(ref)
        ContainerRegistryService.delete(registry)
        return {'disconnected': True, 'connection_id': ref.connection_id}
