"""
AgentFleet Service

Manages agent fleet operations including bulk upgrades, staged rollouts,
health monitoring, offline command queuing, and retry with backoff.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import threading
import time
import uuid

from app import db
from app.models.server import (
    Server, ServerGroup, AgentVersion, ServerCommand, AgentSession, AgentRollout
)
from app.services.agent_registry import agent_registry


class AgentFleetService:
    """Service for managing a fleet of agents."""

    def __init__(self):
        self._rollout_threads = {}
        self._rollout_cancel = {}  # rollout_id -> threading.Event

    # ==================== Fleet Health ====================

    def get_fleet_health(self) -> Dict:
        """Get aggregated health metrics for the entire fleet."""
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)

        servers = Server.query.all()
        total_count = len(servers)

        online_count = sum(1 for s in servers if s.status == 'online')
        offline_count = sum(1 for s in servers if s.status == 'offline')
        pending_count = sum(1 for s in servers if s.status == 'pending')

        # Real heartbeat latency from active sessions. No sessions -> None:
        # "0.0 ms" would be a perfect-latency reading, not an absence of data.
        active_sessions = AgentSession.query.filter_by(is_active=True).all()
        latencies = [s.avg_latency_ms for s in active_sessions if s.avg_latency_ms is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else None

        # Command success rate in the last hour. No commands -> None:
        # "100% success" would be a claim, not an observation.
        commands = ServerCommand.query.filter(ServerCommand.created_at >= one_hour_ago).all()
        if commands:
            success_count = sum(1 for c in commands if c.status == 'completed')
            command_success_rate = (success_count / len(commands)) * 100
        else:
            command_success_rate = None

        # Queued commands count
        queued_count = ServerCommand.query.filter_by(queued=True, status='pending').count()

        return {
            'total_servers': total_count,
            'online_servers': online_count,
            'offline_servers': offline_count,
            'pending_servers': pending_count,
            'uptime_percentage': (online_count / total_count * 100) if total_count > 0 else 100,
            'avg_heartbeat_latency': round(avg_latency, 1) if avg_latency is not None else None,
            'command_success_rate': round(command_success_rate, 1) if command_success_rate is not None else None,
            'queued_commands': queued_count,
            'version_distribution': self._get_version_distribution(servers)
        }

    def _get_version_distribution(self, servers: List[Server]) -> Dict[str, int]:
        """Calculate distribution of agent versions."""
        dist = {}
        for s in servers:
            version = s.agent_version or 'unknown'
            dist[version] = dist.get(version, 0) + 1
        return dist

    # ==================== Upgrades ====================

    def upgrade_servers(self, server_ids: List[str], version_id: Optional[str] = None, user_id: int = None) -> Dict:
        """Trigger upgrades for a list of servers."""
        version = None
        if version_id:
            version = AgentVersion.query.get(version_id)
        else:
            version = AgentVersion.query.filter_by(
                channel='stable', is_active=True
            ).order_by(AgentVersion.version.desc()).first()

        if not version:
            return {'success': False, 'error': 'No suitable agent version found'}

        results = []
        for server_id in server_ids:
            server = Server.query.get(server_id)
            if not server:
                results.append({'server_id': server_id, 'success': False, 'error': 'Server not found'})
                continue

            platform = f"{server.os_type}-{server.architecture}"
            download_url = version.assets.get(platform) if version.assets else None

            if not download_url:
                results.append({'server_id': server_id, 'success': False, 'error': f'No asset for platform {platform}'})
                continue

            params = {
                'version': version.version,
                'download_url': download_url,
                'checksums_url': version.assets.get('checksums') if version.assets else None
            }

            if server.status != 'online':
                # Queue command for offline agent
                self.queue_command(server_id, 'agent:update', params, user_id=user_id)
                results.append({'server_id': server_id, 'success': True, 'message': 'Upgrade queued (agent offline)'})
                continue

            threading.Thread(
                target=agent_registry.send_command,
                args=(server_id, 'agent:update', params),
                kwargs={'user_id': user_id, 'timeout': 60.0},
                daemon=True
            ).start()

            results.append({'server_id': server_id, 'success': True, 'message': 'Upgrade triggered'})

        return {'success': True, 'results': results}

    # ==================== Staged Rollouts ====================

    def staged_rollout(
        self, group_id: str, version_id: str,
        batch_size: int = 5, delay_minutes: int = 10,
        strategy: str = 'staged', user_id: int = None,
        server_ids: List[str] = None
    ) -> Dict:
        """Perform a staged rollout of an agent version."""
        version = AgentVersion.query.get(version_id)
        if not version:
            return {'success': False, 'error': 'Version not found'}

        if group_id:
            group = ServerGroup.query.get(group_id)
            if not group:
                return {'success': False, 'error': 'Group not found'}
            target_servers = Server.query.filter_by(group_id=group_id, status='online').all()
        elif server_ids:
            target_servers = Server.query.filter(
                Server.id.in_(server_ids), Server.status == 'online'
            ).all()
        else:
            target_servers = Server.query.filter_by(status='online').all()

        if not target_servers:
            return {'success': True, 'message': 'No online servers to upgrade'}

        ids = [s.id for s in target_servers]

        # Create persistent rollout record
        rollout = AgentRollout(
            version_id=version_id,
            group_id=group_id,
            user_id=user_id,
            batch_size=batch_size,
            delay_minutes=delay_minutes,
            strategy=strategy,
            status='running',
            total_servers=len(ids),
            started_at=datetime.utcnow()
        )
        db.session.add(rollout)
        db.session.commit()

        rollout_id = rollout.id

        # Setup cancellation
        cancel_event = threading.Event()
        self._rollout_cancel[rollout_id] = cancel_event

        thread = threading.Thread(
            target=self._run_staged_rollout,
            args=(rollout_id, ids, version_id, batch_size, delay_minutes, user_id, cancel_event),
            daemon=True
        )
        self._rollout_threads[rollout_id] = thread
        thread.start()

        return {'success': True, 'rollout_id': rollout_id, 'rollout': rollout.to_dict()}

    def _run_staged_rollout(self, rollout_id, server_ids, version_id, batch_size, delay_minutes, user_id, cancel_event):
        """Run staged rollout in batches with health checks between waves."""
        from app import create_app
        app = create_app()

        with app.app_context():
            total = len(server_ids)
            processed = 0
            failed = 0
            wave = 0
            server_results = []

            for i in range(0, total, batch_size):
                if cancel_event.is_set():
                    self._update_rollout_status(rollout_id, 'cancelled', processed, failed, wave, server_results)
                    return

                batch = server_ids[i:i + batch_size]
                wave += 1

                # Upgrade this batch
                result = self.upgrade_servers(batch, version_id, user_id)
                batch_results = result.get('results', [])

                for r in batch_results:
                    server_results.append({
                        'server_id': r['server_id'],
                        'status': 'success' if r.get('success') else 'failed',
                        'error': r.get('error'),
                        'wave': wave
                    })
                    if not r.get('success'):
                        failed += 1

                processed += len(batch)

                # Update rollout progress
                self._update_rollout_status(rollout_id, 'running', processed, failed, wave, server_results)

                if processed < total:
                    # Health check: if more than 50% of current wave failed, abort
                    wave_failures = sum(1 for r in batch_results if not r.get('success'))
                    if wave_failures > len(batch) * 0.5:
                        self._update_rollout_status(
                            rollout_id, 'failed', processed, failed, wave, server_results,
                            error=f'Wave {wave} had >50% failures ({wave_failures}/{len(batch)}), aborting rollout'
                        )
                        return

                    # Wait between waves, checking for cancellation
                    wait_seconds = delay_minutes * 60
                    if cancel_event.wait(timeout=wait_seconds):
                        self._update_rollout_status(rollout_id, 'cancelled', processed, failed, wave, server_results)
                        return

                    # Post-wave health check: verify previous batch servers are still online
                    offline_count = 0
                    for sid in batch:
                        server = Server.query.get(sid)
                        if server and server.status != 'online':
                            offline_count += 1

                    if offline_count > len(batch) * 0.3:
                        self._update_rollout_status(
                            rollout_id, 'failed', processed, failed, wave, server_results,
                            error=f'Post-wave health check failed: {offline_count}/{len(batch)} servers offline after wave {wave}'
                        )
                        return

            self._update_rollout_status(rollout_id, 'completed', processed, failed, wave, server_results)

    def _update_rollout_status(self, rollout_id, status, processed, failed, wave, server_results, error=None):
        """Update rollout record in database."""
        try:
            rollout = AgentRollout.query.get(rollout_id)
            if rollout:
                rollout.status = status
                rollout.processed_servers = processed
                rollout.failed_servers = failed
                rollout.current_wave = wave
                rollout.server_results = server_results
                rollout.error = error
                if status in ('completed', 'failed', 'cancelled'):
                    rollout.completed_at = datetime.utcnow()
                db.session.commit()
        except Exception as e:
            print(f"Error updating rollout status: {e}")
            db.session.rollback()

    def cancel_rollout(self, rollout_id: str) -> bool:
        """Cancel an active rollout."""
        cancel_event = self._rollout_cancel.get(rollout_id)
        if cancel_event:
            cancel_event.set()
            return True

        # Try to cancel in DB directly if thread already finished
        rollout = AgentRollout.query.get(rollout_id)
        if rollout and rollout.status == 'running':
            rollout.status = 'cancelled'
            rollout.completed_at = datetime.utcnow()
            db.session.commit()
            return True

        return False

    def get_rollouts(self, status: str = None, limit: int = 20) -> List[Dict]:
        """Get rollout history."""
        query = AgentRollout.query.order_by(AgentRollout.created_at.desc())
        if status:
            query = query.filter_by(status=status)
        rollouts = query.limit(limit).all()
        return [r.to_dict() for r in rollouts]

    def get_rollout(self, rollout_id: str) -> Optional[Dict]:
        """Get a specific rollout."""
        rollout = AgentRollout.query.get(rollout_id)
        return rollout.to_dict() if rollout else None

    # ==================== Registration ====================

    def approve_registration(self, server_id: str, user_id: int) -> bool:
        """Approve a pending agent registration."""
        server = Server.query.get(server_id)
        if not server or server.status != 'pending':
            return False

        server.status = 'connecting'
        server.registered_by = user_id
        server.registered_at = datetime.utcnow()
        db.session.commit()
        return True

    def reject_registration(self, server_id: str) -> bool:
        """Reject and delete a pending agent registration."""
        server = Server.query.get(server_id)
        if not server or server.status != 'pending':
            return False

        db.session.delete(server)
        db.session.commit()
        return True

    # ==================== Offline Command Queue ====================

    def queue_command(
        self, server_id: str, action: str, params: dict = None,
        user_id: int = None, max_retries: int = 3, backoff_seconds: int = 30
    ) -> ServerCommand:
        """Queue a command for an offline agent. Delivered on reconnect."""
        command = ServerCommand(
            id=str(uuid.uuid4()),
            server_id=server_id,
            user_id=user_id,
            command_type=action,
            command_data=params,
            status='pending',
            queued=True,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds
        )
        db.session.add(command)
        db.session.commit()
        return command

    def deliver_queued_commands(self, server_id: str):
        """Deliver all queued commands for a server that just reconnected."""
        commands = ServerCommand.query.filter_by(
            server_id=server_id, queued=True, status='pending'
        ).order_by(ServerCommand.created_at.asc()).all()

        for cmd in commands:
            cmd.queued = False
            cmd.status = 'running'
            cmd.started_at = datetime.utcnow()
            db.session.commit()

            # Send asynchronously
            threading.Thread(
                target=self._deliver_single_command,
                args=(server_id, cmd.id, cmd.command_type, cmd.command_data, cmd.user_id),
                daemon=True
            ).start()

    def _deliver_single_command(self, server_id, command_id, action, params, user_id):
        """Send a single queued command and update its status."""
        from app import create_app
        app = create_app()

        with app.app_context():
            result = agent_registry.send_command(
                server_id, action, params, user_id=user_id, timeout=60.0
            )

            try:
                cmd = ServerCommand.query.get(command_id)
                if cmd:
                    if result.get('success'):
                        cmd.status = 'completed'
                        cmd.result = result.get('data')
                    else:
                        cmd.status = 'failed'
                        cmd.error = result.get('error')
                    cmd.completed_at = datetime.utcnow()
                    db.session.commit()
            except Exception as e:
                print(f"Error updating queued command: {e}")
                db.session.rollback()

    def get_queued_commands(self, server_id: str = None) -> List[Dict]:
        """Get all pending queued commands, optionally filtered by server."""
        query = ServerCommand.query.filter_by(queued=True, status='pending')
        if server_id:
            query = query.filter_by(server_id=server_id)
        return [c.to_dict() for c in query.order_by(ServerCommand.created_at.asc()).all()]

    # ==================== Command Retry ====================

    def retry_command(self, command_id: str) -> Dict:
        """Retry a failed command with exponential backoff."""
        cmd = ServerCommand.query.get(command_id)
        if not cmd:
            return {'success': False, 'error': 'Command not found'}

        if cmd.status not in ('failed', 'timeout'):
            return {'success': False, 'error': f'Cannot retry command with status: {cmd.status}'}

        if cmd.retry_count >= cmd.max_retries:
            return {'success': False, 'error': f'Max retries ({cmd.max_retries}) exceeded'}

        server = Server.query.get(cmd.server_id)
        if not server:
            return {'success': False, 'error': 'Server not found'}

        cmd.retry_count += 1

        if server.status != 'online':
            # Re-queue for offline delivery
            cmd.queued = True
            cmd.status = 'pending'
            # Exponential backoff for next_retry_at
            backoff = cmd.backoff_seconds * (2 ** (cmd.retry_count - 1))
            cmd.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff)
            db.session.commit()
            return {'success': True, 'message': 'Command re-queued (agent offline)', 'retry_count': cmd.retry_count}

        # Agent is online, send immediately
        cmd.status = 'running'
        cmd.started_at = datetime.utcnow()
        db.session.commit()

        threading.Thread(
            target=self._deliver_single_command,
            args=(cmd.server_id, cmd.id, cmd.command_type, cmd.command_data, cmd.user_id),
            daemon=True
        ).start()

        return {'success': True, 'message': 'Command retry triggered', 'retry_count': cmd.retry_count}

    def process_scheduled_retries(self):
        """Process commands that are due for retry. Call periodically."""
        now = datetime.utcnow()
        commands = ServerCommand.query.filter(
            ServerCommand.status == 'pending',
            ServerCommand.queued == True,
            ServerCommand.next_retry_at != None,
            ServerCommand.next_retry_at <= now
        ).all()

        for cmd in commands:
            server = Server.query.get(cmd.server_id)
            if server and server.status == 'online':
                cmd.queued = False
                cmd.status = 'running'
                cmd.started_at = datetime.utcnow()
                db.session.commit()

                threading.Thread(
                    target=self._deliver_single_command,
                    args=(cmd.server_id, cmd.id, cmd.command_type, cmd.command_data, cmd.user_id),
                    daemon=True
                ).start()

    # ==================== Diagnostics ====================

    def get_server_diagnostics(self, server_id: str) -> Dict:
        """Get detailed connection diagnostics for a server."""
        server = Server.query.get(server_id)
        if not server:
            return {'error': 'Server not found'}

        # Active session
        active_session = AgentSession.query.filter_by(
            server_id=server_id, is_active=True
        ).first()

        # Recent sessions (last 10)
        recent_sessions = AgentSession.query.filter_by(
            server_id=server_id
        ).order_by(AgentSession.connected_at.desc()).limit(10).all()

        # Command stats (last 24h)
        one_day_ago = datetime.utcnow() - timedelta(hours=24)
        recent_commands = ServerCommand.query.filter(
            ServerCommand.server_id == server_id,
            ServerCommand.created_at >= one_day_ago
        ).all()

        total_cmds = len(recent_commands)
        success_cmds = sum(1 for c in recent_commands if c.status == 'completed')
        failed_cmds = sum(1 for c in recent_commands if c.status == 'failed')
        timeout_cmds = sum(1 for c in recent_commands if c.status == 'timeout')

        # Calculate uptime from sessions
        uptime_seconds = 0
        for session in recent_sessions:
            start = session.connected_at or session.connected_at
            end = session.disconnected_at or datetime.utcnow()
            uptime_seconds += (end - start).total_seconds()

        # Queued commands for this server
        queued = ServerCommand.query.filter_by(
            server_id=server_id, queued=True, status='pending'
        ).count()

        return {
            'server_id': server_id,
            'server_name': server.name,
            'status': server.status,
            'agent_version': server.agent_version,
            'last_seen': server.last_seen.isoformat() if server.last_seen else None,
            'connection': {
                'is_connected': active_session is not None,
                'current_latency_ms': active_session.heartbeat_latency_ms if active_session else None,
                'avg_latency_ms': active_session.avg_latency_ms if active_session else None,
                'connected_since': active_session.connected_at.isoformat() if active_session else None,
                'ip_address': active_session.ip_address if active_session else server.ip_address,
            },
            'commands_24h': {
                'total': total_cmds,
                'success': success_cmds,
                'failed': failed_cmds,
                'timeout': timeout_cmds,
                'success_rate': round((success_cmds / total_cmds * 100), 1) if total_cmds > 0 else 100.0,
            },
            'queued_commands': queued,
            'uptime_seconds_24h': round(uptime_seconds),
            'recent_sessions': [s.to_dict() for s in recent_sessions],
        }


fleet_service = AgentFleetService()
