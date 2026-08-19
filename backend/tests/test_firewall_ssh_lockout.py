"""Enabling ufw must not be able to lock the operator out over SSH.

Found on a live box: ufw was installed, inactive, and had exactly one staged
rule — `ufw allow 25/tcp`. sshd was on 22. ufw defaults to deny-incoming, so
enabling would have severed the only way back in.

`ufw enable` normally asks "Command may disrupt existing ssh connections.
Proceed?" — and `--force enable`, which the service must use because nothing
here is attached to a terminal, suppresses exactly that prompt. So the panel
had removed the one safeguard and offered a one-click lockout.

The rule that matters most: an undeterminable SSH port must REFUSE, never fall
back to assuming 22. Guessing in the permissive direction is the lockout.
"""

import subprocess
from unittest.mock import patch

import pytest

from app.services.firewall_service import FirewallService


def _completed(stdout='', returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr='')


def _router(sshd=None, added='', app_info=''):
    """Dispatch run_privileged by command, so each probe answers separately."""
    def _run(cmd, *args, **kwargs):
        if cmd[0] == 'sshd':
            return sshd if sshd is not None else _completed(returncode=1)
        if cmd[:3] == ['ufw', 'show', 'added']:
            return _completed(added)
        if cmd[:3] == ['ufw', 'app', 'info']:
            return _completed(app_info)
        return _completed()
    return _run


@pytest.fixture(autouse=True)
def _deny_by_default():
    """ufw's shipped default: deny incoming."""
    with patch.object(FirewallService, '_ufw_default_incoming_allow',
                      return_value=False):
        yield


SSHD_22 = 'port 22\nlistenaddress 0.0.0.0:22\npermitrootlogin yes\n'
SSHD_2222 = 'port 2222\nlistenaddress 0.0.0.0:2222\n'


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #

@patch('app.services.firewall_service.run_privileged')
def test_the_live_box_case_is_refused(run):
    """sshd on 22, one staged rule for 25/tcp — the real configuration."""
    run.side_effect = _router(sshd=_completed(SSHD_22),
                              added='Added user rules:\nufw allow 25/tcp\n')

    check = FirewallService.check_ssh_lockout('ufw')

    assert check['safe'] is False
    assert check['ssh_ports'] == [22]
    assert 'ufw allow 22/tcp' in check['reason']


@patch('app.services.firewall_service.run_privileged')
def test_covered_ssh_port_is_allowed(run):
    run.side_effect = _router(sshd=_completed(SSHD_22),
                              added='ufw allow 22/tcp\nufw allow 25/tcp\n')

    assert FirewallService.check_ssh_lockout('ufw')['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_non_default_ssh_port_is_honoured(run):
    """A rule for 22 does not protect an sshd listening on 2222."""
    run.side_effect = _router(sshd=_completed(SSHD_2222),
                              added='ufw allow 22/tcp\n')

    check = FirewallService.check_ssh_lockout('ufw')

    assert check['safe'] is False
    assert check['ssh_ports'] == [2222]


@patch('app.services.firewall_service.run_privileged')
def test_undeterminable_ssh_port_refuses_rather_than_assuming_22(run):
    """The rule that matters most — no answer must not become "probably 22"."""
    run.side_effect = _router(sshd=_completed(returncode=1),
                              added='ufw allow 22/tcp\n')

    check = FirewallService.check_ssh_lockout('ufw')

    assert check['safe'] is False
    assert check['ssh_ports'] is None
    assert 'could not determine' in check['reason'].lower()


@patch('app.services.firewall_service.run_privileged')
def test_named_app_profile_is_resolved_not_guessed(run):
    """`ufw allow OpenSSH` does cover 22 — but only because we looked."""
    run.side_effect = _router(
        sshd=_completed(SSHD_22),
        added='ufw allow OpenSSH\n',
        app_info='Profile: OpenSSH\nTitle: Secure shell server\n\nPorts:\n  22/tcp\n',
    )

    assert FirewallService.check_ssh_lockout('ufw')['safe'] is True


@patch('app.services.firewall_service.run_privileged')
def test_unresolvable_app_profile_does_not_count_as_coverage(run):
    """An app profile we cannot read must not be assumed to include SSH."""
    run.side_effect = _router(sshd=_completed(SSHD_22),
                              added='ufw allow SomeProfile\n',
                              app_info='')

    assert FirewallService.check_ssh_lockout('ufw')['safe'] is False


@patch('app.services.firewall_service.run_privileged')
def test_multiple_ssh_ports_all_need_cover(run):
    run.side_effect = _router(sshd=_completed('port 22\nport 2222\n'),
                              added='ufw allow 22/tcp\n')

    assert FirewallService.check_ssh_lockout('ufw')['safe'] is False


def test_accept_default_policy_cannot_lock_anyone_out():
    with patch.object(FirewallService, '_ufw_default_incoming_allow',
                      return_value=True):
        assert FirewallService.check_ssh_lockout('ufw')['safe'] is True


def test_firewalld_is_not_subject_to_the_ufw_guard():
    assert FirewallService.check_ssh_lockout('firewalld')['safe'] is True


# --------------------------------------------------------------------------- #
# enable() honours it
# --------------------------------------------------------------------------- #

@patch.object(FirewallService, '_enable_ufw')
@patch('app.services.firewall_service.run_privileged')
def test_enable_refuses_and_never_runs_force_enable(run, enable_ufw):
    run.side_effect = _router(sshd=_completed(SSHD_22),
                              added='ufw allow 25/tcp\n')

    result = FirewallService.enable('ufw')

    assert result['success'] is False
    assert result['blocked_by'] == 'ssh_lockout'
    enable_ufw.assert_not_called()          # the whole point


@patch.object(FirewallService, '_enable_ufw', return_value={'success': True})
@patch('app.services.firewall_service.run_privileged')
def test_force_overrides_the_guard(run, enable_ufw):
    """An operator with console access can still say "do it anyway"."""
    run.side_effect = _router(sshd=_completed(SSHD_22),
                              added='ufw allow 25/tcp\n')

    result = FirewallService.enable('ufw', force=True)

    assert result['success'] is True
    enable_ufw.assert_called_once()


@patch.object(FirewallService, '_enable_ufw', return_value={'success': True})
@patch('app.services.firewall_service.run_privileged')
def test_enable_proceeds_when_ssh_is_covered(run, enable_ufw):
    run.side_effect = _router(sshd=_completed(SSHD_22),
                              added='ufw allow 22/tcp\n')

    assert FirewallService.enable('ufw')['success'] is True
    enable_ufw.assert_called_once()


@patch.object(FirewallService, '_enable_ufw')
def test_unknown_firewall_still_reports_cleanly(enable_ufw):
    result = FirewallService.enable('nothing-here')

    assert result['success'] is False
    assert result['error'] == 'No firewall detected'
    enable_ufw.assert_not_called()


# --------------------------------------------------------------------------- #
# ssh_ports() parsing
# --------------------------------------------------------------------------- #

@patch('app.services.firewall_service.run_privileged')
def test_ssh_ports_reads_sshd_dash_T(run):
    """`sshd -T` resolves Includes and Match blocks; parsing config does not."""
    run.return_value = _completed('port 22\nport 2222\naddressfamily any\n')

    assert FirewallService.ssh_ports() == [22, 2222]


@patch('app.services.firewall_service.run_privileged')
def test_ssh_ports_returns_none_when_sshd_cannot_be_asked(run):
    run.side_effect = FileNotFoundError(2, 'No such file or directory', 'sshd')

    assert FirewallService.ssh_ports() is None
