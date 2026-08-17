"""Two lockouts the port-based guards cannot see.

`enable()` and `remove_rule()` reason about *ports*. These two paths never touch
the SSH rule at all, and lock the operator out anyway:

  block_ip(<your own address>)  — the SSH rule is untouched; your source address
                                  is now rejected before it reaches the rule.
  set_default_zone(<zone without ssh>) — firewalld re-homes every interface with
                                  no explicit zone; the rules did not change,
                                  the zone around them did.

Peer detection is read from `ss`, verified against a real host whose only
established SSH connection was `146.190.213.37:22 <- 73.244.95.52:59085` — the
operator's own laptop, and exactly the address a careless block would target.
"""

import subprocess
from unittest.mock import patch

import pytest

from app.services.firewall_service import FirewallService

# Real `ss -Htn state established` output: Recv-Q Send-Q Local Peer.
# The State column is absent because `state established` already filtered it.
SS_OUTPUT = (
    '0      0      146.190.213.37:22 73.244.95.52:59085\n'
    '0      0      146.190.213.37:443 203.0.113.9:44100\n'
)
SSHD_22 = 'port 22\n'


def _completed(stdout='', returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr='')


def _router(ss=SS_OUTPUT, sshd=SSHD_22):
    def _run(cmd, *args, **kwargs):
        if cmd[0] == 'sshd':
            return _completed(sshd)
        if cmd[0] == 'ss':
            return _completed(ss)
        return _completed()
    return _run


# --------------------------------------------------------------------------- #
# block_ip
# --------------------------------------------------------------------------- #

@patch('app.services.firewall_service.run_privileged')
def test_peers_are_read_from_ss_and_filtered_to_ssh_ports(run):
    """The :443 connection is not an SSH session and must not be protected."""
    run.side_effect = _router()

    assert FirewallService.active_ssh_peers() == {'73.244.95.52'}


@patch('app.services.firewall_service.run_privileged')
def test_blocking_your_own_ssh_source_is_refused(run):
    run.side_effect = _router()

    check = FirewallService.check_ip_block('73.244.95.52')

    assert check['safe'] is False
    assert check['conflicts'] == ['73.244.95.52']


