"""Centralized system utilities for subprocess handling.

Provides consistent privilege escalation, distro detection, package management,
and systemd service control so individual services don't need to reinvent these.
"""

import os
import shutil
import subprocess
from typing import List, Optional, Union


def _needs_sudo() -> bool:
    """Return True if the current process should prepend sudo to commands.

    Returns False when:
    - Running on Windows (no sudo concept; dev environment)
    - Already running as root (e.g. inside Docker)
    - ``sudo`` is not installed (minimal containers)
    """
    if os.name == 'nt':
        return False
    if os.geteuid() == 0:
        return False
    if not shutil.which('sudo'):
        return False
    return True


def privileged_cmd(cmd: Union[List[str], str], *, user: Optional[str] = None) -> Union[List[str], str]:
    """Return *cmd* with ``sudo`` prepended when necessary.

    Use this when you need the command list for ``Popen`` or other non-``run``
    callers.  For simple ``subprocess.run`` calls prefer :func:`run_privileged`.

    Pass *user* to run the command as a specific user (``sudo -u <user>``).

    ``sudo -n`` (non-interactive) is always used: nothing here runs attached to a
    human terminal, and callers capture output, so a password prompt would be
    invisible AND unanswerable — sudo would simply block forever, hanging the
    caller (this hung backend startup on a non-root host, via the metadata
    guard's iptables probe). Failing immediately with a non-zero exit is the
    only useful outcome, and every caller already handles that.
    """
    if isinstance(cmd, str):
        if _needs_sudo() and not cmd.lstrip().startswith('sudo '):
            if user:
                return f'sudo -n -u {user} {cmd}'
            return f'sudo -n {cmd}'
        return cmd

    cmd = list(cmd)
    if _needs_sudo() and cmd[0] != 'sudo':
        if user:
            return ['sudo', '-n', '-u', user] + cmd
        return ['sudo', '-n'] + cmd
    return cmd


def run_privileged(cmd: Union[List[str], str], *, user: Optional[str] = None, **kwargs) -> subprocess.CompletedProcess:
    """Run a command with sudo if the current process is not root.

    Prepends ``sudo`` only when needed (not root, not Windows, sudo exists).
    Pass *user* to run the command as a specific user (``sudo -u <user>``).
    Defaults to ``capture_output=True, text=True`` but callers can override.

    Returns the raw ``CompletedProcess`` so services keep their existing
    error-handling patterns.
    """
    cmd = privileged_cmd(cmd, user=user)
    kwargs.setdefault('capture_output', True)
    kwargs.setdefault('text', True)
    return subprocess.run(cmd, **kwargs)


def run_command(cmd: Union[List[str], str], *, timeout: int = 60,
                capture_stderr: bool = False, **kwargs) -> dict:
    """Run a shell command and return a dict with stdout/stderr/returncode.

    This is a convenience wrapper used by services that need simple dict results
    rather than a raw ``CompletedProcess`` object.
    """
    kwargs.setdefault('capture_output', True)
    kwargs.setdefault('text', True)
    result = subprocess.run(cmd, timeout=timeout, **kwargs)
    return {
        'stdout': result.stdout or '',
        'stderr': result.stderr or '',
        'returncode': result.returncode,
    }


def is_command_available(cmd: str) -> bool:
    """Check whether *cmd* is available on the system.

    Uses ``shutil.which`` first, then falls back to checking common sbin/local
    paths that may not be on the current ``$PATH``.
    """
    if shutil.which(cmd):
        return True

    for directory in ('/usr/bin', '/usr/sbin', '/usr/local/bin', '/usr/local/sbin'):
        if os.path.exists(os.path.join(directory, cmd)):
            return True

    return False


def sourced_result(lines: list, source: str, source_label: str) -> dict:
    """Standard response shape for multi-source data endpoints.

    Every fallback-chain endpoint should return this shape so the frontend
    can show a consistent source-aware banner.
    """
    return {
        'success': True,
        'lines': lines,
        'count': len(lines),
        'source': source,
        'source_label': source_label,
    }


