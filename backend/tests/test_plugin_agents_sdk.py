"""Running agent commands from a plugin (plugins_sdk.agents).

Two things this pins down:

* An extension can reach the fleet at all. Before it, everything a plugin could
  do stopped at the machine the panel runs on.
* ``agent.command:<action>`` is now enforced. The manifest permission existed as
  a declaration shown at install time, with nothing checking it — plugins called
  the agent registry directly. Going through the SDK makes the consent dialog
  mean what it says.
"""

import pytest

from app import db
from app.plugins_sdk import permissions
from app.plugins_sdk.agents_sdk import AgentCommandError, agents
from app.services import agent_registry as agent_registry_module

SERVER = 'server-uuid-1'


@pytest.fixture
def installed(app):
    """An installed plugin declaring one agent-command permission."""
    from app.models.plugin import InstalledPlugin

    plugin = InstalledPlugin(slug='serverkit-demo', name='serverkit-demo',
                             display_name='Demo', version='1.0.0',
                             status=InstalledPlugin.STATUS_ACTIVE)
    plugin.manifest = {'permissions': ['agent.command:gui:screenshot']}
    db.session.add(plugin)
    db.session.commit()
    return agents.for_plugin('serverkit-demo')


@pytest.fixture
def fleet(monkeypatch):
    """A connected agent whose responses each test can steer."""
    registry = agent_registry_module.agent_registry
    state = {'sent': [], 'reply': {'success': True, 'data': {'png': 'base64...'}},
             'connected': True, 'capabilities': {'gui.screenshot': True}}

    def _send(server_id, action, params=None, timeout=None, user_id=None):
        state['sent'].append({'server_id': server_id, 'action': action,
                              'params': params, 'timeout': timeout,
                              'user_id': user_id})
        return state['reply']

    monkeypatch.setattr(registry, 'send_command', _send)
    monkeypatch.setattr(registry, 'is_agent_connected',
                        lambda sid: state['connected'])
    monkeypatch.setattr(registry, 'get_capabilities',
                        lambda sid: state['capabilities'])
    monkeypatch.setattr(registry, 'has_capability',
                        lambda sid, cap: bool(state['capabilities'].get(cap)))
    monkeypatch.setattr(registry, 'get_connected_servers',
                        lambda: [SERVER] if state['connected'] else [])
    return state


class TestPermissionGate:
    def test_a_declared_action_is_allowed(self, app, installed, fleet):
        assert installed.run(SERVER, 'gui:screenshot') == {'png': 'base64...'}

    def test_an_undeclared_action_is_refused_before_dispatch(self, app, installed, fleet):
        with pytest.raises(permissions.PermissionDenied):
            installed.run(SERVER, 'file:write', {'path': '/etc/passwd'})
        # Refused, not merely reported: nothing reached the agent.
        assert fleet['sent'] == []

    def test_the_permission_is_matched_verbatim(self, app, installed, fleet):
        # 'agent.command:gui:screenshot' must not also authorise 'gui:record'
        # just because it shares a prefix.
        with pytest.raises(permissions.PermissionDenied):
            installed.run(SERVER, 'gui:record')

    def test_an_uninstalled_plugin_has_no_permissions(self, app, fleet):
        with pytest.raises(permissions.PermissionDenied):
            agents.for_plugin('never-installed').run(SERVER, 'gui:screenshot')


class TestDispatch:
    def test_passes_through_params_and_attribution(self, app, installed, fleet):
        installed.run(SERVER, 'gui:screenshot', {'display': ':0'}, user_id=42)

        sent = fleet['sent'][0]
        assert sent['params'] == {'display': ':0'}
        # user_id is what makes the ServerCommand audit row name a person.
        assert sent['user_id'] == 42

    def test_default_timeout_leaves_room_for_a_polling_agent(self, app, installed, fleet):
        installed.run(SERVER, 'gui:screenshot')
        # A poll-transport agent can sit ~25s before it sees the command.
        assert fleet['sent'][0]['timeout'] >= 45.0

    def test_offline_agent_is_refused_without_dispatching(self, app, installed, fleet):
        fleet['connected'] = False
        with pytest.raises(AgentCommandError) as excinfo:
            installed.run(SERVER, 'gui:screenshot')
        assert excinfo.value.code == 'AGENT_OFFLINE'
        assert fleet['sent'] == []

    def test_a_missing_capability_is_refused_with_a_reason(self, app, installed, fleet):
        fleet['capabilities'] = {}
        with pytest.raises(AgentCommandError) as excinfo:
            installed.run(SERVER, 'gui:screenshot', requires='gui.screenshot')
        # Better than an unknown-action error from the far side.
        assert excinfo.value.code == 'UNSUPPORTED'
        assert fleet['sent'] == []

    def test_missing_arguments_are_refused(self, app, installed, fleet):
        with pytest.raises(AgentCommandError):
            installed.run('', 'gui:screenshot')
        with pytest.raises(AgentCommandError):
            installed.run(SERVER, '')


class TestFailures:
    def test_a_failed_command_raises_with_its_code(self, app, installed, fleet):
        fleet['reply'] = {'success': False, 'error': 'Command timeout',
                          'code': 'TIMEOUT'}
        with pytest.raises(AgentCommandError) as excinfo:
            installed.run(SERVER, 'gui:screenshot')
        assert excinfo.value.code == 'TIMEOUT'
        assert 'Command timeout' in str(excinfo.value)

    def test_a_handler_failure_inside_a_successful_reply_still_raises(
            self, app, installed, fleet):
        # The double envelope: transport succeeded, the handler on the far side
        # did not. Checking only the outer 'success' reads this as a win.
        fleet['reply'] = {'success': True,
                          'data': {'success': False, 'error': 'no display'}}
        with pytest.raises(AgentCommandError) as excinfo:
            installed.run(SERVER, 'gui:screenshot')
        assert 'no display' in str(excinfo.value)

    def test_permission_denied_from_the_server_acl_surfaces(self, app, installed, fleet):
        # The per-server ACL is a separate gate from the manifest permission,
        # and the plugin should be able to tell them apart by code.
        fleet['reply'] = {'success': False, 'error': 'Permission denied for action',
                          'code': 'PERMISSION_DENIED'}
        with pytest.raises(AgentCommandError) as excinfo:
            installed.run(SERVER, 'gui:screenshot')
        assert excinfo.value.code == 'PERMISSION_DENIED'

    def test_an_empty_reply_is_a_failure_not_a_success(self, app, installed, fleet):
        fleet['reply'] = None
        with pytest.raises(AgentCommandError):
            installed.run(SERVER, 'gui:screenshot')


class TestReads:
    def test_online_and_capabilities(self, app, installed, fleet):
        assert installed.online() == [SERVER]
        assert installed.is_online(SERVER) is True
        assert installed.capabilities(SERVER) == {'gui.screenshot': True}
        assert installed.has_capability(SERVER, 'gui.screenshot') is True

        fleet['connected'] = False
        assert installed.online() == []
        assert installed.is_online(SERVER) is False


def test_sdk_is_reachable_from_the_package(app):
    from app import plugins_sdk

    assert plugins_sdk.agents.CommandError is AgentCommandError
    with pytest.raises(ValueError):
        plugins_sdk.agents.for_plugin('')
