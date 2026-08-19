"""Shared command boundary for services backed by a ServerKit agent.

Remote feature services describe domain verbs and their parameters.  This
module owns the transport-level defaults and normalization needed to send
those verbs to an agent.  Keeping that seam here prevents every remote
service from growing its own subtly different ``agent_registry`` wrapper.
"""

from typing import Any, Dict, Mapping, Optional

from app.services.agent_registry import agent_registry


def dispatch_agent_command(
    server_id: str,
    action: str,
    params: Optional[Mapping[str, Any]] = None,
    user_id: Optional[int] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Dispatch one typed agent verb through the shared registry transport."""
    return agent_registry.send_command(
        server_id=server_id,
        action=action,
        params=dict(params or {}),
        user_id=user_id,
        timeout=timeout,
    )
