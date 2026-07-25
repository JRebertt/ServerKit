"""Plugin-facing SDK for running commands on managed servers.

    from app.plugins_sdk import agents

    fleet = agents.for_plugin('serverkit-gui')
    shot = fleet.run(server_id, 'gui:screenshot', {'display': ':0'},
                     requires='gui.screenshot')

Without this, an extension was effectively local-panel-only: everything it
could do stopped at the machine the panel runs on, which is at odds with a
product built around a fleet.

**This is where ``agent.command:<action>`` finally means something.** The
manifest permission has existed as a declaration — surfaced at install time for
consent — with nothing enforcing it, because plugins called the agent registry
directly. Going through the SDK checks it before dispatch, so a plugin can only
run the actions it asked the operator for, by name.

The panel's own guarantees still apply underneath and are not re-implemented
here: the per-server ACL decides whether that server permits the action at all,
and every command is recorded as a ServerCommand row — pass ``user_id`` so it
is attributable to a person rather than to "the panel".

``run()`` returns the agent's payload and raises :class:`AgentCommandError` for
anything else, with ``.code`` carrying why (``AGENT_OFFLINE``,
``PERMISSION_DENIED``, ``TIMEOUT``, ``UNSUPPORTED``, ...). It also unwraps the
double envelope: a transport-successful reply can still carry a handler failure
inside, which is easy to miss and reads as success.
"""

import logging

logger = logging.getLogger(__name__)

#: Longer than the registry's own 30s default on purpose. An agent on the HTTP
#: long-poll fallback can sit up to ~25s before it even sees the command, which
#: leaves a 30s budget almost no room to run anything.
DEFAULT_TIMEOUT = 45.0


class AgentCommandError(RuntimeError):
    """A command that did not reach the agent, or did not succeed there."""

    def __init__(self, message, code=None, data=None):
        super().__init__(message)
        self.code = code or 'AGENT_ERROR'
        self.data = data


class BoundAgents:
    """The fleet as seen by one plugin. Get it from ``agents.for_plugin()``."""

    def __init__(self, slug):
        if not slug or not isinstance(slug, str):
            raise ValueError('an agent surface needs a plugin slug')
        self.slug = slug

    # ------------------------------------------------------------------ read
    def online(self):
        """Server ids with a live agent connection."""
        return list(_registry().get_connected_servers())

    def is_online(self, server_id):
        """True if *server_id* has a live agent connection."""
        return bool(_registry().is_agent_connected(server_id))

    def capabilities(self, server_id):
        """What the agent on *server_id* reports it can do (``{}`` if unknown)."""
        return _registry().get_capabilities(server_id) or {}

    def has_capability(self, server_id, capability):
        """True if the agent on *server_id* reports *capability*."""
        return bool(_registry().has_capability(server_id, capability))

    # ------------------------------------------------------------------- run
    def run(self, server_id, action, params=None, timeout=DEFAULT_TIMEOUT,
            user_id=None, requires=None):
        """Run *action* on *server_id* and return the agent's payload.

        Raises :class:`AgentCommandError` if the command didn't run or didn't
        succeed. Declare ``agent.command:<action>`` in your manifest first —
        verbatim, so ``gui:screenshot`` is ``agent.command:gui:screenshot``.

        Pass *requires* to check the agent reports a capability before
        dispatching, so an old agent fails with a clear reason instead of an
        unknown-action error from the far side.
        """
        if not server_id:
            raise AgentCommandError('No server given', code='NO_SERVER')
        if not action:
            raise AgentCommandError('No action given', code='NO_ACTION')

        # The gate the manifest has been promising all along.
        from app.plugins_sdk import permissions
        permissions.require(self.slug, f'agent.command:{action}')

        registry = _registry()
        if not registry.is_agent_connected(server_id):
            raise AgentCommandError(
                f'No agent connected for server {server_id}', code='AGENT_OFFLINE')
        if requires and not registry.has_capability(server_id, requires):
            raise AgentCommandError(
                f"The agent on {server_id} does not support '{requires}'",
                code='UNSUPPORTED')

        result = registry.send_command(
            server_id=server_id, action=action, params=params or {},
            timeout=float(timeout), user_id=user_id,
        ) or {}

        if not result.get('success'):
            raise AgentCommandError(
                result.get('error') or f'Agent command failed: {action}',
                code=result.get('code'), data=result.get('data'))

        data = result.get('data')
        if isinstance(data, dict) and data.get('success') is False:
            # Transport succeeded, the handler on the far side did not. Easy to
            # miss, and it reads as success to anyone checking only the outer
            # envelope.
            raise AgentCommandError(
                data.get('error') or f'Agent command failed: {action}',
                code=data.get('code') or 'HANDLER_ERROR', data=data)
        return data


class AgentsSdk:
    """Stable fleet surface for plugins."""

    #: Raised by :meth:`BoundAgents.run`; exposed so a plugin can catch it
    #: without importing a host module path.
    CommandError = AgentCommandError
    DEFAULT_TIMEOUT = DEFAULT_TIMEOUT

    def for_plugin(self, slug):
        """The fleet surface for *slug*, gated by that plugin's permissions."""
        return BoundAgents(slug)


def _registry():
    from app.services.agent_registry import agent_registry
    return agent_registry


agents = AgentsSdk()
