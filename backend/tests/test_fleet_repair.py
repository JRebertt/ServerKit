"""Tests for the allowlisted remote-repair layer (fleet_repair_service).

Every refusal (not allowlisted, unknown target, missing server_id, unknown
server, offline agent, capability gap) must be caught server-side and returned
as ``success: False`` with a code — never dispatched to the agent. Only a fully
allowlisted + capable + connected target reaches ``send_command``.
"""
import pytest

from app.services import agent_registry as agent_registry_mod
from app.services.fleet_repair_service import FleetRepairService, _ALLOWLIST

registry = agent_registry_mod.agent_registry


@pytest.fixture
def server(app):
    from app import db
    from factories import make_server
    return make_server(db)


def _connect(monkeypatch, *, connected=True, capable=True, send=None):
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: connected)
    monkeypatch.setattr(registry, 'has_capability', lambda sid, cap: capable)
    if send is not None:
        monkeypatch.setattr(registry, 'send_command', send)


# --------------------------------------------------------------------------- #
# Allowlist shape
# --------------------------------------------------------------------------- #

def test_is_allowlisted():
    assert FleetRepairService.is_allowlisted('fleet.service') is True
    assert FleetRepairService.is_allowlisted('drift') is False
    spec = _ALLOWLIST['fleet.service']
    assert spec['action'] == 'systemd:restart'
    assert spec['capability'] == 'systemd.restart'
    assert spec['param_key'] == 'unit'
    assert spec['item_key'] == 'name'
    assert set(spec['targets']) == {'nginx', 'docker'}


# --------------------------------------------------------------------------- #
# Refusals (never dispatched)
# --------------------------------------------------------------------------- #

def test_unknown_kind_refused(app, server):
    res = FleetRepairService.repair({'kind': 'nope', 'server_id': server.id,
                                     'name': 'nginx'})
    assert res['success'] is False
    assert res['code'] == 'NOT_ALLOWLISTED'


def test_missing_server_id_refused(app):
    res = FleetRepairService.repair({'kind': 'fleet.service', 'name': 'nginx'})
    assert res['success'] is False
    assert res['code'] == 'BAD_REQUEST'


def test_target_not_allowlisted_refused(app, server):
    res = FleetRepairService.repair({'kind': 'fleet.service',
                                     'server_id': server.id, 'name': 'apache2'})
    assert res['success'] is False
    assert res['code'] == 'NOT_ALLOWLISTED'
    assert 'apache2' in res['error']


def test_unknown_server_refused(app):
    res = FleetRepairService.repair({'kind': 'fleet.service',
                                     'server_id': 'does-not-exist', 'name': 'nginx'})
    assert res['success'] is False
    assert res['code'] == 'NOT_FOUND'


def test_offline_agent_refused(app, server, monkeypatch):
    def _boom(*a, **kw):
        pytest.fail('offline agent must not be dispatched to')
    _connect(monkeypatch, connected=False, send=_boom)
    res = FleetRepairService.repair({'kind': 'fleet.service',
                                     'server_id': server.id, 'name': 'nginx'})
    assert res['success'] is False
    assert res['code'] == 'AGENT_OFFLINE'


def test_capability_gap_refused_cleanly(app, server, monkeypatch):
    def _boom(*a, **kw):
        pytest.fail('capability-less agent must not be dispatched to')
    _connect(monkeypatch, connected=True, capable=False, send=_boom)
    res = FleetRepairService.repair({'kind': 'fleet.service',
                                     'server_id': server.id, 'name': 'nginx'})
    assert res['success'] is False
    assert res['code'] == 'UNSUPPORTED'
    assert 'upgrade' in res['error']


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def test_successful_restart_dispatches_and_reports(app, server, monkeypatch):
    calls = []

    def _send(server_id, action, params, timeout=None, user_id=None):
        calls.append((server_id, action, params, timeout, user_id))
        return {'success': True, 'data': {'restarted': True, 'unit': 'nginx'}}

    _connect(monkeypatch, send=_send)
    res = FleetRepairService.repair(
        {'kind': 'fleet.service', 'server_id': server.id, 'name': 'nginx'},
        user_id=7)

    assert res == {'success': True, 'restarted': 'nginx', 'server_id': server.id}
    assert len(calls) == 1
    sid, action, params, timeout, user_id = calls[0]
    assert sid == server.id
    assert action == 'systemd:restart'
    assert params == {'unit': 'nginx'}
    assert timeout == 130.0
    assert user_id == 7


def test_failed_restart_surfaces_agent_error(app, server, monkeypatch):
    def _send(*a, **kw):
        return {'success': False, 'error': 'unit not found', 'code': 'AGENT_ERR'}

    _connect(monkeypatch, send=_send)
    res = FleetRepairService.repair(
        {'kind': 'fleet.service', 'server_id': server.id, 'name': 'docker'})
    assert res['success'] is False
    assert res['error'] == 'unit not found'
    assert res['code'] == 'AGENT_ERR'
