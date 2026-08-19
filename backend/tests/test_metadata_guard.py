"""Cloud metadata egress guard — service logic and API endpoints.

Proving points:
- default-on: with no setting stored, ensure() inserts the DROP rule
- idempotent: apply() with the rule already present does not re-insert
- opt-out: setting False makes ensure() remove the rule
- unsupported hosts (no iptables/nft, or Windows) return cleanly
- nftables best-effort fallback when iptables is absent
- endpoint auth (401 unauthenticated, 403 non-admin PUT)
"""
import types

import pytest

import app.services.metadata_guard_service as mgs
from app.services.metadata_guard_service import (
    JOB_KIND,
    SETTING_KEY,
    MetadataGuardService,
)


# The shared stub kit (plan 75 §G7) — this class was pasted
# byte-identical in four test modules.
from subprocess_stub import FakeProc as _FakeProc


class _FakeFirewall:
    """Stateful iptables/nft stub — tracks rule presence + issued commands."""

    def __init__(self):
        self.ipt_rule_present = False
        self.nft_table_present = False
        self.commands = []

    def run(self, cmd, **kwargs):
        # run_privileged never prepends sudo in these tests (patched directly)
        self.commands.append(cmd)
        if cmd[0] == 'iptables':
            flag = cmd[1]
            if flag == '-C':
                return _FakeProc(0 if self.ipt_rule_present else 1)
            if flag == '-I':
                self.ipt_rule_present = True
                return _FakeProc(0)
            if flag == '-D':
                self.ipt_rule_present = False
                return _FakeProc(0)
        if cmd[0] == 'nft':
            verb = cmd[1]
            if verb == 'list':
                return _FakeProc(0 if self.nft_table_present else 1)
            if verb == 'add':
                self.nft_table_present = True
                return _FakeProc(0)
            if verb == 'delete':
                self.nft_table_present = False
                return _FakeProc(0)
        return _FakeProc(1, stderr='unexpected command')


@pytest.fixture
def linux(monkeypatch):
    """Make the service believe it runs on a Linux host."""
    monkeypatch.setattr(mgs, 'os', types.SimpleNamespace(name='posix'))


@pytest.fixture
def fw(monkeypatch, linux):
    """Linux host with iptables available; returns the stateful stub."""
    fake = _FakeFirewall()
    monkeypatch.setattr(mgs, 'run_privileged', fake.run)
    monkeypatch.setattr(mgs, 'is_command_available', lambda c: c == 'iptables')
    return fake


@pytest.fixture
def fw_nft(monkeypatch, linux):
    """Linux host with only nft available."""
    fake = _FakeFirewall()
    monkeypatch.setattr(mgs, 'run_privileged', fake.run)
    monkeypatch.setattr(mgs, 'is_command_available', lambda c: c == 'nft')
    return fake


@pytest.fixture
def unsupported(monkeypatch, linux):
    """Linux host with neither iptables nor nft."""
    monkeypatch.setattr(mgs, 'is_command_available', lambda c: False)


# ── service: default-on / idempotency / opt-out ─────────────────────────────

def test_default_on_ensure_inserts_drop_rule(app, fw):
    result = MetadataGuardService.ensure()

    assert result['success'] is True
    assert result['active'] is True
    assert result['backend'] == 'iptables'
    assert fw.ipt_rule_present is True
    assert ['iptables', '-I', 'DOCKER-USER', '-d', '169.254.169.254/32',
            '-j', 'DROP'] in fw.commands


def test_apply_is_idempotent(app, fw):
    fw.ipt_rule_present = True

    result = MetadataGuardService.apply()

    assert result['success'] is True
    inserts = [c for c in fw.commands if c[:2] == ['iptables', '-I']]
    assert inserts == []                                    # no double insert


def test_opt_out_removes_rule(app, fw):
    from app.services.settings_service import SettingsService
    fw.ipt_rule_present = True
    SettingsService.set(SETTING_KEY, False)

    result = MetadataGuardService.ensure()

    assert result['success'] is True
    assert result['active'] is False
    assert fw.ipt_rule_present is False
    assert ['iptables', '-D', 'DOCKER-USER', '-d', '169.254.169.254/32',
            '-j', 'DROP'] in fw.commands


