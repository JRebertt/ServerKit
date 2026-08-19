"""Allowlisted remote repairs over the agent (plan 26 Phase 5, Decision 6).

Remote mutations are dangerous, so they go through an explicit allowlist that
maps a repair *kind* → the agent command it dispatches + the capability the
agent must advertise + the specific targets allowed. Anything not on the
allowlist is refused server-side, capability gaps are refused cleanly (never
errored — Decision 2), and **every** attempt that reaches an agent is
audit-logged.

The v1 allowlist is service-restart only (``fleet.service`` →
``systemd:restart`` for the core services), matching the fleet doctor's
repairable rows. The permission scope is enforced by ``send_command`` itself
(it checks ``Server.has_permission(action)`` before dispatch); this layer adds
the capability gate, the target allowlist, and the audit trail on top.

See ``docs/FLEET_CONTRACT.md`` (rule 6).
"""
import logging

from app.services.agent_registry import agent_registry
from app.services.remote_command_dispatcher import dispatch_agent_command

logger = logging.getLogger(__name__)

# Core host services a fleet repair is allowed to restart (matches the fleet
# doctor's repairable ``service.<name>`` rows).
_REPAIRABLE_SERVICES = ('nginx', 'docker')

# repair kind -> dispatch spec. Everything a remote mutation needs is declared
# here so the repair path is entirely data-driven and nothing outside this map
# can be dispatched.
_ALLOWLIST = {
    'fleet.service': {
        'action': 'systemd:restart',
        'capability': 'systemd.restart',
        'permission': 'systemd:restart',
        'targets': _REPAIRABLE_SERVICES,
        'timeout': 130.0,
        'param_key': 'unit',
        'item_key': 'name',
    },
}

AUDIT_ACTION = 'doctor.fleet.repair'


class FleetRepairService:
    """Dispatch an allowlisted remote repair and audit it."""

    @staticmethod
    def is_allowlisted(kind):
        return kind in _ALLOWLIST

    @classmethod
    def repair(cls, item, user_id=None):
        """Execute one allowlisted remote repair.

        ``item`` = ``{'kind': 'fleet.service', 'server_id': ..., 'name': ...}``.
        Returns ``{'success': bool, ...}``. Refusals (not allowlisted, unknown
        target, offline, capability missing) return ``success: False`` with a
        code and are NOT dispatched to the agent.
        """
        kind = (item or {}).get('kind')
        spec = _ALLOWLIST.get(kind)
        if not spec:
            return {'success': False,
                    'error': f'Repair kind not allowlisted: {kind}',
                    'code': 'NOT_ALLOWLISTED'}

        server_id = item.get('server_id')
        target = item.get(spec['item_key'])
        if not server_id:
            return {'success': False, 'error': 'server_id is required',
                    'code': 'BAD_REQUEST'}
        if target not in spec['targets']:
            return {'success': False,
                    'error': f'Target not repairable: {target}',
                    'code': 'NOT_ALLOWLISTED'}

        from app.models.server import Server
        server = Server.query.get(server_id)
        if server is None:
            return {'success': False, 'error': 'Unknown server',
                    'code': 'NOT_FOUND'}

        if not agent_registry.is_agent_connected(server_id):
            return {'success': False, 'error': 'Agent is offline',
                    'code': 'AGENT_OFFLINE'}

        if not agent_registry.has_capability(server_id, spec['capability']):
            return {'success': False,
                    'error': f"Agent does not support {spec['capability']}"
                             f" (older agent — upgrade to enable remote repair)",
                    'code': 'UNSUPPORTED'}

        result = dispatch_agent_command(
            server_id,
            spec['action'],
            {spec['param_key']: target},
            timeout=spec['timeout'],
            user_id=user_id,
        )
        ok = bool(result.get('success'))

        cls._audit(user_id, server_id, kind, target, ok, result)

        if ok:
            return {'success': True, 'restarted': target, 'server_id': server_id}
        return {'success': False,
                'error': result.get('error') or f"{spec['action']} failed",
                'code': result.get('code')}

    @staticmethod
    def _audit(user_id, server_id, kind, target, ok, result):
        try:
            from app.services.audit_service import AuditService
            AuditService.log(
                action=AUDIT_ACTION,
                user_id=user_id,
                target_type='server',
                details={
                    'server_id': server_id,
                    'kind': kind,
                    'service': target,
                    'success': ok,
                    'error': result.get('error'),
                    'code': result.get('code'),
                },
            )
        except Exception as e:  # noqa: BLE001 — auditing must never break repair
            logger.warning('could not audit fleet repair for %s: %s', server_id, e)
