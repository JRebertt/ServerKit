"""
Remote Runtimes Service.

Wraps the agent's runtimes:* handlers (pyenv on Linux, pyenv-win on
Windows) so the panel can install / uninstall / select Python versions
on a remote host.

Long-running operations (bootstrap, install) return {job_id, channel}
just like packages:install_async — the frontend subscribes to the
matching Socket.IO room for live build output.
"""

from typing import Any, Dict, Optional

from app.services.remote_command_dispatcher import dispatch_agent_command


class RemoteRuntimesService:
    """Thin dispatcher to runtimes:* on a remote agent."""

    @staticmethod
    def list_state(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(server_id, 'runtimes:list', user_id=user_id)

    @staticmethod
    def python_installed(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:python:installed', user_id=user_id, timeout=15.0,
        )

    @staticmethod
    def python_available(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:python:available', user_id=user_id, timeout=30.0,
        )

    @staticmethod
    def python_current(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:python:current', user_id=user_id, timeout=15.0,
        )

    @staticmethod
    def python_install(server_id: str, version: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:python:install',
            params={'version': version},
            user_id=user_id, timeout=10.0,  # async — returns job_id quickly
        )

    @staticmethod
    def python_uninstall(server_id: str, version: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:python:uninstall',
            params={'version': version},
            user_id=user_id, timeout=120.0,
        )

    @staticmethod
    def python_set_global(server_id: str, version: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:python:set_global',
            params={'version': version},
            user_id=user_id, timeout=15.0,
        )

    @staticmethod
    def python_set_local(server_id: str, version: str, dir_path: str,
                         user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:python:set_local',
            params={'version': version, 'dir': dir_path},
            user_id=user_id, timeout=15.0,
        )

    @staticmethod
    def pyenv_bootstrap(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'runtimes:pyenv:bootstrap',
            user_id=user_id, timeout=10.0,  # async
        )
