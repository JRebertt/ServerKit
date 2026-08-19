"""Tests for the fleet health doctor (fleet_doctor_service).

Covers the composed-vs-probe negotiation, the panel-side DNS-vs-IP check, and
that a sweep records one FleetDoctorResult row per (server_id, check_key).
Agent responses are faked via monkeypatch — no real agent, no real network.
"""
import pytest

from app.services import agent_registry as agent_registry_mod
from app.services import fleet_doctor_service
from app.services.fleet_doctor_service import FleetDoctorService

registry = agent_registry_mod.agent_registry


@pytest.fixture
def server(app):
    from app import db
    from factories import make_server
    return make_server(db, hostname='box', ip_address='203.0.113.10')


def by_key(rows):
    return {r['key']: r for r in rows}


# --------------------------------------------------------------------------- #
# Per-server remote probe composition
# --------------------------------------------------------------------------- #

def test_offline_server_yields_offline_status(app, server, monkeypatch):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: False)
    res = FleetDoctorService._compose_server_checks(server.id, 5.0)
    assert res['status'] == 'offline'
    assert res['checks'] == []


def test_agent_without_systemd_is_unsupported(app, server, monkeypatch):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(registry, 'get_capabilities', lambda sid: {'docker': True})
    res = FleetDoctorService._compose_server_checks(server.id, 5.0)
    assert res['status'] == 'unsupported'


def test_probe_path_builds_service_and_disk_rows(app, server, monkeypatch):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(registry, 'get_capabilities',
                        lambda sid: {'doctor.probe': True, 'systemd.restart': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        assert action == 'doctor:probe'
        assert params == {'units': ['nginx', 'docker']}
        return {'success': True, 'data': {
            'units': {'nginx': {'active': True}, 'docker': {'active': False}},
            'disk': {'percent': 96.0, 'path': '/'},
        }}

    monkeypatch.setattr(registry, 'send_command', _send)
    res = FleetDoctorService._compose_server_checks(server.id, 5.0)
    assert res['status'] == 'ok'
    checks = by_key(res['checks'])
    assert checks['service.nginx']['status'] == 'ok'
    docker = checks['service.docker']
    assert docker['status'] == 'fail'
    assert docker['repairable'] is True
    assert docker['repair_ref'] == {'kind': 'fleet.service',
                                    'server_id': server.id, 'name': 'docker'}
    # 96% used -> 4% free -> below the 5% fail threshold.
    assert checks['disk.headroom']['status'] == 'fail'


def test_probe_error_falls_back_to_composed_v1(app, server, monkeypatch):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(registry, 'get_capabilities',
                        lambda sid: {'doctor.probe': True, 'systemd': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        if action == 'doctor:probe':
            return {'success': False, 'error': 'probe not implemented'}
        if action == 'systemd:status':
            return {'success': True, 'data': {'active': params['unit'] == 'nginx'}}
        if action == 'system:metrics':
            return {'success': True, 'data': {'disk_percent': 40.0}}
        raise AssertionError(f'unexpected action {action}')

    monkeypatch.setattr(registry, 'send_command', _send)
    res = FleetDoctorService._compose_server_checks(server.id, 5.0)
    assert res['status'] == 'ok'
    checks = by_key(res['checks'])
    assert checks['service.nginx']['status'] == 'ok'
    assert checks['service.docker']['status'] == 'fail'
    assert checks['disk.headroom']['status'] == 'ok'  # 60% free


def test_service_down_not_repairable_without_restart_capability(app, server, monkeypatch):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(registry, 'get_capabilities', lambda sid: {'systemd': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        if action == 'systemd:status':
            return {'success': True, 'data': {'active': False}}
        return {'success': True, 'data': {}}

    monkeypatch.setattr(registry, 'send_command', _send)
    res = FleetDoctorService._compose_server_checks(server.id, 5.0)
    checks = by_key(res['checks'])
    assert checks['service.nginx']['status'] == 'fail'
    assert checks['service.nginx']['repairable'] is False
    assert checks['service.nginx']['repair_ref'] is None


# --------------------------------------------------------------------------- #
# DNS-vs-IP (panel-side)
# --------------------------------------------------------------------------- #

def test_dns_ok_when_hostname_points_at_server(app, server, monkeypatch):
    monkeypatch.setattr(fleet_doctor_service, '_resolve_host_ips',
                        lambda host: ['203.0.113.10'])
    from app import db
    server.hostname = 'box.example.com'
    db.session.commit()
    row = FleetDoctorService._dns_check_for_server(server)
    assert row['key'] == 'dns.hostname'
    assert row['status'] == 'ok'


def test_dns_warn_on_mismatch(app, server, monkeypatch):
    monkeypatch.setattr(fleet_doctor_service, '_resolve_host_ips',
                        lambda host: ['198.51.100.9'])
    from app import db
    server.hostname = 'box.example.com'
    db.session.commit()
    row = FleetDoctorService._dns_check_for_server(server)
    assert row['status'] == 'warn'
    assert '198.51.100.9' in row['detail']


def test_dns_fail_when_unresolved(app, server, monkeypatch):
    import socket

    def _boom(host):
        raise socket.gaierror(-2, 'name resolution failure')

    monkeypatch.setattr(fleet_doctor_service, '_resolve_host_ips', _boom)
    from app import db
    server.hostname = 'gone.example.com'
    db.session.commit()
    row = FleetDoctorService._dns_check_for_server(server)
    assert row['status'] == 'fail'


def test_dns_skips_bare_hostname(app, server):
    # default fixture hostname is 'box' (no dot) -> not a public name.
    row = FleetDoctorService._dns_check_for_server(server)
    assert row['status'] == 'ok'
    assert 'No public hostname' in row['detail']


# --------------------------------------------------------------------------- #
# Persistence + full sweep
# --------------------------------------------------------------------------- #

def test_persist_upserts_one_row_per_check_key(app, server):
    from app.models.fleet_doctor_result import FleetDoctorResult
    from app.services.fleet_doctor_service import _row

    FleetDoctorService._persist(server.id, [
        _row('service.nginx', 'nginx service', 'fail', 'Not running.',
             repairable=True, repair_ref={'kind': 'fleet.service',
                                          'server_id': server.id, 'name': 'nginx'}),
    ])
    # Second run flips nginx to ok — must update the same row, not add one.
    FleetDoctorService._persist(server.id, [
        _row('service.nginx', 'nginx service', 'ok', 'Running.'),
    ])

    rows = FleetDoctorResult.query.filter_by(server_id=server.id).all()
    assert len(rows) == 1
    assert rows[0].status == 'ok'
    assert rows[0].repairable is False


def test_run_fleet_doctor_records_rows_for_each_server(app, server, monkeypatch):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(registry, 'get_capabilities',
                        lambda sid: {'doctor.probe': True, 'systemd.restart': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        return {'success': True, 'data': {
            'units': {'nginx': {'active': True}, 'docker': {'active': True}},
            'disk': {'percent': 20.0},
        }}

    monkeypatch.setattr(registry, 'send_command', _send)

    summary = FleetDoctorService.run_fleet_doctor()
    assert summary['servers'] == 1
    assert summary['checks_written'] >= 3  # 2 services + disk + dns

    results = FleetDoctorService.results_for_server(server.id)
    keys = {r['check_key'] for r in results}
    assert {'service.nginx', 'service.docker', 'disk.headroom',
            'dns.hostname'} <= keys
