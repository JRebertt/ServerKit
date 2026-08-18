"""
Remote Systemd Service.

Wraps the agent's systemd:* handlers behind a simple Python surface so
the API layer can call control_unit('nginx', 'restart') instead of
threading actions and params manually.

list_units returns canonical unit rows in either JSON or plain-parsed
format — the agent flips automatically based on systemd version. The
panel doesn't need to care which.
"""

from typing import Any, Dict, Optional

from app.services.remote_command_dispatcher import dispatch_agent_command


_VALID_ACTIONS = {'start', 'stop', 'restart', 'enable', 'disable'}


class RemoteSystemdService:
    """Thin dispatcher to systemd:* on a remote agent."""

    @staticmethod
    def list_units(server_id: str, state: Optional[str] = None, type_: str = 'service',
                   user_id: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {'type': type_}
        if state:
            params['state'] = state
        return dispatch_agent_command(
            server_id, 'systemd:list_units', params=params,
            user_id=user_id, timeout=30.0,
        )

    @staticmethod
    def status(server_id: str, unit: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'systemd:status', params={'unit': unit},
            user_id=user_id, timeout=15.0,
        )

    @staticmethod
    def control(server_id: str, unit: str, action: str,
                user_id: Optional[int] = None) -> Dict[str, Any]:
        if action not in _VALID_ACTIONS:
            return {'success': False, 'error': f'invalid action: {action}', 'code': 'INVALID_ACTION'}
        # 2-minute timeout matches the agent's per-action ceiling for
        # cold-starts on heavyweight units (postgresql etc.).
        return dispatch_agent_command(
            server_id, f'systemd:{action}', params={'unit': unit},
            user_id=user_id, timeout=130.0,
        )

    @staticmethod
    def daemon_reload(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'systemd:daemon_reload',
            user_id=user_id, timeout=310.0,
        )

    @staticmethod
    def logs(server_id: str, unit: str, lines: int = 200,
             user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'systemd:logs',
            params={'unit': unit, 'lines': int(lines)},
            user_id=user_id, timeout=30.0,
        )

    @staticmethod
    def logs_follow(server_id: str, unit: str,
                    user_id: Optional[int] = None) -> Dict[str, Any]:
        # Returns {job_id, channel}; the panel re-broadcasts on Socket.IO.
        return dispatch_agent_command(
            server_id, 'systemd:logs_follow',
            params={'unit': unit},
            user_id=user_id, timeout=10.0,
        )
