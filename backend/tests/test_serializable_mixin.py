"""Plan 77 B2 gate — SerializableMixin parity, key for key.

For every converted model the frozen set below is the EXACT key list its
hand-written to_dict produced before conversion. The mixin must emit every
one of them, may add at most the Timestamp pair (models that already carried
created_at/updated_at columns the old dict simply forgot), and must never
leak an *_encrypted column. Datetimes must come out isoformat, matching the
deleted `x.isoformat() if x else None` ternaries.
"""
from datetime import datetime

import pytest

from app.models.mixins import SerializableMixin

# ClassName -> the old hand-written to_dict's key set (captured pre-conversion).
EXPECTED = {
    'AgentSession': {'avg_latency_ms', 'connected_at', 'disconnect_reason', 'disconnected_at', 'heartbeat_latency_ms', 'id', 'ip_address', 'is_active', 'last_heartbeat', 'server_id'},
    'ApiUsageLog': {'api_key_id', 'blueprint', 'created_at', 'endpoint', 'id', 'ip_address', 'method', 'response_time_ms', 'status_code', 'user_id'},
    'ApiUsageSummary': {'api_key_id', 'avg_response_time_ms', 'client_error_count', 'endpoint', 'id', 'max_response_time_ms', 'period_start', 'server_error_count', 'success_count', 'total_requests', 'user_id'},
    'CfOpsChange': {'action', 'created_at', 'dns_provider_config_id', 'error', 'id', 'product', 'provider_zone_id', 'result', 'target', 'user_id'},
    'CloudSnapshot': {'created_at', 'external_id', 'id', 'name', 'server_id', 'size_gb', 'status'},
    'CloudflareTunnel': {'account_id', 'created_at', 'dns_provider_config_id', 'id', 'name', 'tunnel_id'},
    'CronRun': {'created_at', 'duration_seconds', 'exit_code', 'finished_at', 'id', 'job_id', 'output_tail', 'started_at', 'status'},
    'DNSRecord': {'content', 'created_at', 'id', 'name', 'priority', 'provider_record_id', 'proxied', 'record_type', 'ttl', 'zone_id'},
    'DnsChange': {'action', 'before_json', 'content', 'created_at', 'dns_provider_config_id', 'error', 'id', 'name', 'provider', 'provider_record_id', 'provider_zone_id', 'record_type', 'result', 'source'},
    'HealthCheck': {'checked_at', 'component_id', 'error', 'id', 'response_time', 'status', 'status_code'},
    'ImageUpdateCheck': {'application_id', 'checked_at', 'current_digest', 'error_message', 'id', 'image_ref', 'latest_digest', 'status', 'update_available'},
    'ManagedDnsRecord': {'app_id', 'content', 'created_at', 'id', 'name', 'priority', 'provider', 'provider_record_id', 'provider_zone_id', 'proxied', 'record_type', 'source', 'ttl', 'updated_at'},
    'ResourceTag': {'created_at', 'id', 'resource_id', 'resource_type', 'tag'},
    'ServerCommand': {'command_data', 'command_type', 'completed_at', 'created_at', 'error', 'exit_code', 'id', 'max_retries', 'queued', 'result', 'retry_count', 'server_id', 'started_at', 'status', 'user_id'},
    'ServerMetrics': {'container_count', 'container_running', 'cpu_percent', 'disk_percent', 'disk_used', 'extra', 'id', 'memory_percent', 'memory_used', 'network_rx', 'network_rx_rate', 'network_tx', 'network_tx_rate', 'server_id', 'timestamp'},
    'SharedVariableGroupAttachment': {'created_at', 'group_id', 'id', 'resource_id', 'resource_type'},
    'SourceConnection': {'avatar_url', 'created_at', 'display_name', 'id', 'last_used_at', 'provider', 'provider_account_id', 'provider_username', 'scope', 'updated_at'},
    'StatusIncidentUpdate': {'body', 'created_at', 'id', 'incident_id', 'status'},
    'WordPressSitePlugin': {'custom_plugin_id', 'id', 'installed_version', 'status', 'updated_at', 'wordpress_site_id'},
    'WordPressVulnerability': {'advisory_id', 'cvss_score', 'detected_at', 'fixed_in', 'id', 'installed_version', 'name', 'reference_url', 'severity', 'site_id', 'slug', 'source', 'title'},
}