class PackageManager:
    """Cross-distro package management helpers.

    Detects ``apt``, ``dnf``, or ``yum`` once and caches the result.
    """

    _detected: Optional[str] = None
    _detection_done: bool = False

    @classmethod
    def detect(cls) -> Optional[str]:
        """Return ``'apt'``, ``'dnf'``, ``'yum'``, or ``None``."""
        if cls._detection_done:
            return cls._detected

        for manager in ('apt', 'dnf', 'yum'):
            if shutil.which(manager):
                cls._detected = manager
                cls._detection_done = True
                return cls._detected

        cls._detection_done = True
        return cls._detected

    @classmethod
    def is_available(cls) -> bool:
        """Return ``True`` if any supported package manager was found."""
        return cls.detect() is not None

    @classmethod
    def is_installed(cls, package: str) -> bool:
        """Check whether *package* is installed (cross-distro).

        Uses ``dpkg -s`` on apt systems and ``rpm -q`` on dnf/yum systems.
        Catches ``FileNotFoundError`` so it works on any distro.
        """
        manager = cls.detect()

        if manager == 'apt':
            try:
                result = subprocess.run(
                    ['dpkg', '-s', package],
                    capture_output=True, text=True,
                )
                return (
                    result.returncode == 0
                    and 'Status: install ok installed' in result.stdout
                )
            except FileNotFoundError:
                return False

        if manager in ('dnf', 'yum'):
            try:
                result = subprocess.run(
                    ['rpm', '-q', package],
                    capture_output=True, text=True,
                )
                return result.returncode == 0
            except FileNotFoundError:
                return False

        return False

    @classmethod
    def install(cls, packages: Union[str, List[str]], timeout: int = 300) -> subprocess.CompletedProcess:
        """Install one or more packages (cross-distro).

        Raises ``RuntimeError`` when no supported package manager is found.
        """
        manager = cls.detect()
        if manager is None:
            raise RuntimeError('No supported package manager found (apt/dnf/yum)')

        if isinstance(packages, str):
            packages = [packages]

        cmd = [manager, 'install', '-y'] + packages
        return run_privileged(cmd, timeout=timeout)

    @classmethod
    def reset_cache(cls) -> None:
        """Reset the cached detection (useful in tests)."""
        cls._detected = None
        cls._detection_done = False


class ServiceControl:
    """Thin wrappers around ``systemctl`` that use :func:`run_privileged`."""

    @staticmethod
    def start(service: str, **kwargs) -> subprocess.CompletedProcess:
        return run_privileged(['systemctl', 'start', service], **kwargs)

    @staticmethod
    def stop(service: str, **kwargs) -> subprocess.CompletedProcess:
        return run_privileged(['systemctl', 'stop', service], **kwargs)

    @staticmethod
    def restart(service: str, **kwargs) -> subprocess.CompletedProcess:
        return run_privileged(['systemctl', 'restart', service], **kwargs)

    @staticmethod
    def reload(service: str, **kwargs) -> subprocess.CompletedProcess:
        return run_privileged(['systemctl', 'reload', service], **kwargs)

    @staticmethod
    def enable(service: str, **kwargs) -> subprocess.CompletedProcess:
        return run_privileged(['systemctl', 'enable', service], **kwargs)

    @staticmethod
    def disable(service: str, **kwargs) -> subprocess.CompletedProcess:
        return run_privileged(['systemctl', 'disable', service], **kwargs)

    @staticmethod
    def daemon_reload(**kwargs) -> subprocess.CompletedProcess:
        return run_privileged(['systemctl', 'daemon-reload'], **kwargs)

    @staticmethod
    def is_active(service: str) -> bool:
        """Return ``True`` when the service is active.  No sudo needed."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', service],
                capture_output=True, text=True,
            )
            return result.stdout.strip() == 'active'
        except FileNotFoundError:
            return False

    @staticmethod
    def is_enabled(service: str) -> bool:
        """Return ``True`` when the service is enabled.  No sudo needed."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-enabled', service],
                capture_output=True, text=True,
            )
            return result.stdout.strip() == 'enabled'
        except FileNotFoundError:
            return False
