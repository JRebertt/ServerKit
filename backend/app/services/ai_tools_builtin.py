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

from app.services.ai_tool_registry import ai_tool_registry

logger = logging.getLogger(__name__)

_REGISTERED = False


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
    return DockerService.list_containers(all_containers=include_stopped)


def get_docker_info() -> dict:
    """Get Docker engine status and summary info (version, container/image counts)."""
    from app.services.docker_service import DockerService
    return DockerService.get_docker_info()


def list_applications() -> list:
    """List the web applications managed by this ServerKit panel.

    Returns:
        A list of apps with name, status, type, and port.
    """
    from app.models.application import Application
    # The assistant answers questions about what is RUNNING; a deleted app in
    # its context would be reported as though it still existed.
    return [a.to_dict() for a in Application.query_active().all()]


def list_servers() -> list:
    """List the servers in this ServerKit fleet (the panel host plus paired agents).

    Returns:
        A list of servers with name, status, and address.
    """
    from app.models.server import Server
    out = []
    for s in Server.query.all():
        if hasattr(s, "to_dict"):
            out.append(s.to_dict())
        else:
            out.append({"id": getattr(s, "id", None), "name": getattr(s, "name", None),
                        "status": getattr(s, "status", None)})
    return out


def list_databases() -> dict:
    """List MySQL/MariaDB databases managed on the host.

    Returns:
        A dict with the database list, or a message if MySQL is not available.
    """
    from app.services.database_service import DatabaseService
    try:
        if not DatabaseService.mysql_is_installed():
            return {"available": False, "message": "MySQL/MariaDB is not installed on this host."}
        if not DatabaseService.mysql_is_running():
            return {"available": False, "message": "MySQL/MariaDB is installed but not running."}
        return {"available": True, "databases": DatabaseService.mysql_list_databases()}
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"available": False, "message": f"Could not list databases: {exc}"}


# ---------------------------------------------------------------------------
# Write tools (guarded by the confirmation handshake before execution)
# ---------------------------------------------------------------------------
def restart_docker_container(container_id: str) -> dict:
    """Restart a Docker container. STATE-CHANGING — requires human confirmation.

    Args:
        container_id: The container id or name to restart.
    """
    from app.services.docker_service import DockerService
    DockerService.restart_container(container_id)
    return {"ok": True, "action": "restart", "container": container_id}


def stop_docker_container(container_id: str) -> dict:
    """Stop a running Docker container. STATE-CHANGING — requires human confirmation.

    Args:
        container_id: The container id or name to stop.
    """
    from app.services.docker_service import DockerService
    DockerService.stop_container(container_id)
    return {"ok": True, "action": "stop", "container": container_id}


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
        rbac_feature="databases", rbac_level="read",
    )
    # --- guarded write tools ---
    ai_tool_registry.register(
        name="restart_docker_container", func=restart_docker_container,
        rbac_feature="docker", is_write=True,
    )
    ai_tool_registry.register(
        name="stop_docker_container", func=stop_docker_container,
        rbac_feature="docker", is_write=True,
    )

    _REGISTERED = True
    logger.info("Registered %d built-in AI tools", 8)
