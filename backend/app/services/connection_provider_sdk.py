"""Contract and dispatcher for external-account providers.

Provider implementations may keep their existing persistence model, but every
operation crossing the Connections boundary uses the same result envelope.
This keeps provider-specific HTTP clients and credential shapes out of the API
layer while giving the UI stable capability, health, retry, and rate-limit
metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Type


OPERATIONS = (
    'validate',
    'test',
    'list_resources',
    'health',
    'rotate',
    'disconnect',
)


class ProviderOperationError(Exception):
    """Expected provider failure with transport-neutral recovery metadata."""

    def __init__(self, message, *, code='provider_error', retryable=False,
                 retry_after=None, rate_limit=None, details=None):
        super().__init__(message)
        self.code = code
        self.retryable = bool(retryable)
        self.retry_after = retry_after
        self.rate_limit = rate_limit or {}
        self.details = details or {}


@dataclass(frozen=True)
class ConnectionRef:
    kind: str
    connection_id: Any
    provider: Optional[str] = None
    user_id: Optional[int] = None
    workspace_id: Optional[int] = None


@dataclass
class ProviderResult:
    operation: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    retryable: bool = False
    retry_after: Optional[int] = None
    rate_limit: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self):
        payload = asdict(self)
        if not self.error:
            payload.pop('error')
            payload.pop('error_code')
        if not self.retry_after:
            payload.pop('retry_after')
        if not self.rate_limit:
            payload.pop('rate_limit')
        if not self.details:
            payload.pop('details')
        return payload


class ConnectionProvider:
    """Base provider contract.

    A provider opts into an operation by overriding its method. Unsupported
    operations remain visible in the schema with ``supported: false`` instead
    of failing later with an ad-hoc response.
    """

    kind = None
    display_name = None
    credential_schema = {}
    permission_scopes = ()
    max_attempts = 1
    retry_operations = ('test', 'list_resources', 'health')

    @classmethod
    def capabilities(cls):
        return {
            operation: getattr(cls, operation) is not getattr(ConnectionProvider, operation)
            for operation in OPERATIONS
        }

    @classmethod
    def schema(cls):
        return {
            'kind': cls.kind,
            'display_name': cls.display_name or cls.kind,
            'credentials': cls.credential_schema,
            'permission_scopes': list(cls.permission_scopes),
            'capabilities': cls.capabilities(),
            'retry_policy': {
                'max_attempts': max(1, int(cls.max_attempts)),
                'operations': list(cls.retry_operations),
                'honors_retry_after': True,
            },
        }

    def validate(self, payload, *, partial=False):
        raise NotImplementedError

    def test(self, ref):
        raise NotImplementedError

    def list_resources(self, ref):
        raise NotImplementedError

    def health(self, ref):
        raise NotImplementedError

    def rotate(self, ref, payload):
        raise NotImplementedError

    def disconnect(self, ref):
        raise NotImplementedError


class ConnectionProviderRegistry:
    """Registers provider adapters and normalizes every operation result."""

    _providers: Dict[str, Type[ConnectionProvider]] = {}

    @classmethod
    def register(cls, provider_cls):
        kind = getattr(provider_cls, 'kind', None)
        if not isinstance(kind, str) or not kind.strip():
            raise TypeError('Connection providers require a non-empty kind')
        if kind in cls._providers and cls._providers[kind] is not provider_cls:
            raise ValueError(f"Connection provider '{kind}' is already registered")
        cls._providers[kind] = provider_cls
        return provider_cls

    @classmethod
    def get(cls, kind):
        provider_cls = cls._providers.get(kind)
        if not provider_cls:
            raise ProviderOperationError(
                f"Unknown connection provider kind: {kind}", code='unknown_provider')
        return provider_cls()

    @classmethod
    def schemas(cls):
        return [cls._providers[kind].schema() for kind in sorted(cls._providers)]

    @classmethod
    def execute(cls, kind, operation, *, ref=None, payload=None, partial=False):
        if operation not in OPERATIONS:
            return ProviderResult(
                operation=operation, success=False,
                error=f'Unknown provider operation: {operation}',
                error_code='unknown_operation',
            )
        try:
            provider = cls.get(kind)
            if not provider.capabilities()[operation]:
                raise ProviderOperationError(
                    f"{provider.display_name or kind} does not support {operation}",
                    code='unsupported_operation')

            attempts = 0
            while True:
                attempts += 1
                try:
                    if operation == 'validate':
                        data = provider.validate(payload or {}, partial=partial)
                    elif operation == 'rotate':
                        data = provider.rotate(ref, payload or {})
                    else:
                        data = getattr(provider, operation)(ref)
                    break
                except ProviderOperationError as exc:
                    can_retry = (
                        exc.retryable
                        and exc.retry_after is None
                        and operation in provider.retry_operations
                        and attempts < max(1, int(provider.max_attempts))
                    )
                    if not can_retry:
                        exc.details.setdefault('attempts', attempts)
                        raise

            if isinstance(data, ProviderResult):
                return data
            result = ProviderResult(operation=operation, success=True, data=data or {})
            if attempts > 1:
                result.details['attempts'] = attempts
            return result
        except ProviderOperationError as exc:
            return ProviderResult(
                operation=operation, success=False, error=str(exc),
                error_code=exc.code, retryable=exc.retryable,
                retry_after=exc.retry_after, rate_limit=exc.rate_limit,
                details=exc.details,
            )
        except NotImplementedError:
            return ProviderResult(
                operation=operation, success=False,
                error=f'{kind} does not support {operation}',
                error_code='unsupported_operation',
            )
        except Exception as exc:
            return ProviderResult(
                operation=operation, success=False, error=str(exc),
                error_code='provider_error',
            )


def register_providers(providers: Iterable[Type[ConnectionProvider]]):
    """Small helper for extension/provider packages registering in one call."""
    for provider in providers:
        ConnectionProviderRegistry.register(provider)
