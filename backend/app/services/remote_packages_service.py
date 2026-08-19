"""
Remote Packages Service.

Routes /api/v1/servers/<id>/packages/* requests through the agent
registry to the host's package manager (apt/dnf/apk/pacman/zypper).

Long-running operations (install_async, upgrade) return
{job_id, channel} immediately and stream progress on the channel —
the panel re-broadcasts those events to Socket.IO subscribers via
agent_gateway.

Short reads (list_installed, search, info, update_cache) are
synchronous round-trips matching the cron service shape.
"""

from typing import Any, Dict, Iterable, List, Optional

from app.services.remote_command_dispatcher import dispatch_agent_command


class RemotePackagesService:
    """Thin dispatcher to the agent's packages:* handlers."""

    # ---- read paths -------------------------------------------------

    @staticmethod
    def list_installed(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        # The agent's list_installed shells `apt-get list --installed` /
        # `dnf list installed` / etc., which can return ~250KB on a
        # populated server. 30s budget is generous; usually subsecond.
        return dispatch_agent_command(
            server_id, 'packages:list_installed', user_id=user_id, timeout=30.0,
        )

    @staticmethod
    def search(server_id: str, query: str, limit: int = 100,
               user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'packages:search',
            params={'query': query, 'limit': limit},
            user_id=user_id,
            timeout=30.0,
        )

    @staticmethod
    def info(server_id: str, name: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'packages:info',
            params={'name': name},
            user_id=user_id,
            timeout=30.0,
        )

    # ---- write paths ------------------------------------------------

    @staticmethod
    def update_cache(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'packages:update_cache', user_id=user_id, timeout=180.0,
        )

    @staticmethod
    def install(server_id: str, name: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        # Synchronous single-name install for callers that want a
        # structured result (workflow_engine agent_command nodes).
        return dispatch_agent_command(
            server_id, 'packages:install',
            params={'name': name},
            user_id=user_id,
            timeout=15 * 60.0,
        )

    @staticmethod
    def install_async(server_id: str, names: Iterable[str],
                      user_id: Optional[int] = None) -> Dict[str, Any]:
        # Streaming variant: returns {job_id, channel}.
        return dispatch_agent_command(
            server_id, 'packages:install_async',
            params={'names': list(names)},
            user_id=user_id,
            timeout=10.0,
        )

    @staticmethod
    def remove(server_id: str, name: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'packages:remove',
            params={'name': name},
            user_id=user_id,
            timeout=10 * 60.0,
        )

    @staticmethod
    def upgrade(server_id: str, names: Optional[List[str]] = None, all_packages: bool = False,
                user_id: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if all_packages:
            params['all'] = True
        if names:
            params['names'] = list(names)
        return dispatch_agent_command(
            server_id, 'packages:upgrade',
            params=params,
            user_id=user_id,
            timeout=10.0,
        )
