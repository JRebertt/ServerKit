"""
Agent Gateway

WebSocket gateway for ServerKit agents.
Handles agent connections, authentication, and message routing.
"""

import json
import logging
import threading
import time
from collections import defaultdict

from flask import request
from flask_socketio import Namespace, emit, disconnect

from app.services.agent_registry import agent_registry
from app.models.server import Server
from app.utils.ip_utils import is_ip_allowed
from app.services.anomaly_detection_service import anomaly_detection_service

logger = logging.getLogger(__name__)

# In-memory per-IP auth rate limiter. Guarded by a lock because the gateway
# runs under async_mode='threading' — on_auth (WS) and the poll /connect
# endpoint can call this concurrently, and an unlocked read-modify-write of a
# shared dict races. Buckets are swept periodically so the dict can't grow
# without bound from one-off IPs on an internet-facing gateway.
# NOTE: request.remote_addr below is the ProxyFix-corrected real client IP when
# TRUST_PROXY_HEADERS is on (plan 48). Before that fix, every agent behind nginx
# shared nginx's address = one global bucket; now the throttle keys per-agent.
_auth_attempts = defaultdict(list)
_auth_attempts_lock = threading.Lock()
_last_auth_sweep = 0.0
_AUTH_RATE_LIMIT = 10  # max attempts per window
_AUTH_RATE_WINDOW = 60  # seconds


def _check_auth_rate_limit(ip_address: str) -> bool:
    """Record an auth attempt and report whether the IP is still under the
    limit. Returns True when allowed, False when the per-IP window is
    exhausted. Thread-safe."""
    global _last_auth_sweep
    now = time.time()
    with _auth_attempts_lock:
        # Opportunistic sweep: drop buckets whose attempts have all aged out
        # so IPs that connect once and never return don't accumulate forever.
        if now - _last_auth_sweep > _AUTH_RATE_WINDOW:
            for ip in list(_auth_attempts.keys()):
                fresh = [t for t in _auth_attempts[ip] if now - t < _AUTH_RATE_WINDOW]
                if fresh:
                    _auth_attempts[ip] = fresh
                else:
                    del _auth_attempts[ip]
            _last_auth_sweep = now

        recent = [t for t in _auth_attempts[ip_address] if now - t < _AUTH_RATE_WINDOW]
        if len(recent) >= _AUTH_RATE_LIMIT:
            _auth_attempts[ip_address] = recent
            return False
        recent.append(now)
        _auth_attempts[ip_address] = recent
        return True


