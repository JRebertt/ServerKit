"""Built-in ``core.*`` AI tools (powered by Prompture).

These wrap existing ServerKit services so the assistant can answer with LIVE
data and (with confirmation) take action. Each function has type hints + a
Google-style docstring — Prompture derives the tool's JSON-Schema from those.

RBAC is declared at registration (``rbac_feature``/``rbac_level``) and enforced
by the registry + the per-request wrapper in ai_service; these bodies assume the
caller already passed the check. Write tools (``is_write=True``) execute the real
effect here — the confirmation handshake happens in the wrapper *before* this
body runs.

Tools run inside the streaming worker thread (or the request) with an active
Flask app context, so DB/service calls work normally.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar

from app.services.ai_tool_registry import ai_tool_registry

logger = logging.getLogger(__name__)

_REGISTERED = False
tool_caller = ContextVar('ai_tool_caller', default=None)


def _caller(*, admin=False):
    user = tool_caller.get()
    if user is None or not user.is_active or (admin and not user.is_admin):
        raise PermissionError('Permission denied for this AI tool.')
    return user


def _summary(row, fields):
    return {field: getattr(row, field, None) for field in fields}


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------
def get_system_metrics() -> dict:
    """Get live CPU, memory, disk, and network usage for the panel host.

    Returns:
        A dict of current system metrics (cpu, memory, disk, network, uptime).
    """
    from app.services.system_service import SystemService
    return SystemService.get_all_metrics()


def list_docker_containers(include_stopped: bool = True) -> list:
    """List Docker containers on the host.

    Args:
        include_stopped: If true, include stopped containers; otherwise only running ones.
    """
    from app.services.docker_service import DockerService
    _caller()
    rows = DockerService.list_containers(all_containers=include_stopped)
    fields = ('id', 'name', 'image', 'status', 'state', 'ports', 'protected')
    return [{key: row.get(key) for key in fields if key in row} for row in rows]


def get_docker_info() -> dict:
    """Get Docker engine status and summary info (version, container/image counts)."""
    from app.services.docker_service import DockerService
    _caller()
    info = DockerService.get_docker_info() or {}
    fields = ('ServerVersion', 'Containers', 'ContainersRunning', 'ContainersPaused',
              'ContainersStopped', 'Images', 'NCPU', 'MemTotal', 'OperatingSystem',
              'version', 'containers', 'images', 'running')
    return {key: info[key] for key in fields if key in info}


def list_applications(workspace_id: int = None) -> list:
    """List the web applications managed by this ServerKit panel.

    Returns:
        A list of apps with name, status, type, and port.
    """
    from app.models.application import Application
    from app.services.workspace_service import WorkspaceService
    user = _caller()
    ws_id = WorkspaceService.resolve_workspace_id(user, workspace_id)
    # The assistant answers questions about what is RUNNING; a deleted app in
    # its context would be reported as though it still existed.
    query = WorkspaceService.scope_query(
        Application.query_active(), Application, user, workspace_id=ws_id,
        owner_attr='user_id', grant_resource_type='application',
    )
    return [_summary(a, ('id', 'name', 'status', 'app_type', 'port')) for a in query.all()]


def list_servers(workspace_id: int = None) -> list:
    """List the servers in this ServerKit fleet (the panel host plus paired agents).

    Returns:
        A list of servers with name, status, and address.
    """
    from app.models.server import Server
    from app.services.workspace_service import WorkspaceService
    user = _caller()
    ws_id = WorkspaceService.resolve_workspace_id(user, workspace_id)
    query = WorkspaceService.scope_query(Server.query, Server, user, workspace_id=ws_id)
    return [_summary(s, ('id', 'name', 'status', 'hostname')) for s in query.all()]


def list_databases() -> dict:
    """List MySQL/MariaDB databases managed on the host.

    Returns:
        A dict with the database list, or a message if MySQL is not available.
    """
    from app.services.database_service import DatabaseService
    _caller(admin=True)
    try:
        if not DatabaseService.mysql_is_installed():
            return {"available": False, "message": "MySQL/MariaDB is not installed on this host."}
        if not DatabaseService.mysql_is_running():
            return {"available": False, "message": "MySQL/MariaDB is installed but not running."}
        return {"available": True, "databases": DatabaseService.mysql_list_databases()}
    except Exception:  # pragma: no cover - environment dependent
        return {"available": False, "message": "Could not list databases on this host."}


# ---------------------------------------------------------------------------
# Write tools (guarded by the confirmation handshake before execution)
# ---------------------------------------------------------------------------
def restart_docker_container(container_id: str) -> dict:
    """Restart a Docker container. STATE-CHANGING — requires human confirmation.

    Args:
        container_id: The container id or name to restart.
    """
    from app.services.docker_service import DockerService
    _caller(admin=True)
    if DockerService.is_protected_container(container_id):
        raise PermissionError('ServerKit system containers cannot be controlled here.')
    return DockerService.restart_container(container_id)


def stop_docker_container(container_id: str) -> dict:
    """Stop a running Docker container. STATE-CHANGING — requires human confirmation.

    Args:
        container_id: The container id or name to stop.
    """
    from app.services.docker_service import DockerService
    _caller(admin=True)
    if DockerService.is_protected_container(container_id):
        raise PermissionError('ServerKit system containers cannot be controlled here.')
    return DockerService.stop_container(container_id)


def register_builtin_tools() -> None:
    """Register all ``core.*`` tools with the global registry (idempotent)."""
    global _REGISTERED
    if _REGISTERED:
        return

    ai_tool_registry.register(
        name="get_system_metrics", func=get_system_metrics,
        rbac_feature="monitoring", rbac_level="read",
    )
    ai_tool_registry.register(
        name="list_docker_containers", func=list_docker_containers,
        rbac_feature="docker", rbac_level="read",
    )
    ai_tool_registry.register(
        name="get_docker_info", func=get_docker_info,
        rbac_feature="docker", rbac_level="read",
    )
    ai_tool_registry.register(
        name="list_applications", func=list_applications,
        rbac_feature="applications", rbac_level="read",
    )
    ai_tool_registry.register(
        name="list_servers", func=list_servers,
        rbac_feature="servers", rbac_level="read",
    )
    ai_tool_registry.register(
        name="list_databases", func=list_databases,
        rbac_feature="databases", rbac_level="read", admin_only=True,
    )
    # --- guarded write tools ---
    ai_tool_registry.register(
        name="restart_docker_container", func=restart_docker_container,
        rbac_feature="docker", is_write=True, admin_only=True,
    )
    ai_tool_registry.register(
        name="stop_docker_container", func=stop_docker_container,
        rbac_feature="docker", is_write=True, admin_only=True,
    )

    _REGISTERED = True
    logger.info("Registered %d built-in AI tools", 8)
