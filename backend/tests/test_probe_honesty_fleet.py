"""A probe that could not answer must never render as a healthy (or guilty)
answer — fleet doctor edition.

Plan 75 §A2. The bug class, on the agent-fleet side of the same audit:

* **Default-to-ok persistence.** `_persist` wrote
  ``c.get('status') or STATUS_OK`` — a check dict missing its status persisted
  as a green row — and `fleet_report` read a missing status back as ``'ok'``.
  The summarising boundary could not render "couldn't check" at all.
* **Silence read as failure.** A successful probe whose payload lacked the
  unit's ``active`` key was coerced with ``bool(None)`` → fail "Not running.",
  persisted and counted and marked repairable. A failed metrics probe (or an
  unparseable ``disk_percent``) produced NO disk row — the check vanished.
* **A failed sweep left stale health standing.** When the fan-out returned
  ``failed``/``timeout`` for a server, zero rows were written, so the per-server
  view kept showing the previous run's (possibly all-ok) rows as current.
* **Resolver outage impersonating NXDOMAIN** — the same panel-side DNS bug as
  the host doctor: any ``getaddrinfo`` exception read as "does not resolve".

The rule: **`ok` must be positively earned** — and `fail` must be positively
earned too. An agent that didn't answer a question has not answered "no".
"""
import socket

import pytest

from app import db
from app.services import agent_registry as agent_registry_mod
from app.services import fleet_doctor_service
from app.services.fleet_doctor_service import FleetDoctorService, _row

registry = agent_registry_mod.agent_registry


@pytest.fixture
def server(app):
    from app.models.server import Server
    row = Server(name='box1', hostname='box', ip_address='203.0.113.10')
    db.session.add(row)
    db.session.commit()
    return row


def by_key(rows):
    return {r['key']: r for r in rows}


def _connected(monkeypatch, caps):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(registry, 'get_capabilities', lambda sid: caps)


# --------------------------------------------------------------------------- #
# Finding 12: a check dict with no status persists as error, never ok
# --------------------------------------------------------------------------- #

def test_persist_defaults_a_missing_status_to_error(app, server):
    """The bug, stated directly: `c.get('status') or STATUS_OK`."""
    from app.models.fleet_doctor_result import FleetDoctorResult

    written = FleetDoctorService._persist(server.id, [
        {'key': 'service.nginx', 'title': 'nginx service',
         'detail': 'status unknown', 'repairable': False, 'repair_ref': None},
    ])

    assert written == 1
    row = FleetDoctorResult.query.filter_by(
        server_id=server.id, check_key='service.nginx').one()
    assert row.status == FleetDoctorResult.STATUS_ERROR


# --------------------------------------------------------------------------- #
# Finding 13: a row with no status counts as error in the report, never ok
# --------------------------------------------------------------------------- #

def test_fleet_report_counts_a_missing_status_as_error(app, server, monkeypatch):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(FleetDoctorService, 'all_results', classmethod(lambda cls: {
        server.id: [{'check_key': 'service.nginx', 'status': None,
                     'title': 'nginx service', 'detail': None,
                     'repairable': False, 'repair_ref': None, 'ran_at': None}],
    }))

    report = FleetDoctorService.fleet_report()

    entry = report['servers'][0]
    assert entry['counts']['error'] == 1
    assert entry['counts']['ok'] == 0


# --------------------------------------------------------------------------- #
# Finding 14: a probe that didn't report a unit state is error, not fail
# --------------------------------------------------------------------------- #

def test_probe_payload_missing_active_is_an_error_row(app, server, monkeypatch):
    """The bug: `bool(info.get('active'))` — a missing key coerced to False,
    rendered fail 'Not running.' and marked repairable."""
    _connected(monkeypatch, {'doctor.probe': True, 'systemd.restart': True})
    monkeypatch.setattr(
        registry, 'send_command',
        lambda server_id, action, params, timeout=None, user_id=None: {
            'success': True,
            'data': {'units': {'nginx': {}, 'docker': {'active': True}},
                     'disk': {'percent': 50.0}},
        })

    res = FleetDoctorService._compose_server_checks(server.id, 5.0)

    checks = by_key(res['checks'])
    nginx = checks['service.nginx']
    assert nginx['status'] == 'error'
    assert 'did not report a state' in nginx['detail']
    assert nginx['repairable'] is False
    # A reported state keeps its meaning.
    assert checks['service.docker']['status'] == 'ok'


