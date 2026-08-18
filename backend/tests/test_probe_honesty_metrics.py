"""Probe honesty: unknown must never render as 0, and a real 0 must never
render as unknown.

Plan 75 §A3/A4 — the metrics/fleet sibling of the backup-verify and drill
honesty fixes. The bug class: a probe that could NOT determine a value
reported one anyway — an LXC agent missing a counter rendered as a perfectly
idle box (0% CPU/RAM/disk, 0 B network), a platform without getloadavg
rendered as zero load, a never-probed fleet server exported
``serverkit_server_up 0`` to external alertmanagers, a mobile dashboard
permanently reading 0/0/0 because it called a service method that does not
exist. A zero is indistinguishable from a real reading, so "unknown rendering
as 0" is the same lie a dishonest gauge tells.

The reverse dishonesty is covered too: falsy traps (``x if x else None``,
``int(avg or 0) or None``) that collapsed a real 0.0 reading — an idle CPU, an
empty container fleet — into "no data".

The rule: **a probe answers a value it determined; None when it could not —
never the negative and never 0.**
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import db
from app.models.metrics_history import MetricsHistory
from app.models.server import Server
from app.services.agent_fleet_service import AgentFleetService
from app.services.fleet_monitor_service import FleetMonitorService
from app.services.metrics_history_service import MetricsHistoryService
from app.services.monitoring_service import MonitoringService
from app.services.remote_docker_service import RemoteDockerService
from app.services.server_metrics_service import ServerMetricsService
from app.services.system_service import SystemService


# ---------------------------------------------------------------------------
# #1 — an agent that can't determine a counter is not a perfectly idle box
# ---------------------------------------------------------------------------

def test_agent_payload_missing_keys_normalizes_to_none_not_zero():
    """The bug, stated directly: an LXC agent that omits cpu/memory/disk/
    network/load counters rendered as 0% CPU, 0% RAM, 0% disk, 0 B network."""
    normalized = RemoteDockerService._normalize_agent_metrics({})

    assert normalized['cpu']['percent'] is None
    assert normalized['memory']['ram']['percent'] is None
    assert normalized['memory']['ram']['total'] is None
    assert normalized['memory']['ram']['total_human'] is None
    assert normalized['memory']['swap']['percent'] is None
    assert normalized['disk']['partitions'][0]['percent'] is None
    assert normalized['disk']['partitions'][0]['free'] is None
    assert normalized['network']['io']['bytes_sent'] is None
    assert normalized['network']['io']['bytes_sent_human'] is None
    assert normalized['load_average'] == {'1min': None, '5min': None, '15min': None}


def test_agent_payload_real_zeros_survive_normalization():
    """A determined 0.0 is a reading, not an unknown — it must NOT become None."""
    normalized = RemoteDockerService._normalize_agent_metrics({
        'cpu_percent': 0.0,
        'memory_percent': 0.0,
        'memory_total': 1024,
        'memory_used': 0,
        'disk_percent': 0.0,
        'network_tx': 0,
        'load_avg_1': 0.0,
    })

    assert normalized['cpu']['percent'] == 0.0
    assert normalized['memory']['ram']['percent'] == 0.0
    assert normalized['memory']['ram']['available'] == 1024
    assert normalized['disk']['partitions'][0]['percent'] == 0.0
    assert normalized['network']['io']['bytes_sent'] == 0
    assert normalized['network']['io']['bytes_sent_human'] is not None
    assert normalized['load_average']['1min'] == 0.0


# ---------------------------------------------------------------------------
# #2 — no getloadavg on this platform means "unknown", not "zero load"
# ---------------------------------------------------------------------------

def test_load_average_unsupported_platform_is_none_triplet():
    with patch('app.services.system_service.psutil.getloadavg',
               side_effect=OSError('not supported')):
        load = SystemService.get_load_average()
    assert load == {'1min': None, '5min': None, '15min': None}


# ---------------------------------------------------------------------------
# #3 — an undetermined load must not silently pass the threshold check as 0
# ---------------------------------------------------------------------------

def test_current_metrics_load_is_none_when_getloadavg_fails():
    psutil_mock = Mock()
    psutil_mock.cpu_percent.return_value = 10.0
    psutil_mock.cpu_count.return_value = 4
    psutil_mock.virtual_memory.return_value = SimpleNamespace(
        percent=50.0, used=1, total=2, available=1)
    psutil_mock.disk_usage.return_value = SimpleNamespace(
        percent=40.0, used=1, total=2, free=1)

    with patch('app.services.monitoring_service.psutil', psutil_mock), \
            patch('os.getloadavg', side_effect=OSError('not supported')):
        metrics = MonitoringService.get_current_metrics()

    assert metrics['load_average'] == {'1min': None, '5min': None, '15min': None}


def test_load_threshold_check_is_skipped_when_load_unknown():
    metrics = {
        'cpu': {'percent': 1.0, 'cores': 4},
        'memory': {'percent': 1.0, 'used': 1, 'total': 2, 'available': 1},
        'disk': {'percent': 1.0, 'used': 1, 'total': 2, 'free': 1},
        'load_average': {'1min': None, '5min': None, '15min': None},
    }
    with patch.object(MonitoringService, 'get_current_metrics', return_value=metrics), \
            patch.object(MonitoringService, 'get_thresholds',
                         return_value={'load_average': 0.0}):
        alerts = MonitoringService.check_thresholds()
    assert [a for a in alerts if a['type'] == 'load'] == []


# ---------------------------------------------------------------------------
# #5 — a failed network probe blanks its own section, never the whole broadcast
# ---------------------------------------------------------------------------

def test_net_io_counters_none_yields_none_io_stats_without_raising():
    psutil_mock = Mock()
    psutil_mock.net_io_counters.return_value = None
    psutil_mock.net_if_addrs.return_value = {}
    psutil_mock.net_if_stats.return_value = {}

    with patch('app.services.system_service.psutil', psutil_mock):
        result = SystemService.get_network_metrics()  # must not raise

    assert result['io'] is None
    assert result['interfaces'] == []
    assert 'bytes_sent' not in result  # no fabricated flat zeros


def test_interface_without_stats_reports_unknown_not_down():
    psutil_mock = Mock()
    psutil_mock.net_io_counters.return_value = SimpleNamespace(
        bytes_sent=1, bytes_recv=2, packets_sent=3, packets_recv=4)
    psutil_mock.net_if_addrs.return_value = {'eth0': []}
    psutil_mock.net_if_stats.return_value = {}  # no stats for eth0

    with patch('app.services.system_service.psutil', psutil_mock):
        result = SystemService.get_network_metrics()

    assert result['interfaces'][0]['is_up'] is None
    assert result['interfaces'][0]['speed'] is None


def test_one_failed_section_does_not_blank_the_others():
    with patch.object(SystemService, 'get_network_metrics',
                      side_effect=RuntimeError('net probe exploded')):
        metrics = SystemService.get_all_metrics()  # must not raise

    assert metrics['network'] is None
    assert isinstance(metrics['cpu'], dict)
    assert isinstance(metrics['memory'], dict)
    assert metrics['timestamp'] is not None


# ---------------------------------------------------------------------------
# #8 — an empty history window has no average
# ---------------------------------------------------------------------------

def test_empty_history_window_summary_is_none_not_zero(app):
    history = MetricsHistoryService.get_history('1h')
    assert history['points'] == 0
    assert history['summary'] == {
        'cpu_avg': None, 'memory_avg': None, 'disk_avg': None,
    }


# ---------------------------------------------------------------------------
# #9 — falsy traps: a real 0.0 average is data, not "no data"
# ---------------------------------------------------------------------------

def test_average_records_preserves_real_zero_averages():
    from app.models.server import ServerMetrics

    def _rec(**values):
        rec = ServerMetrics()
        rec.server_id = 'srv-1'
        rec.timestamp = datetime(2026, 8, 18)
        for key, value in values.items():
            setattr(rec, key, value)
        return rec

    records = [
        _rec(cpu_percent=0.0, memory_used=0, container_running=0, container_count=0),
        _rec(cpu_percent=0.0, memory_used=0, container_running=0, container_count=0),
    ]
    avg = ServerMetricsService._average_records(records)

    assert avg.cpu_percent == 0.0
    assert avg.memory_used == 0       # int(0 or 0) or None used to eat this
    assert avg.container_running == 0
    assert avg.container_count == 0


def test_average_records_all_none_stays_none():
    from app.models.server import ServerMetrics

    records = [ServerMetrics(server_id='srv-1', timestamp=datetime(2026, 8, 18)),
               ServerMetrics(server_id='srv-1', timestamp=datetime(2026, 8, 18))]
    avg = ServerMetricsService._average_records(records)
    assert avg.cpu_percent is None
    assert avg.memory_used is None


def test_metrics_history_to_dict_preserves_real_zero_load(app):
    rec = MetricsHistory(
        timestamp=datetime(2026, 8, 18), level='minute',
        cpu_percent=0.0, cpu_percent_min=0.0, cpu_percent_max=0.0,
        memory_percent=1.0, memory_used_bytes=1, memory_total_bytes=2,
        disk_percent=1.0, disk_used_bytes=1, disk_total_bytes=2,
        load_1m=0.0, load_5m=0.0, load_15m=0.0,
    )
    d = rec.to_dict()
    assert d['cpu']['min'] == 0.0
    assert d['load'] == {'1m': 0.0, '5m': 0.0, '15m': 0.0}


# ---------------------------------------------------------------------------
# #10 — mobile dashboard called a service method that does not exist
# ---------------------------------------------------------------------------

def test_mobile_summary_returns_real_metrics(client, auth_headers):
    live = {
        'cpu': {'percent': 42.5, 'cores': 4},
        'memory': {'percent': 61.0, 'used': 1, 'total': 2, 'available': 1},
        'disk': {'percent': 33.3, 'used': 1, 'total': 2, 'free': 1},
        'load_average': {'1min': 0.5, '5min': 0.4, '15min': 0.3},
    }
    with patch.object(MonitoringService, 'get_current_metrics', return_value=live):
        resp = client.get('/api/v1/mobile/summary', headers=auth_headers)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['metrics'] == {'cpu': 42.5, 'memory': 61.0, 'disk': 33.3}


def test_mobile_summary_probe_failure_is_none_not_zero(client, auth_headers):
    with patch.object(MonitoringService, 'get_current_metrics',
                      side_effect=RuntimeError('psutil exploded')):
        resp = client.get('/api/v1/mobile/summary', headers=auth_headers)

    assert resp.status_code == 200
    assert resp.get_json()['metrics'] == {'cpu': None, 'memory': None, 'disk': None}


def test_mobile_view_stats_quick_action_no_longer_500s(client, auth_headers):
    with patch.object(MonitoringService, 'get_current_metrics',
                      return_value={'cpu': {'percent': 1.0}}):
        resp = client.post('/api/v1/mobile/quick-actions/view_stats',
                           json={}, headers=auth_headers)

    assert resp.status_code == 200
    assert resp.get_json()['result'] == {'cpu': {'percent': 1.0}}


# ---------------------------------------------------------------------------
# #13 — no sessions is not "0.0 ms latency"; no commands is not "100% success"
# ---------------------------------------------------------------------------

def test_fleet_health_without_observations_reports_none_kpis(app):
    health = AgentFleetService().get_fleet_health()
    assert health['total_servers'] == 0
    assert health['avg_heartbeat_latency'] is None
    assert health['command_success_rate'] is None


# ---------------------------------------------------------------------------
# #15 — a never-probed server must not export serverkit_server_up 0
# ---------------------------------------------------------------------------

def test_prometheus_up_series_skips_undetermined_servers(app):
    never_probed = Server(name='pending-box', status='pending', last_seen=None)
    seen_offline = Server(name='offline-box', status='offline',
                          last_seen=datetime(2026, 8, 18))
    seen_online = Server(name='online-box', status='online',
                         last_seen=datetime(2026, 8, 18))
    db.session.add_all([never_probed, seen_offline, seen_online])
    db.session.commit()

    output = FleetMonitorService.get_prometheus_metrics()

    up_lines = [line for line in output.splitlines()
                if line.startswith('serverkit_server_up{')]
    assert not any('pending-box' in line for line in up_lines)
    assert any('offline-box' in line and line.endswith(' 0') for line in up_lines)
    assert any('online-box' in line and line.endswith(' 1') for line in up_lines)


def test_prometheus_up_series_skips_never_seen_even_if_marked_offline(app):
    """last_seen NULL means connectivity was never determined — a manual
    status flip is not a probe result."""
    ghost = Server(name='ghost-box', status='offline', last_seen=None)
    db.session.add(ghost)
    db.session.commit()

    output = FleetMonitorService.get_prometheus_metrics()
    assert not any('ghost-box' in line for line in output.splitlines()
                   if line.startswith('serverkit_server_up{'))
