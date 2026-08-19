"""Removing the last rule that admits SSH must not be a one-click lockout.

`enable()` guards the moment the firewall comes up. This guards every moment
after it: with ufw active and denying by default, deleting the rule that admits
SSH severs the very session issuing the delete, and there is no way back in.

Deleting **by number** is the sharp edge — the caller passes an opaque index,
so the only way to know what is about to go is to resolve it against
`ufw status numbered` first.

`deny_port()` is implemented as `remove_rule()`, so it inherits this guard;
denying the SSH port and deleting its allow rule are the same outcome.
"""

import subprocess
from unittest.mock import patch

import pytest

from app.services.firewall_service import FirewallService

NUMBERED = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
[ 2] 25/tcp                     ALLOW IN    Anywhere
[ 3] 80/tcp                     ALLOW IN    Anywhere
"""

NUMBERED_DUPLICATE_SSH = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
[ 2] 22/tcp                     ALLOW IN    10.0.0.0/8
"""

NUMBERED_PROFILE = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] OpenSSH                    ALLOW IN    Anywhere
"""

SSHD_22 = 'port 22\n'


def _completed(stdout='', returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr='')


def _router(numbered=NUMBERED, sshd=SSHD_22, app_info=''):
    def _run(cmd, *args, **kwargs):
        if cmd[0] == 'sshd':
            return _completed(sshd)
        if cmd[:3] == ['ufw', 'status', 'numbered']:
            return _completed(numbered)
        if cmd[:3] == ['ufw', 'app', 'info']:
            return _completed(app_info)
        return _completed()
    return _run


@pytest.fixture(autouse=True)
def _active_ufw():
    """ufw installed, active, default-deny — the state where this matters."""
    with patch.object(FirewallService, 'get_status', return_value={
        'firewalld': {'installed': False, 'running': False, 'default_zone': None},
        'ufw': {'installed': True, 'active': True},
        'active_firewall': 'ufw', 'any_installed': True, 'any_active': True,
    }), patch.object(FirewallService, '_ufw_default_incoming_allow',
                     return_value=False):
        yield


# --------------------------------------------------------------------------- #
# Removal by number — the opaque-index case
# --------------------------------------------------------------------------- #

@patch('app.services.firewall_service.run_privileged')
def test_deleting_the_ssh_rule_by_number_is_refused(run):
    run.side_effect = _router()

    check = FirewallService.check_ssh_rule_removal('port', number=1)

    assert check['safe'] is False
    assert check['ssh_ports'] == [22]
    assert 'only active rule admitting SSH' in check['reason']


@patch('app.services.firewall_service.run_privileged')
def test_deleting_an_unrelated_rule_by_number_is_allowed(run):
    run.side_effect = _router()

    assert FirewallService.check_ssh_rule_removal('port', number=3)['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_a_duplicate_ssh_rule_may_still_be_deleted(run):
    """Two rules admit 22 — removing one leaves SSH open, so do not block it."""
    run.side_effect = _router(numbered=NUMBERED_DUPLICATE_SSH)

    check = FirewallService.check_ssh_rule_removal('port', number=1)

    assert check['safe'] is True
    assert 'stays open via rule 2' in check['reason']


@patch('app.services.firewall_service.run_privileged')
def test_app_profile_rule_is_resolved_before_deleting(run):
    """`[1] OpenSSH` admits 22 — but only because app info was read."""
    run.side_effect = _router(
        numbered=NUMBERED_PROFILE,
        app_info='Profile: OpenSSH\n\nPorts:\n  22/tcp\n',
    )

    assert FirewallService.check_ssh_rule_removal('port', number=1)['safe'] is False


@patch('app.services.firewall_service.run_privileged')
def test_unknown_rule_number_does_not_block(run):
    """ufw would reject it anyway; refusing here blocks harmless deletes."""
    run.side_effect = _router()

    assert FirewallService.check_ssh_rule_removal('port', number=99)['safe'] is True


# --------------------------------------------------------------------------- #
# Removal by specification
# --------------------------------------------------------------------------- #

@patch('app.services.firewall_service.run_privileged')
def test_ipv6_suffix_does_not_parse_as_a_port(run):
    """`22/tcp (v6)` must not yield port 6 — real `ufw status numbered` output."""
    run.side_effect = _router()

    assert FirewallService._ports_in('22/tcp (v6)') == {22}
    assert FirewallService._ports_in('80,443/tcp') == {80, 443}


@patch('app.services.firewall_service.run_privileged')
def test_anywhere_is_not_looked_up_as_an_app_profile(run):
    """It is ufw's wildcard destination; the lookup would cost a subprocess."""
    run.side_effect = _router()

    assert FirewallService._ports_in('Anywhere') == set()
    assert not any(call.args[0][:3] == ['ufw', 'app', 'info']
                   for call in run.call_args_list)


@patch('app.services.firewall_service.run_privileged')
def test_ipv6_ssh_row_still_protects_ssh(run):
    """An IPv6-only SSH allow rule is real coverage and must be guarded."""
    numbered = ('Status: active\n\n'
                '[ 1] 22/tcp (v6)               ALLOW IN    Anywhere (v6)\n')
    run.side_effect = _router(numbered=numbered)

    assert FirewallService.check_ssh_rule_removal('port', number=1)['safe'] is False


@patch('app.services.firewall_service.run_privileged')
def test_deleting_the_ssh_rule_by_port_is_refused(run):
    run.side_effect = _router()

    assert FirewallService.check_ssh_rule_removal('port', port=22)['safe'] is False