ALLOWED_ADDITIONS = {'created_at', 'updated_at'}


def _converted_classes():
    from app.models.api_usage import ApiUsageLog, ApiUsageSummary
    from app.models.cf_ops_change import CfOpsChange
    from app.models.cloud_server import CloudSnapshot
    from app.models.cloudflare_tunnel import CloudflareTunnel
    from app.models.cron_run import CronRun
    from app.models.dns_change import DnsChange
    from app.models.dns_zone import DNSRecord
    from app.models.image_update import ImageUpdateCheck
    from app.models.managed_dns_record import ManagedDnsRecord
    from app.models.server import AgentSession, ServerCommand, ServerMetrics
    from app.models.shared_resource import ResourceTag, SharedVariableGroupAttachment
    from app.models.source_connection import SourceConnection
    from app.models.status_page import HealthCheck, StatusIncidentUpdate
    from app.models.wordpress_custom_plugin import WordPressSitePlugin
    from app.models.wordpress_site import WordPressVulnerability
    return [ApiUsageLog, ApiUsageSummary, CfOpsChange, CloudSnapshot,
            CloudflareTunnel, CronRun, DnsChange, DNSRecord, ImageUpdateCheck,
            ManagedDnsRecord, AgentSession, ServerCommand, ServerMetrics,
            ResourceTag, SharedVariableGroupAttachment, SourceConnection,
            HealthCheck, StatusIncidentUpdate, WordPressSitePlugin,
            WordPressVulnerability]


def _synthetic(column):
    kind = type(column.type).__name__.lower()
    if 'datetime' in kind:
        return datetime(2026, 1, 2, 3, 4, 5)
    if 'bool' in kind:
        return True
    if 'integer' in kind or 'biginteger' in kind:
        return 7
    if 'float' in kind or 'numeric' in kind:
        return 1.5
    return 'x'


def _instance(cls):
    # In-memory only — never added to a session; we only exercise to_dict().
    obj = cls(**{c.name: _synthetic(c) for c in cls.__table__.columns})
    return obj


@pytest.mark.parametrize('cls', _converted_classes(), ids=lambda c: c.__name__)
def test_parity_key_for_key(app, cls):
    assert issubclass(cls, SerializableMixin)
    obj = _instance(cls)
    d = obj.to_dict()

    expected = EXPECTED[cls.__name__]
    if expected is not None:
        missing = expected - set(d)
        assert not missing, f'{cls.__name__} lost keys: {sorted(missing)}'
        added = set(d) - expected
        assert added <= ALLOWED_ADDITIONS, f'{cls.__name__} added: {sorted(added)}'

    # every column that should be excluded stays out
    for name in getattr(cls, '__serialize_exclude__', ()):
        assert name not in d, f'{cls.__name__} leaked excluded column {name}'
    for column in cls.__table__.columns:
        if column.name.endswith('_encrypted'):
            assert column.name not in d, f'{cls.__name__} leaked {column.name}'

    # datetimes serialize isoformat, like the deleted ternaries did
    for column in cls.__table__.columns:
        if 'datetime' in type(column.type).__name__.lower() and column.name in d:
            assert d[column.name] == '2026-01-02T03:04:05', (cls.__name__, column.name)


def test_cron_run_extra_keeps_duration(app):
    from app.models.cron_run import CronRun
    run = CronRun(started_at=datetime(2026, 1, 1, 0, 0, 0),
                  finished_at=datetime(2026, 1, 1, 0, 0, 30))
    d = run.to_dict()
    assert d['duration_seconds'] == 30
