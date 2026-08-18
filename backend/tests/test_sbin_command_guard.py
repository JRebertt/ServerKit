"""Guard: sbin-resident commands must never be exec'd by bare name.

The panel's systemd unit historically shipped

    Environment="PATH=<venv>/bin:/usr/local/bin:/usr/bin:/bin"

with no sbin directory, and it runs as root — so `_needs_sudo()` is False and
nothing prepends `sudo` to resolve the command through sudo's secure_path.
`subprocess` searches $PATH and nothing else, so every sbin-resident tool
raised FileNotFoundError. Callers wrapping the call in a broad `except` then
reported that as a *fact about the system*:

  - `ufw status`  -> "No Firewall Installed", on a host where ufw was installed
  - `nginx -t`    -> every config reported invalid

`fail2ban-client` and `certbot` live in /usr/bin, so they always worked — which
is exactly why the failure looked feature-specific instead of systemic.

Two layers keep it dead:

  1. `privileged_cmd` and `run_unprivileged` resolve argv[0] to an absolute path
     when $PATH cannot (verified below against a PATH with no sbin).
  2. this static scan, so a NEW raw `subprocess` call cannot reintroduce it by
     bypassing both helpers.
"""

import ast
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.utils.system import privileged_cmd, resolve_command, run_unprivileged

APP_ROOT = Path(__file__).resolve().parent.parent / 'app'

#: Commands that live in /usr/sbin or /sbin on Debian/Ubuntu and RHEL. Bare-name
#: exec of any of these is a latent FileNotFoundError on a root install.
SBIN_COMMANDS = {
    'a2enmod', 'a2ensite', 'blkid', 'dovecot', 'e2fsck', 'fail2ban-server',
    'groupadd', 'ip', 'ip6tables', 'ipset', 'iptables', 'modprobe', 'nft',
    'nginx', 'postfix', 'service', 'sshd', 'swapon', 'sysctl', 'tune2fs',
    'ufw', 'useradd', 'userdel', 'usermod',
}

#: Direct subprocess entry points. These bypass both helpers, so they get no
#: argv[0] resolution and are the only way to reintroduce the bug.
RAW_SUBPROCESS_FUNCS = {'run', 'Popen', 'check_output', 'check_call', 'call'}


def _python_files():
    for path in APP_ROOT.rglob('*.py'):
        if '__pycache__' in path.parts:
            continue
        yield path


def _first_arg_command(node):
    """argv[0] of a subprocess call, when it is a plain literal list."""
    if not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, (ast.List, ast.Tuple)) or not first.elts:
        return None
    head = first.elts[0]
    if isinstance(head, ast.Constant) and isinstance(head.value, str):
        return head.value
    return None


def _is_raw_subprocess(node):
    """`subprocess.<fn>(...)` — not run_privileged / run_unprivileged."""
    func = node.func
    return (isinstance(func, ast.Attribute)
            and func.attr in RAW_SUBPROCESS_FUNCS
            and isinstance(func.value, ast.Name)
            and func.value.id == 'subprocess')


def _scan(path):
    """[(lineno, command)] — bare sbin commands exec'd directly in *path*."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_raw_subprocess(node):
            continue
        command = _first_arg_command(node)
        # 'sudo' as argv[0] is safe: sudo resolves through its own secure_path,
        # which includes the sbin dirs on every distro we target.
        if command in SBIN_COMMANDS:
            offenders.append((node.lineno, command))
    return offenders


def test_no_bare_sbin_command_in_raw_subprocess_calls():
    """A new raw subprocess call must not reintroduce the FileNotFoundError."""
    found = []
    for path in _python_files():
        for lineno, command in _scan(path):
            rel = path.relative_to(APP_ROOT.parent.parent)
            found.append(f'{rel}:{lineno} execs {command!r} by bare name')

    assert not found, (
        'These commands live in /usr/sbin or /sbin, which the panel unit\'s '
        'PATH may omit — subprocess would raise FileNotFoundError:\n  '
        + '\n  '.join(found)
        + '\n\nUse run_privileged() (or run_unprivileged() when no root is needed); '
          'both resolve argv[0] to an absolute path when $PATH cannot.'
    )


# --------------------------------------------------------------------------- #
# The helpers actually resolve, under the PATH that caused the outage
# --------------------------------------------------------------------------- #

CONSTRAINED_PATH = '/opt/serverkit/venv/bin:/usr/local/bin:/usr/bin:/bin'


@pytest.mark.parametrize('command', sorted(SBIN_COMMANDS))
def test_helpers_resolve_every_sbin_command_without_sbin_on_path(command):
    """Simulates the real unit: sbin absent from $PATH, running as root."""
    sbin_path = f'/usr/sbin/{command}'

    with patch.dict(os.environ, {'PATH': CONSTRAINED_PATH}), \
         patch('app.utils.system.shutil.which', return_value=None), \
         patch('app.utils.system.os.path.exists',
               side_effect=lambda p: p == sbin_path), \
         patch('app.utils.system.os.name', 'posix'), \
         patch('app.utils.system.os.geteuid', return_value=0, create=True):

        assert resolve_command(command) == sbin_path
        assert privileged_cmd([command, '--version'])[0] == sbin_path


@patch('app.utils.system.subprocess.run')
@patch('app.utils.system.os.path.exists')
@patch('app.utils.system.shutil.which', return_value=None)
def test_run_unprivileged_resolves_too(_which, exists, mock_run):
    """The sibling helper had the same gap — `nginx -t` went through it."""
    exists.side_effect = lambda p: p == '/usr/sbin/nginx'
    mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')

    run_unprivileged(['nginx', '-t'])

    assert mock_run.call_args[0][0] == ['/usr/sbin/nginx', '-t']


@patch('app.utils.system.subprocess.run')
@patch('app.utils.system.shutil.which', return_value='/usr/bin/git')
def test_run_unprivileged_leaves_resolvable_commands_alone(_which, mock_run):
    """A working $PATH must not have its argv rewritten underneath callers."""
    mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')

    run_unprivileged(['git', 'status'])

    assert mock_run.call_args[0][0] == ['git', 'status']


def test_the_ambiguous_name_stays_gone():
    """`run_command` said nothing about privilege and sat one autocomplete from
    `run_privileged`. `nginx -t` went through it and reported every config
    invalid. Re-adding the name re-adds the second door this rename closed.

    (`PythonService.run_command` is unrelated and keeps its name — the collision
    is part of why the utils one had to change.)
    """
    import app.utils.system as system

    assert not hasattr(system, 'run_command'), (
        'app.utils.system.run_command is back. Use run_privileged() or the '
        'explicit run_unprivileged() — a name that does not say whether it '
        'escalates is how nginx -t ended up unprivileged.'
    )
