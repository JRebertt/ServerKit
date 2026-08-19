"""
Remote File Service

Mirrors the local FileService surface but routes through the agent
registry so callers can target a remote server. Phase 3b ships only the
verbs the agent already supports (file:read, file:write, file:list);
other operations (delete, mkdir, rename, copy, chmod, search, disk
usage) require new agent handlers and land in a follow-up.

Action mapping (panel → agent):
    file:list  -> {path, files: [{name, path, is_dir, size, modified, ...}]}
    file:read  -> {path, content, size}
    file:write -> {success: true, path, size}

Allowed paths are enforced on the agent side via validateFileAccess —
the panel never sees the agent's filesystem state and shouldn't try to
second-guess it.
"""

from typing import Any, Dict, Optional

from app.services.agent_registry import agent_registry
from app.services.remote_command_dispatcher import dispatch_agent_command


class RemoteFileService:
    """Thin dispatcher to agent file:* handlers."""

    @staticmethod
    def list_directory(server_id: str, path: str,
                       user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'file:list',
            params={'path': path},
            user_id=user_id,
        )

    @staticmethod
    def read_file(server_id: str, path: str,
                  user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'file:read',
            params={'path': path},
            user_id=user_id,
        )

    @staticmethod
    def write_file(server_id: str, path: str, content: str,
                   user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'file:write',
            params={'path': path, 'content': content},
            user_id=user_id,
            timeout=30.0,
        )

    @staticmethod
    def get_allowed_paths(server_id: str) -> list:
        """Roots the agent advertised on connect — used by the UI to seed
        the browse picker. Empty for agents that don't expose files."""
        return agent_registry.get_allowed_paths(server_id)