@patch('app.services.firewall_service.run_privileged')
def test_blocking_someone_else_is_allowed(run):
    run.side_effect = _router()

    assert FirewallService.check_ip_block('198.51.100.7')['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_a_cidr_that_swallows_your_session_is_refused(run):
    """Blocking 73.244.0.0/16 is the same lockout wearing a wider mask."""
    run.side_effect = _router()

    check = FirewallService.check_ip_block('73.244.0.0/16')

    assert check['safe'] is False
    assert '73.244.95.52' in check['conflicts']


@patch('app.services.firewall_service.run_privileged')
def test_a_cidr_that_misses_your_session_is_allowed(run):
    run.side_effect = _router()

    assert FirewallService.check_ip_block('198.51.100.0/24')['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_blocking_loopback_is_refused(run):
    """nginx forwards to 127.0.0.1 — blocking it takes the panel down."""
    run.side_effect = _router(ss='')

    check = FirewallService.check_ip_block('127.0.0.1')

    assert check['safe'] is False
    assert check['conflicts'] == ['loopback']


@patch('app.services.firewall_service.run_privileged')
def test_the_panel_callers_own_address_is_refused(run):
    """No SSH session at all, but blocking it still locks them out of the UI."""
    run.side_effect = _router(ss='')

    check = FirewallService.check_ip_block('203.0.113.5', caller_ip='203.0.113.5')

    assert check['safe'] is False
    assert check['conflicts'] == ['203.0.113.5']


@patch('app.services.firewall_service.run_privileged')
def test_caller_ip_is_not_double_reported(run):
    """Same address via SSH and the panel is one conflict, not two."""
    run.side_effect = _router()

    check = FirewallService.check_ip_block('73.244.95.52', caller_ip='73.244.95.52')

    assert check['conflicts'] == ['73.244.95.52']


@patch('app.services.firewall_service.run_privileged')
def test_unreadable_ss_does_not_fabricate_peers(run):
    """A failed probe must not invent conflicts and block every request."""
    run.side_effect = _router(ss='')

    assert FirewallService.active_ssh_peers() == set()
    assert FirewallService.check_ip_block('198.51.100.7')['safe'] is True


@patch.object(FirewallService, 'add_rule')
@patch('app.services.firewall_service.run_privileged')
def test_block_ip_refuses_and_never_adds_the_rule(run, add_rule):
    run.side_effect = _router()

    result = FirewallService.block_ip('73.244.95.52')

    assert result['success'] is False
    assert result['blocked_by'] == 'ssh_lockout'
    add_rule.assert_not_called()


@patch.object(FirewallService, 'add_rule', return_value={'success': True})
@patch('app.services.firewall_service.run_privileged')
def test_force_overrides_the_self_block_guard(run, add_rule):
    run.side_effect = _router()

    assert FirewallService.block_ip('73.244.95.52', force=True)['success'] is True
    add_rule.assert_called_once()


@patch.object(FirewallService, 'add_rule', return_value={'success': True})
@patch('app.services.firewall_service.run_privileged')
def test_blocking_an_unrelated_ip_proceeds(run, add_rule):
    run.side_effect = _router()

    assert FirewallService.block_ip('198.51.100.7')['success'] is True
    add_rule.assert_called_once()


@patch.object(FirewallService, 'add_rule')
def test_invalid_ip_is_still_rejected_first(add_rule):
    result = FirewallService.block_ip('not-an-ip')

    assert result['error'] == 'Invalid IP address format'
    add_rule.assert_not_called()


# --------------------------------------------------------------------------- #
# set_default_zone
# --------------------------------------------------------------------------- #

@pytest.fixture
def _running_firewalld():
    with patch.object(FirewallService, 'get_status', return_value={
        'firewalld': {'installed': True, 'running': True, 'default_zone': 'public'},
        'ufw': {'installed': False, 'active': False},
        'active_firewall': 'firewalld', 'any_installed': True, 'any_active': True,
    }):
        yield


def _zone_router(services='', ports='', sshd=SSHD_22):
    def _run(cmd, *args, **kwargs):
        if cmd[0] == 'sshd':
            return _completed(sshd)
        if len(cmd) > 2 and cmd[2] == '--list-services':
            return _completed(services)
        if len(cmd) > 2 and cmd[2] == '--list-ports':
            return _completed(ports)
        return _completed()
    return _run


@patch('app.services.firewall_service.run_privileged')
def test_zone_without_ssh_is_refused(run, _running_firewalld):
    run.side_effect = _zone_router(services='dhcpv6-client')

    check = FirewallService.check_default_zone('drop')

    assert check['safe'] is False
    assert 'does not permit SSH' in check['reason']


@patch('app.services.firewall_service.run_privileged')
def test_zone_with_the_ssh_service_is_allowed(run, _running_firewalld):
    run.side_effect = _zone_router(services='ssh dhcpv6-client')

    assert FirewallService.check_default_zone('public')['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_zone_with_the_ssh_port_is_allowed(run, _running_firewalld):
    """Coverage by explicit port counts, not just the named service."""
    run.side_effect = _zone_router(services='http', ports='22/tcp')

    assert FirewallService.check_default_zone('custom')['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_zone_change_refuses_when_ssh_port_is_undeterminable(run, _running_firewalld):
    run.side_effect = _zone_router(services='ssh', sshd='')

    def _run(cmd, *args, **kwargs):
        if cmd[0] == 'sshd':
            return _completed(returncode=1)
        return _completed('ssh')
    run.side_effect = _run

    check = FirewallService.check_default_zone('public')

    assert check['safe'] is False
    assert check['ssh_ports'] is None


def test_zone_guard_is_a_noop_when_firewalld_is_not_running():
    with patch.object(FirewallService, 'get_status', return_value={
        'firewalld': {'installed': True, 'running': False, 'default_zone': None},
        'ufw': {'installed': False, 'active': False},
        'active_firewall': 'firewalld', 'any_installed': True, 'any_active': False,
    }):
        assert FirewallService.check_default_zone('drop')['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_set_default_zone_refuses_and_never_shells_out(run, _running_firewalld):
    run.side_effect = _zone_router(services='dhcpv6-client')

    result = FirewallService.set_default_zone('drop')

    assert result['success'] is False
    assert result['blocked_by'] == 'ssh_lockout'
    assert not any('--set-default-zone' in str(c) for c in run.call_args_list)


@patch('app.services.firewall_service.run_privileged')
def test_force_overrides_the_zone_guard(run, _running_firewalld):
    run.side_effect = _zone_router(services='dhcpv6-client')

    result = FirewallService.set_default_zone('drop', force=True)

    assert result['success'] is True
    assert any('--set-default-zone' in str(c) for c in run.call_args_list)
