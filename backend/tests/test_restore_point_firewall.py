"""Plan 81 firewall checkpoint adapter and mutation-door coverage."""

from types import SimpleNamespace

import pytest


def _ufw_payload(*, enabled=True, allow_default=False, rules=None):
    return {
        'version': 1,
        'firewall': 'ufw',
        'enabled': enabled,
        'default_zone': None,
        'default_incoming_allow': allow_default,
        'rules': rules or [],
    }


def test_capture_uses_replayable_ufw_rules(monkeypatch):
    from app.services import restore_point_adapter_firewall as adapter

    monkeypatch.setattr(adapter.FirewallService, 'get_status', classmethod(
        lambda cls: {
            'active_firewall': 'ufw',
            'ufw': {'installed': True, 'active': False},
            'firewalld': {'installed': False, 'running': False},
        }))
    monkeypatch.setattr(
        adapter.FirewallService, '_ufw_default_incoming_policy',
        classmethod(lambda cls: False),
    )
    monkeypatch.setattr(adapter, 'run_privileged', lambda argv, timeout=None: SimpleNamespace(
        returncode=0,
        stdout=('Added user rules\n'
                'ufw deny from 203.0.113.9\n'
                'ufw allow 2222/tcp\n'),
        stderr='',
    ))

    payload = adapter.capture('firewall')

    assert payload['enabled'] is False
    assert payload['default_incoming_allow'] is False
    assert payload['rules'] == sorted([
        {'kind': 'ufw', 'argv': ['deny', 'from', '203.0.113.9']},
        {'kind': 'ufw', 'argv': ['allow', '2222/tcp']},
    ], key=adapter._rule_key)


def test_capture_refuses_unknown_ufw_policy_and_remote_scope(monkeypatch):
    from app.services import restore_point_adapter_firewall as adapter

    monkeypatch.setattr(adapter.FirewallService, 'get_status', classmethod(
        lambda cls: {
            'active_firewall': 'ufw',
            'ufw': {'installed': True, 'active': False},
            'firewalld': {'installed': False, 'running': False},
        }))
    monkeypatch.setattr(
        adapter.FirewallService, '_ufw_default_incoming_policy',
        classmethod(lambda cls: None),
    )

    with pytest.raises(RuntimeError, match='default incoming policy'):
        adapter.capture('firewall')
    with pytest.raises(ValueError, match='remote firewall'):
        adapter.capture('firewall', server_id='remote-1')


def test_firewalld_capture_includes_non_default_zones(monkeypatch):
    from app.services import restore_point_adapter_firewall as adapter

    monkeypatch.setattr(adapter.FirewallService, 'get_status', classmethod(
        lambda cls: {
            'active_firewall': 'firewalld',
            'firewalld': {
                'installed': True, 'running': True, 'default_zone': 'public',
            },
            'ufw': {'installed': False, 'active': False},
        }))

    def output(argv):
        if argv[-1] == '--get-zones':
            return 'public internal'
        zone = next((part.split('=', 1)[1] for part in argv if part.startswith('--zone=')), '')
        if argv[-1] == '--list-services':
            return 'ssh' if zone == 'public' else 'postgresql'
        if argv[-1] == '--list-ports':
            return ''
        if argv[-1] == '--list-rich-rules':
            return ''
        raise AssertionError(argv)

    monkeypatch.setattr(adapter, '_run', output)

    payload = adapter.capture('firewall')

    assert {(rule['zone'], rule['service']) for rule in payload['rules']} == {
        ('public', 'ssh'), ('internal', 'postgresql'),
    }


def test_validate_restore_refuses_ssh_lockout_and_protected_address(monkeypatch):
    from app.services import restore_point_adapter_firewall as adapter

    target = _ufw_payload(rules=[
        {'kind': 'ufw', 'argv': ['deny', 'from', '127.0.0.0/8']},
    ])
    monkeypatch.setattr(
        adapter.FirewallService, 'ssh_ports', classmethod(lambda cls: [2222]),
    )
    monkeypatch.setattr(
        adapter.FirewallService, 'active_ssh_peers', classmethod(lambda cls: set()),
    )

    refusals = adapter.validate_restore('firewall', target, _ufw_payload())

    assert any('does not admit SSH on port 2222' in item for item in refusals)
    assert any('protected live address' in item for item in refusals)


def test_restore_replays_additions_before_default_and_removals(monkeypatch):
    from app.services import restore_point_adapter_firewall as adapter

    current = _ufw_payload(rules=[
        {'kind': 'ufw', 'argv': ['allow', '80/tcp']},
    ])
    target = _ufw_payload(rules=[
        {'kind': 'ufw', 'argv': ['allow', '2222/tcp']},
    ])
    monkeypatch.setattr(adapter, 'capture', lambda *_a, **_k: current)
    monkeypatch.setattr(
        adapter.FirewallService, 'ssh_ports', classmethod(lambda cls: [2222]),
    )
    calls = []
    monkeypatch.setattr(
        adapter.FirewallService, 'add_rule', classmethod(
            lambda cls, kind, **values: calls.append(('add', kind, values)) or {'success': True}
        ),
    )
    monkeypatch.setattr(
        adapter.FirewallService, 'remove_rule', classmethod(
            lambda cls, kind, **values: calls.append(('remove', kind, values)) or {'success': True}
        ),
    )

    result = adapter.restore('firewall', target)

    assert result == {'success': True, 'rules_added': 1, 'rules_removed': 1}
    assert [call[0] for call in calls] == ['add', 'remove']
    assert calls[0][2]['port'] == 2222
    assert calls[1][2]['port'] == 80


def test_restore_disables_before_removing_last_rule(monkeypatch):
    from app.services import restore_point_adapter_firewall as adapter

    current = _ufw_payload(enabled=True, rules=[
        {'kind': 'ufw', 'argv': ['allow', '2222/tcp']},
    ])
    target = _ufw_payload(enabled=False)
    monkeypatch.setattr(adapter, 'capture', lambda *_a, **_k: current)
    monkeypatch.setattr(
        adapter.FirewallService, 'ssh_ports', classmethod(lambda cls: [2222]),
    )
    calls = []
    monkeypatch.setattr(
        adapter.FirewallService, 'disable', classmethod(
            lambda cls, firewall=None: calls.append('disable') or {'success': True}
        ),
    )
    monkeypatch.setattr(
        adapter.FirewallService, 'remove_rule', classmethod(
            lambda cls, kind, **values: calls.append('remove') or {'success': True}
        ),
    )

    assert adapter.restore('firewall', target)['success'] is True
    assert calls == ['disable', 'remove']


def test_firewall_door_checkpoints_only_after_request_validation(app, monkeypatch):
    from app.services.firewall_service import FirewallService
    from app.services import restore_point_service

    monkeypatch.setattr(FirewallService, 'get_status', classmethod(lambda cls: {
        'active_firewall': 'ufw',
        'any_active': False,
        'ufw': {'installed': True, 'active': False},
        'firewalld': {'installed': False, 'running': False},
    }))
    monkeypatch.setattr(
        FirewallService, '_add_ufw_rule',
        classmethod(lambda cls, kind, **values: {'success': True}),
    )
    captures = []
    monkeypatch.setattr(
        restore_point_service, 'auto_capture',
        lambda *args, **kwargs: captures.append((args, kwargs)),
    )
    monkeypatch.setattr(restore_point_service, 'get_adapter', lambda scope: object())

    assert FirewallService.add_rule('port')['success'] is False
    assert captures == []
    assert FirewallService.add_rule('port', port=443)['success'] is True
    assert captures[0][0][:3] == ('firewall', 'firewall', 'add_rule')