@patch('app.services.firewall_service.run_privileged')
def test_deleting_a_non_ssh_port_is_allowed(run):
    run.side_effect = _router()

    assert FirewallService.check_ssh_rule_removal('port', port=80)['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_removal_that_names_no_port_is_allowed(run):
    run.side_effect = _router()

    assert FirewallService.check_ssh_rule_removal('block_ip', ip='1.2.3.4')['safe'] is True


# --------------------------------------------------------------------------- #
# When the guard does not apply
# --------------------------------------------------------------------------- #

@patch('app.services.firewall_service.run_privileged')
def test_inactive_firewall_is_not_guarded(run):
    """Nothing is being enforced; enable() runs its own preflight later."""
    run.side_effect = _router()
    with patch.object(FirewallService, 'get_status', return_value={
        'ufw': {'installed': True, 'active': False}, 'active_firewall': 'ufw',
        'firewalld': {'installed': False, 'running': False, 'default_zone': None},
        'any_installed': True, 'any_active': False,
    }):
        check = FirewallService.check_ssh_rule_removal('port', number=1)

    assert check['safe'] is True
    assert check['reason'] == 'firewall is not active'


@patch('app.services.firewall_service.run_privileged')
def test_undeterminable_ssh_port_refuses(run):
    """Same rule as enable(): no answer must never become "probably 22"."""
    def _run(cmd, *args, **kwargs):
        if cmd[0] == 'sshd':
            return _completed(returncode=1)
        if cmd[:3] == ['ufw', 'status', 'numbered']:
            return _completed(NUMBERED)
        return _completed()
    run.side_effect = _run

    check = FirewallService.check_ssh_rule_removal('port', number=1)

    assert check['safe'] is False
    assert check['ssh_ports'] is None


def test_accept_default_policy_cannot_lock_anyone_out():
    with patch.object(FirewallService, '_ufw_default_incoming_allow',
                      return_value=True):
        assert FirewallService.check_ssh_rule_removal('port', number=1)['safe'] is True


# --------------------------------------------------------------------------- #
# remove_rule() and deny_port() honour it
# --------------------------------------------------------------------------- #

@patch.object(FirewallService, '_remove_ufw_rule')
@patch('app.services.firewall_service.run_privileged')
def test_remove_rule_refuses_and_never_shells_out(run, remove):
    run.side_effect = _router()

    result = FirewallService.remove_rule('port', number=1)

    assert result['success'] is False
    assert result['blocked_by'] == 'ssh_lockout'
    remove.assert_not_called()          # the whole point


@patch.object(FirewallService, '_remove_ufw_rule', return_value={'success': True})
@patch('app.services.firewall_service.run_privileged')
def test_force_overrides_the_removal_guard(run, remove):
    run.side_effect = _router()

    assert FirewallService.remove_rule('port', force=True, number=1)['success'] is True
    remove.assert_called_once()


@patch.object(FirewallService, '_remove_ufw_rule', return_value={'success': True})
@patch('app.services.firewall_service.run_privileged')
def test_unrelated_removal_proceeds(run, remove):
    run.side_effect = _router()

    assert FirewallService.remove_rule('port', number=3)['success'] is True
    remove.assert_called_once()


@patch.object(FirewallService, '_remove_ufw_rule')
@patch('app.services.firewall_service.run_privileged')
def test_deny_port_on_ssh_inherits_the_guard(run, remove):
    """Denying a port IS removing its allow rule — same lockout, same guard."""
    run.side_effect = _router()

    result = FirewallService.deny_port(22)

    assert result['success'] is False
    assert result['blocked_by'] == 'ssh_lockout'
    remove.assert_not_called()


@patch.object(FirewallService, '_remove_ufw_rule', return_value={'success': True})
@patch('app.services.firewall_service.run_privileged')
def test_deny_port_on_another_port_is_unaffected(run, remove):
    run.side_effect = _router()

    assert FirewallService.deny_port(80)['success'] is True


# --------------------------------------------------------------------------- #
# firewalld
# --------------------------------------------------------------------------- #

@pytest.fixture
def _active_firewalld():
    with patch.object(FirewallService, 'get_status', return_value={
        'firewalld': {'installed': True, 'running': True, 'default_zone': 'public'},
        'ufw': {'installed': False, 'active': False},
        'active_firewall': 'firewalld', 'any_installed': True, 'any_active': True,
    }):
        yield


def _firewalld_router(services='ssh dhcpv6-client', ports=''):
    def _run(cmd, *args, **kwargs):
        if cmd[0] == 'sshd':
            return _completed(SSHD_22)
        if cmd[:2] == ['firewall-cmd', '--list-services']:
            return _completed(services)
        if cmd[:2] == ['firewall-cmd', '--list-ports']:
            return _completed(ports)
        return _completed()
    return _run


@patch('app.services.firewall_service.run_privileged')
def test_firewalld_removing_the_ssh_service_is_refused(run, _active_firewalld):
    run.side_effect = _firewalld_router()

    check = FirewallService.check_ssh_rule_removal('service', service='ssh')

    assert check['safe'] is False


@patch('app.services.firewall_service.run_privileged')
def test_firewalld_ssh_service_removal_ok_when_a_port_also_covers_it(
        run, _active_firewalld):
    run.side_effect = _firewalld_router(ports='22/tcp')

    check = FirewallService.check_ssh_rule_removal('service', service='ssh')

    assert check['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_firewalld_unrelated_service_removal_is_allowed(run, _active_firewalld):
    run.side_effect = _firewalld_router()

    assert FirewallService.check_ssh_rule_removal(
        'service', service='http')['safe'] is True
