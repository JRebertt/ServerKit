"""Provider SDK contract tests independent of any credential model."""

import pytest

from app.services.connection_provider_sdk import (
    ConnectionProvider,
    ConnectionProviderRegistry,
    ConnectionRef,
    ProviderOperationError,
)


@pytest.fixture
def isolated_registry(monkeypatch):
    monkeypatch.setattr(ConnectionProviderRegistry, '_providers', {})
    return ConnectionProviderRegistry


def test_registration_requires_a_kind(isolated_registry):
    class MissingKind(ConnectionProvider):
        pass

    with pytest.raises(TypeError):
        isolated_registry.register(MissingKind)


def test_capabilities_and_schema_are_derived_from_overrides(isolated_registry):
    @isolated_registry.register
    class Minimal(ConnectionProvider):
        kind = 'minimal'
        display_name = 'Minimal provider'
        credential_schema = {'type': 'object'}

        def health(self, ref):
            return {'status': 'healthy'}

    schema = isolated_registry.schemas()[0]
    assert schema['capabilities']['health'] is True
    assert schema['capabilities']['rotate'] is False
    assert schema['retry_policy']['honors_retry_after'] is True

    unsupported = isolated_registry.execute(
        'minimal', 'rotate', ref=ConnectionRef('minimal', 'one'), payload={})
    assert unsupported.success is False
    assert unsupported.error_code == 'unsupported_operation'


def test_retryable_reads_use_bounded_provider_policy(isolated_registry):
    @isolated_registry.register
    class Flaky(ConnectionProvider):
        kind = 'flaky'
        max_attempts = 3

        def __init__(self):
            self.calls = 0

        def health(self, ref):
            self.calls += 1
            if self.calls < 3:
                raise ProviderOperationError('temporary', retryable=True)
            return {'status': 'healthy'}

    result = isolated_registry.execute(
        'flaky', 'health', ref=ConnectionRef('flaky', 'one'))
    assert result.success is True
    assert result.details['attempts'] == 3


def test_retry_after_is_returned_without_blocking(isolated_registry):
    @isolated_registry.register
    class Limited(ConnectionProvider):
        kind = 'limited'
        max_attempts = 3

        def test(self, ref):
            raise ProviderOperationError(
                'rate limited', code='rate_limited', retryable=True,
                retry_after=60, rate_limit={'remaining': 0})

    result = isolated_registry.execute(
        'limited', 'test', ref=ConnectionRef('limited', 'one'))
    assert result.success is False
    assert result.error_code == 'rate_limited'
    assert result.retry_after == 60
    assert result.rate_limit == {'remaining': 0}
    assert result.details['attempts'] == 1