def test_remove_noop_when_rule_absent(app, fw):
    result = MetadataGuardService.remove()

    assert result['success'] is True
    deletes = [c for c in fw.commands if c[:2] == ['iptables', '-D']]
    assert deletes == []


def test_status_reports_setting_and_active(app, fw):
    fw.ipt_rule_present = True
    info = MetadataGuardService.status()

    assert info == {'supported': True, 'enabled_setting': True,
                    'active': True, 'backend': 'iptables'}


# ── service: nftables fallback ───────────────────────────────────────────────

def test_nftables_fallback_apply_and_remove(app, fw_nft):
    result = MetadataGuardService.apply()
    assert result['success'] is True
    assert result['backend'] == 'nftables'
    assert fw_nft.nft_table_present is True
    assert any(c[:2] == ['nft', 'add'] for c in fw_nft.commands)

    result = MetadataGuardService.remove()
    assert result['success'] is True
    assert fw_nft.nft_table_present is False


# ── service: unsupported paths ───────────────────────────────────────────────

def test_ensure_unsupported_host_returns_cleanly(app, unsupported):
    result = MetadataGuardService.ensure()
    assert result == {'success': True, 'supported': False,
                      'active': False, 'backend': None}


def test_status_unsupported_host(app, unsupported):
    info = MetadataGuardService.status()
    assert info['supported'] is False
    assert info['backend'] is None
    assert info['active'] is False
    assert info['enabled_setting'] is True                  # still default-on


def test_windows_is_unsupported(app, monkeypatch):
    monkeypatch.setattr(mgs, 'os', types.SimpleNamespace(name='nt'))
    assert MetadataGuardService.status()['supported'] is False
    assert MetadataGuardService.ensure()['supported'] is False


def test_apply_unsupported_reports_error(app, unsupported):
    result = MetadataGuardService.apply()
    assert result['success'] is False
    assert result['supported'] is False
    assert 'error' in result


# ── jobs registration ────────────────────────────────────────────────────────

def test_register_jobs_registers_ensure_kind(app, unsupported):
    from app.jobs import registry
    MetadataGuardService.register_jobs()
    assert JOB_KIND in registry.registered_kinds()

    handler = registry.get(JOB_KIND) if hasattr(registry, 'get') else None
    if handler:
        result = handler(types.SimpleNamespace(get_payload=lambda: {}))
        assert result['supported'] is False                 # clean no-op


# ── API endpoints ────────────────────────────────────────────────────────────

def test_get_metadata_guard_requires_auth(client):
    response = client.get('/api/v1/firewall/metadata-guard')
    assert response.status_code == 401


def test_get_metadata_guard_status(client, auth_headers, unsupported):
    response = client.get('/api/v1/firewall/metadata-guard',
                          headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data['supported'] is False
    assert data['enabled_setting'] is True


def test_put_metadata_guard_requires_admin(client, app, unsupported):
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token

    viewer = User(email='viewer@test.local', username='viewer',
                  password_hash='x', role=User.ROLE_VIEWER, is_active=True)
    db.session.add(viewer)
    db.session.commit()
    token = create_access_token(identity=viewer.id)

    response = client.put('/api/v1/firewall/metadata-guard',
                          headers={'Authorization': f'Bearer {token}'},
                          json={'enabled': False})
    assert response.status_code == 403


def test_put_metadata_guard_requires_body(client, auth_headers, unsupported):
    response = client.put('/api/v1/firewall/metadata-guard',
                          headers=auth_headers, json={})
    assert response.status_code == 400
    assert 'error' in response.get_json()


def test_put_metadata_guard_persists_opt_out(client, auth_headers, fw):
    fw.ipt_rule_present = True

    response = client.put('/api/v1/firewall/metadata-guard',
                          headers=auth_headers, json={'enabled': False})
    assert response.status_code == 200
    data = response.get_json()
    assert data['enabled_setting'] is False
    assert data['active'] is False
    assert fw.ipt_rule_present is False                     # rule actually removed
    assert MetadataGuardService.enabled_setting() is False  # setting persisted


def test_put_metadata_guard_enable_applies_rule(client, auth_headers, fw):
    response = client.put('/api/v1/firewall/metadata-guard',
                          headers=auth_headers, json={'enabled': True})
    assert response.status_code == 200
    data = response.get_json()
    assert data['enabled_setting'] is True
    assert data['active'] is True
    assert fw.ipt_rule_present is True
