"""
Remote Cloudflared Service

Mirrors RemoteCronService: a thin dispatcher that forwards
cloudflared:* actions to the agent.

Auth model — approach A (the user runs `cloudflared tunnel login`
once on each server). The panel never touches Cloudflare credentials
directly; the cert.pem on the host IS the credential, and cloudflared
uses it for every subsequent call. The /status endpoint surfaces
"cert present? yes/no" so the UI can show a "log in first" prompt
instead of letting actions fail with confusing errors.
"""

from typing import Any, Dict, Optional

from app.services.remote_command_dispatcher import dispatch_agent_command


class RemoteCloudflaredService:
    @staticmethod
    def status(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(server_id, 'cloudflared:status',
                                      user_id=user_id, timeout=8.0)

    @staticmethod
    def list_tunnels(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        # Tunnel list hits Cloudflare API server-side, so allow more time
        # than for crontab parsing.
        return dispatch_agent_command(server_id, 'cloudflared:tunnel:list',
                                      user_id=user_id, timeout=30.0)

    @staticmethod
    def create_tunnel(server_id: str, name: str,
                      user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'cloudflared:tunnel:create',
            params={'name': name},
            user_id=user_id, timeout=30.0,
        )

    @staticmethod
    def route_tunnel(server_id: str, tunnel_ref: str, hostname: str,
                     user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'cloudflared:tunnel:route',
            params={'tunnel_ref': tunnel_ref, 'hostname': hostname},
            user_id=user_id, timeout=30.0,
        )

    @staticmethod
    def delete_tunnel(server_id: str, ref: str,
                      user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'cloudflared:tunnel:delete',
            params={'ref': ref},
            user_id=user_id, timeout=30.0,
        )

    @staticmethod
    def login(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        # Returns {job_id, channel} immediately; the panel subscribes to
        # the matching Socket.IO room for the auth_url + completion event.
        return dispatch_agent_command(
            server_id, 'cloudflared:login',
            user_id=user_id, timeout=10.0,
        )
