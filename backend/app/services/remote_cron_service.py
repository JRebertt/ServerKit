"""
Remote Cron Service

Mirrors the local CronService surface but routes through the agent
registry so callers can target a remote server. Keeps the local-only
CronService unchanged — it still serves /api/v1/cron/* (the panel host
itself).

Action mapping (panel → agent):
    cron:status   -> Status struct {available, running, daemon, reason}
    cron:list     -> {jobs: [Entry, ...]}
    cron:add      -> Entry
    cron:update   -> Entry (NEW id — agent ids are content-derived)
    cron:remove   -> {success: true}
    cron:toggle   -> {success: true, enabled}

cron:update is the first cron verb gated on a v2 capability (cron.update,
plan 28): agents older than 1.2.0 never advertise it, so we refuse cleanly
with a friendly "agent too old" 503 rather than dispatching a command the
agent will reject as unknown.

The agent is the source of truth for what's actually in the user's
crontab. We intentionally do NOT cache results here — every call
round-trips so the UI can't display stale state.
"""

from typing import Any, Dict, Optional

from app.services.agent_registry import agent_registry
from app.services.remote_command_dispatcher import dispatch_agent_command


class RemoteCronService:
    """Thin dispatcher to agent cron handlers."""

    @staticmethod
    def status(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(server_id, 'cron:status', user_id=user_id, timeout=8.0)

    @staticmethod
    def list_jobs(server_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(server_id, 'cron:list', user_id=user_id, timeout=8.0)

    @staticmethod
    def add_job(server_id: str, schedule: str, command: str,
                name: Optional[str] = None, description: Optional[str] = None,
                user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'cron:add',
            params={
                'schedule': schedule,
                'command': command,
                'name': name or '',
                'description': description or '',
            },
            user_id=user_id,
        )

    UPDATE_CAPABILITY = 'cron.update'

    @staticmethod
    def update_job(server_id: str, job_id: str, schedule: Optional[str] = None,
                   command: Optional[str] = None, name: Optional[str] = None,
                   user_id: Optional[int] = None) -> Dict[str, Any]:
        """Edit an existing remote cron entry. Agent ids are content-derived,
        so a schedule/command change returns a fresh Entry (new id) the
        caller must adopt.

        Only fields explicitly provided (non-None) are sent, so the agent
        leaves the rest unchanged. Refuses cleanly on an agent too old to
        advertise cron.update (Decision: first v2 key outside doctor/survey)."""
        if not agent_registry.has_capability(server_id, RemoteCronService.UPDATE_CAPABILITY):
            return {
                'success': False,
                'code': 'CRON_UPDATE_UNSUPPORTED',
                'error': 'This agent is too old to edit cron jobs in place. '
                         'Upgrade the agent to 1.2.0 or newer.',
            }

        params = {'id': job_id}
        if schedule is not None:
            params['schedule'] = schedule
        if command is not None:
            params['command'] = command
        if name is not None:
            params['name'] = name

        return dispatch_agent_command(
            server_id, 'cron:update',
            params=params,
            user_id=user_id,
        )

    @staticmethod
    def remove_job(server_id: str, job_id: str,
                   user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'cron:remove',
            params={'id': job_id},
            user_id=user_id,
        )

    @staticmethod
    def toggle_job(server_id: str, job_id: str, enabled: bool,
                   user_id: Optional[int] = None) -> Dict[str, Any]:
        return dispatch_agent_command(
            server_id, 'cron:toggle',
            params={'id': job_id, 'enabled': bool(enabled)},
            user_id=user_id,
        )