class AgentNamespace(Namespace):
    """
    SocketIO namespace for agent connections.

    Agents connect to: /agent
    """

    def on_connect(self):
        """Handle agent connection attempt"""
        # Connection is not authenticated yet
        # Agent must send auth message first
        logger.info("New connection from %s", request.remote_addr)

    def on_disconnect(self):
        """Handle agent disconnection"""
        sid = request.sid
        logger.info("Disconnect: %s", sid)
        agent_registry.unregister_agent(sid, reason='disconnect')

    def on_auth(self, data):
        """
        Handle agent authentication.

        Expected data:
        {
            "type": "auth",
            "agent_id": "uuid",
            "api_key_prefix": "sk_xxx",
            "signature": "hmac_signature",
            "timestamp": unix_ms,
            "nonce": "unique_nonce" (optional but recommended)
        }
        """
        sid = request.sid
        ip_address = request.remote_addr
        if not _check_auth_rate_limit(ip_address):
            emit('auth_response', {'success': False, 'error': 'Rate limit exceeded'}, room=request.sid, namespace='/agent')
            return

        agent_id = data.get('agent_id')
        api_key_prefix = data.get('api_key_prefix')
        signature = data.get('signature')
        timestamp = data.get('timestamp', 0)
        nonce = data.get('nonce')  # Optional for backward compatibility

        ip_address = request.remote_addr
        logger.info("Auth attempt from agent %s at %s", agent_id, ip_address)

        if not all([agent_id, api_key_prefix, signature]):
            emit('auth_fail', {
                'type': 'auth_fail',
                'error': 'Missing required fields'
            })
            disconnect()
            return

        # Verify authentication (includes signature verification and replay protection)
        server = agent_registry.verify_agent_auth(
            agent_id, api_key_prefix, signature, timestamp,
            nonce=nonce, ip_address=ip_address
        )

        if not server:
            emit('auth_fail', {
                'type': 'auth_fail',
                'error': 'Authentication failed'
            })
            disconnect()
            return

        # Check IP allowlist
        if server.allowed_ips and len(server.allowed_ips) > 0:
            if not is_ip_allowed(ip_address, server.allowed_ips):
                # Log security event
                anomaly_detection_service.track_ip_blocked(
                    server.id, ip_address, server.allowed_ips
                )
                emit('auth_fail', {
                    'type': 'auth_fail',
                    'error': 'IP address not allowed'
                })
                logger.warning("IP %s blocked for server %s", ip_address, server.id)
                disconnect()
                return

        # Check for new IP and create info alert
        anomaly_detection_service.check_new_ip(server.id, ip_address)

        # Register agent
        agent_version = request.headers.get('User-Agent', '').replace('ServerKit-Agent/', '')

        session_token = agent_registry.register_agent(
            server_id=server.id,
            socket_id=sid,
            ip_address=ip_address,
            agent_version=agent_version
        )

        # register_agent returns None when the DB write failed and it rolled
        # back the in-memory state — don't tell the agent it's authenticated.
        if not session_token:
            emit('auth_fail', {
                'type': 'auth_fail',
                'error': 'Registration failed'
            })
            disconnect()
            return

        # Calculate token expiry (1 hour)
        expires = int((time.time() + 3600) * 1000)

        emit('auth_ok', {
            'type': 'auth_ok',
            'session_token': session_token,
            'expires': expires,
            'server_id': server.id
        })

        logger.info("Agent %s authenticated successfully from %s", agent_id, ip_address)

    def on_heartbeat(self, data):
        """
        Handle agent heartbeat.

        Expected data:
        {
            "type": "heartbeat",
            "metrics": {
                "cpu_percent": float,
                "memory_percent": float,
                "disk_percent": float,
                "container_count": int,
                "container_running": int
            }
        }
        """
        sid = request.sid
        agent = agent_registry.get_agent_by_socket(sid)

        if not agent:
            emit('error', {
                'type': 'error',
                'code': 'NOT_AUTHENTICATED',
                'message': 'Not authenticated'
            })
            return

        metrics = data.get('metrics', {})
        agent_registry.update_heartbeat(agent.server_id, metrics)

        emit('heartbeat_ack', {'type': 'heartbeat_ack'})

    def on_command_result(self, data):
        """
        Handle command result from agent.

        Expected data:
        {
            "type": "command_result",
            "command_id": "uuid",
            "success": bool,
            "data": any,
            "error": string,
            "duration": int (ms)
        }
        """
        sid = request.sid
        agent_registry.handle_command_result(sid, data)

    def on_system_info(self, data):
        """
        Handle system info update from agent.

        Expected data:
        {
            "type": "system_info",
            "info": {
                "hostname": string,
                "os": string,
                "os_version": string,
                "platform": string,
                "architecture": string,
                "cpu_cores": int,
                "cpu_model": string,
                "total_memory": int,
                "total_disk": int,
                "docker_version": string,
                "agent_version": string
            }
        }
        """
        sid = request.sid
        agent = agent_registry.get_agent_by_socket(sid)

        if not agent:
            emit('error', {
                'type': 'error',
                'code': 'NOT_AUTHENTICATED',
                'message': 'Not authenticated'
            })
            return

        info = data.get('info', {})
        agent_registry.update_system_info(agent.server_id, info)

    def on_capabilities(self, data):
        """
        Handle agent capability advertisement.

        Sent by the agent right after auth succeeds (and on every
        reconnect). The payload tells the panel which feature surfaces
        this agent can drive — cron, docker, systemd, etc. — and is
        used to filter target pickers in the UI.

        Expected data:
        {
            "type": "capabilities",
            "capabilities": {"docker": true, "cron": true, ...},
            "platform": "linux",
            "distro": "ubuntu",
            "distro_version": "22.04"
        }
        """
        sid = request.sid
        agent = agent_registry.get_agent_by_socket(sid)

        if not agent:
            emit('error', {
                'type': 'error',
                'code': 'NOT_AUTHENTICATED',
                'message': 'Not authenticated'
            })
            return

        # Capability side-effects (incl. the WireGuard tunnel reconcile)
        # happen inside update_capabilities so both transports — this WS
        # handler and the long-poll /poll body — share one ingest path.
        agent_registry.update_capabilities(agent.server_id, data or {})

    def on_stream(self, data):
        """
        Handle streaming data from agent (logs, metrics).

        Expected data:
        {
            "type": "stream",
            "channel": string,
            "data": any
        }
        """
        sid = request.sid
        agent = agent_registry.get_agent_by_socket(sid)

        if not agent:
            return

        channel = data.get('channel')
        stream_data = data.get('data')

        # A malformed/partial stream frame — exactly what the poll fallback
        # exists to tolerate — can omit or null the channel. Calling
        # .startswith on a non-string would raise AttributeError; drop the
        # frame instead of letting the handler crash.
        if not isinstance(channel, str) or not channel:
            return

        # Broadcast to subscribers
        # The channel format determines where to broadcast:
        # - "metrics" -> room: f"server_{server_id}_metrics"
        # - "container:xxx:logs" -> room: f"server_{server_id}_container_logs"

        if channel == 'metrics':
            room = f"server_{agent.server_id}_metrics"
        elif channel.startswith('container:') and channel.endswith(':logs'):
            parts = channel.split(':')
            if len(parts) < 3:
                return
            container_id = parts[1]
            room = f"server_{agent.server_id}_container_{container_id}_logs"
        else:
            room = f"server_{agent.server_id}_{channel}"

        # Emit to the main namespace for UI clients
        from app import get_socketio
        socketio = get_socketio()
        if socketio:
            socketio.emit(
                'server_stream',
                {
                    'server_id': agent.server_id,
                    'channel': channel,
                    'data': stream_data
                },
                room=room
            )

    def on_error(self, data):
        """Handle error message from agent"""
        sid = request.sid
        agent = agent_registry.get_agent_by_socket(sid)

        if agent:
            logger.warning("Error from server %s: %s", agent.server_id, data)

    def on_credential_update_ack(self, data):
        """
        Handle credential update acknowledgment from agent.

        Expected data:
        {
            "type": "credential_update_ack",
            "rotation_id": "uuid",
            "success": bool,
            "error": string (optional)
        }
        """
        sid = request.sid
        agent = agent_registry.get_agent_by_socket(sid)

        if not agent:
            emit('error', {
                'type': 'error',
                'code': 'NOT_AUTHENTICATED',
                'message': 'Not authenticated'
            })
            return

        rotation_id = data.get('rotation_id')
        success = data.get('success', False)
        error = data.get('error')

        logger.info("Credential update ack from %s: success=%s", agent.server_id, success)

        if not rotation_id:
            emit('error', {
                'type': 'error',
                'code': 'MISSING_ROTATION_ID',
                'message': 'Missing rotation_id'
            })
            return

        try:
            from app import db
            server = Server.query.get(agent.server_id)

            if not server:
                return

            if success:
                # Complete the rotation
                if server.complete_key_rotation(rotation_id):
                    db.session.commit()
                    logger.info("Key rotation completed for server %s", server.id)

                    # Clear nonces for this server since we have new credentials
                    from app.services.nonce_service import nonce_service
                    nonce_service.clear_server_nonces(server.id)
                else:
                    logger.warning("Key rotation completion failed for server %s", server.id)
            else:
                # Agent failed to update credentials, cancel rotation
                server.cancel_key_rotation()
                db.session.commit()
                logger.info("Key rotation cancelled for server %s: %s", server.id, error)

        except Exception:
            # Roll back the poisoned session so the next DB user on this
            # worker doesn't inherit a broken transaction.
            from app import db
            db.session.rollback()
            logger.exception("Error handling credential update ack")


def init_agent_gateway(socketio):
    """Initialize the agent gateway namespace"""
    agent_registry.init_socketio(socketio)
    socketio.on_namespace(AgentNamespace('/agent'))
    logger.info("Agent gateway initialized on /agent namespace")