def test_compose_v1_missing_active_is_an_error_row(app, server, monkeypatch):
    _connected(monkeypatch, {'systemd': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        if action == 'systemd:status':
            return {'success': True, 'data': {}}  # no 'active' key
        return {'success': True, 'data': {'disk_percent': 50.0}}

    monkeypatch.setattr(registry, 'send_command', _send)

    res = FleetDoctorService._compose_server_checks(server.id, 5.0)

    checks = by_key(res['checks'])
    for unit in ('nginx', 'docker'):
        row = checks[f'service.{unit}']
        assert row['status'] == 'error'
        assert 'did not report a state' in row['detail']
        assert row['repairable'] is False


def test_compose_v1_reported_inactive_is_still_a_fail(app, server, monkeypatch):
    """The honest negative keeps its teeth: the agent RAN the probe and said
    the unit is down."""
    _connected(monkeypatch, {'systemd': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        if action == 'systemd:status':
            return {'success': True, 'data': {'active': False}}
        return {'success': True, 'data': {'disk_percent': 50.0}}

    monkeypatch.setattr(registry, 'send_command', _send)

    res = FleetDoctorService._compose_server_checks(server.id, 5.0)

    checks = by_key(res['checks'])
    assert checks['service.nginx']['status'] == 'fail'
    assert checks['service.nginx']['detail'] == 'Not running.'


# --------------------------------------------------------------------------- #
# Finding 16: a failed/absent/unparseable metrics probe is a warn disk row,
# never a vanished check
# --------------------------------------------------------------------------- #

def test_probe_without_disk_data_still_emits_a_disk_row(app, server, monkeypatch):
    _connected(monkeypatch, {'doctor.probe': True})
    monkeypatch.setattr(
        registry, 'send_command',
        lambda server_id, action, params, timeout=None, user_id=None: {
            'success': True,
            'data': {'units': {'nginx': {'active': True},
                               'docker': {'active': True}}},
        })

    res = FleetDoctorService._compose_server_checks(server.id, 5.0)

    disk = by_key(res['checks'])['disk.headroom']
    assert disk['status'] == 'warn'
    assert 'disk headroom unknown' in disk['detail']


def test_compose_v1_metrics_failure_still_emits_a_disk_row(app, server, monkeypatch):
    _connected(monkeypatch, {'systemd': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        if action == 'systemd:status':
            return {'success': True, 'data': {'active': True}}
        if action == 'system:metrics':
            return {'success': False, 'error': 'timeout'}
        raise AssertionError(action)

    monkeypatch.setattr(registry, 'send_command', _send)

    res = FleetDoctorService._compose_server_checks(server.id, 5.0)

    disk = by_key(res['checks'])['disk.headroom']
    assert disk['status'] == 'warn'
    assert 'disk headroom unknown' in disk['detail']


def test_compose_v1_unparseable_disk_percent_is_a_warn_not_a_vanish(
        app, server, monkeypatch):
    _connected(monkeypatch, {'systemd': True})

    def _send(server_id, action, params, timeout=None, user_id=None):
        if action == 'systemd:status':
            return {'success': True, 'data': {'active': True}}
        return {'success': True, 'data': {'disk_percent': 'not-a-number'}}

    monkeypatch.setattr(registry, 'send_command', _send)

    res = FleetDoctorService._compose_server_checks(server.id, 5.0)

    disk = by_key(res['checks'])['disk.headroom']
    assert disk['status'] == 'warn'
    assert 'disk headroom unknown' in disk['detail']


# --------------------------------------------------------------------------- #
# Finding 15: a failed/timeout sweep writes a synthetic error row — the last
# all-ok rows must not keep standing as current health
# --------------------------------------------------------------------------- #

def test_a_failed_sweep_persists_a_sweep_error_row(app, server, monkeypatch):
    """The bug: a composer exception → fleet_sweep 'failed' → zero rows
    written → yesterday's green rows kept rendering as today."""
    from app.models.fleet_doctor_result import FleetDoctorResult

    # Yesterday: everything was fine.
    FleetDoctorService._persist(server.id, [
        _row('service.nginx', 'nginx service', 'ok', 'Running.'),
    ])

    # Today: the probe itself blows up inside the (real) fleet_sweep.
    def _boom(cls, server_id, per_agent_timeout):
        raise RuntimeError('agent gateway exploded')

    monkeypatch.setattr(FleetDoctorService, '_compose_server_checks',
                        classmethod(_boom))

    summary = FleetDoctorService.run_fleet_doctor()

    assert summary['sweep_statuses'].get('failed') == 1
    rows = {r.check_key: r for r in
            FleetDoctorResult.query.filter_by(server_id=server.id).all()}
    assert 'sweep' in rows
    assert rows['sweep'].status == FleetDoctorResult.STATUS_ERROR
    assert 'agent gateway exploded' in rows['sweep'].detail


def test_a_timeout_sweep_persists_a_sweep_error_row(app, server, monkeypatch):
    from app.models.fleet_doctor_result import FleetDoctorResult

    monkeypatch.setattr(
        fleet_doctor_service, 'fleet_sweep',
        lambda *a, **k: {server.id: {
            'status': 'timeout',
            'error': 'agent did not respond within the sweep budget'}})

    summary = FleetDoctorService.run_fleet_doctor()

    assert summary['sweep_statuses'].get('timeout') == 1
    rows = {r.check_key: r for r in
            FleetDoctorResult.query.filter_by(server_id=server.id).all()}
    assert rows['sweep'].status == FleetDoctorResult.STATUS_ERROR
    assert 'did not respond' in rows['sweep'].detail


def test_an_offline_server_keeps_its_stale_rows_and_gets_no_sweep_row(
        app, server, monkeypatch):
    """The deliberate exception: offline is a *reported state* (the report
    marks connected=false), so stale rows stand and no error row is added."""
    from app.models.fleet_doctor_result import FleetDoctorResult

    FleetDoctorService._persist(server.id, [
        _row('service.nginx', 'nginx service', 'ok', 'Running.'),
    ])
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: False)

    summary = FleetDoctorService.run_fleet_doctor()

    assert summary['sweep_statuses'].get('offline') == 1
    rows = {r.check_key: r for r in
            FleetDoctorResult.query.filter_by(server_id=server.id).all()}
    assert 'sweep' not in rows
    assert rows['service.nginx'].status == FleetDoctorResult.STATUS_OK


# --------------------------------------------------------------------------- #
# Finding 17: NXDOMAIN is a fail; a resolver outage is "could not check"
# --------------------------------------------------------------------------- #

def _public_server(server):
    server.hostname = 'box.example.com'
    db.session.commit()
    return server


def test_fleet_dns_nxdomain_is_still_a_fail(app, server, monkeypatch):
    monkeypatch.setattr(
        fleet_doctor_service, '_resolve_host_ips',
        lambda host: (_ for _ in ()).throw(
            socket.gaierror(socket.EAI_NONAME, 'Name or service not known')))

    row = FleetDoctorService._dns_check_for_server(_public_server(server))

    assert row['status'] == 'fail'
    assert 'does not resolve' in row['detail']


def test_fleet_dns_resolver_error_is_a_warn_not_a_fake_nxdomain(
        app, server, monkeypatch):
    """The bug: any resolver exception rendered fail 'does not resolve to any
    address.' — a panel-side outage impersonating NXDOMAIN."""
    monkeypatch.setattr(
        fleet_doctor_service, '_resolve_host_ips',
        lambda host: (_ for _ in ()).throw(
            socket.gaierror(socket.EAI_AGAIN, 'Temporary failure')))

    row = FleetDoctorService._dns_check_for_server(_public_server(server))

    assert row['status'] == 'warn'
    assert 'could not check' in row['detail']


def test_fleet_dns_non_gaierror_failure_is_also_a_warn(app, server, monkeypatch):
    monkeypatch.setattr(
        fleet_doctor_service, '_resolve_host_ips',
        lambda host: (_ for _ in ()).throw(OSError('network unreachable')))

    row = FleetDoctorService._dns_check_for_server(_public_server(server))

    assert row['status'] == 'warn'
    assert 'could not check' in row['detail']
