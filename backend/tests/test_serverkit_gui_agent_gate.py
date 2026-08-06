"""serverkit-gui goes through plugins_sdk.agents (retrofit).

The extension used to call the agent registry directly, so its manifest
permissions were decoration: the install dialog said "screenshot and
capabilities" while /synthetic quietly also asked for system:info and
system:processes. Routing through the SDK enforces the declaration, which
first required the manifest to tell the truth.

The case worth protecting is an install whose STORED manifest predates those
two actions — declared_permissions() reads the database row captured at install
time, not plugin.json on disk. /synthetic must degrade there, not 500.
"""

import importlib
import json
import pathlib

import pytest
from flask_jwt_extended import create_access_token

from app import db
from app.models.plugin import InstalledPlugin
from app.models.server import Server
from app.models.user import User
from app.services import agent_registry as agent_registry_module

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app

SLUG = 'serverkit-gui'
SERVER_ID = 'srv-gui-1'
PREFIX = '/api/v1/server-gui'

GUI_ONLY = ['agent.command:gui:screenshot', 'agent.command:gui:capabilities']
ALL_FOUR = GUI_ONLY + ['agent.command:system:info', 'agent.command:system:processes']

_PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1] / 'app' / 'plugins' / SLUG


@pytest.fixture
def gui_app(app):
    """The app fixture with the gui blueprint mounted."""
    module = importlib.import_module(f'app.plugins.{SLUG}.blueprint')
    if not any(bp.name == 'server_gui' for bp in app.blueprints.values()):
        app.register_blueprint(module.gui_bp, url_prefix=PREFIX)
    return app


@pytest.fixture
def headers(gui_app):
    user = User(email='gui@test.local', username='gui_admin',
                password_hash='x', role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.add(Server(id=SERVER_ID, name='box', status='online'))
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


def _install(permissions):
    """Install the plugin with a given stored manifest."""
    InstalledPlugin.query.filter_by(slug=SLUG).delete()
    plugin = InstalledPlugin(slug=SLUG, name=SLUG, display_name='GUI',
                             version='0.1.0',
                             status=InstalledPlugin.STATUS_ACTIVE)
    plugin.manifest = {'permissions': permissions}
    db.session.add(plugin)
    db.session.commit()
    return plugin


@pytest.fixture
def fleet(monkeypatch):
    registry = agent_registry_module.agent_registry
    replies = {
        'gui:capabilities': {'success': True, 'data': {'capability': 'x11'}},
        'gui:screenshot': {'success': True, 'data': {'image_base64': 'AAAA'}},
        'system:info': {'success': True, 'data': {'hostname': 'realhost'}},
        'system:processes': {'success': True,
                             'data': [{'pid': 1, 'name': 'sshd'}]},
    }
    state = {'replies': replies, 'asked': []}

    def _send(server_id, action, params=None, timeout=None, user_id=None):
        state['asked'].append(action)
        return state['replies'].get(action, {'success': False, 'error': 'unknown action',
                                             'code': 'UNKNOWN'})

    monkeypatch.setattr(registry, 'send_command', _send)
    monkeypatch.setattr(registry, 'is_agent_connected', lambda sid: True)
    monkeypatch.setattr(registry, 'has_capability', lambda sid, cap: True)
    monkeypatch.setattr(registry, 'get_capabilities', lambda sid: {})
    return state


class TestManifest:
    def _manifest(self, path):
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))

    def test_declares_every_action_it_calls(self):
        manifest = self._manifest(_PLUGIN_DIR / 'plugin.json')
        # The retrofit's precondition: the gate can only be honest if the
        # manifest lists what the code actually asks for.
        for action in ('gui:screenshot', 'gui:capabilities',
                       'system:info', 'system:processes'):
            assert f'agent.command:{action}' in manifest['permissions']

    def test_requires_agent_actions_agrees_with_permissions(self):
        manifest = self._manifest(_PLUGIN_DIR / 'plugin.json')
        declared = {p.split('agent.command:', 1)[1]
                    for p in manifest['permissions']
                    if p.startswith('agent.command:')}
        assert set(manifest['requires_agent_actions']) == declared


class TestCapabilities:
    def test_returns_the_agents_answer(self, gui_app, client, headers, fleet):
        _install(ALL_FOUR)
        res = client.get(f'{PREFIX}/{SERVER_ID}/capabilities', headers=headers)
        assert res.status_code == 200
        assert res.get_json()['capability'] == 'x11'

    def test_falls_back_when_the_agent_cannot(self, gui_app, client, headers, fleet):
        _install(ALL_FOUR)
        fleet['replies']['gui:capabilities'] = {'success': False,
                                                'error': 'unsupported'}
        res = client.get(f'{PREFIX}/{SERVER_ID}/capabilities', headers=headers)
        # Still a 200 with the synthetic fallback — unchanged behaviour.
        assert res.status_code == 200
        assert res.get_json()['synthetic_fallback'] is True

    def test_falls_back_when_the_permission_is_missing(self, gui_app, client,
                                                       headers, fleet):
        _install([])
        res = client.get(f'{PREFIX}/{SERVER_ID}/capabilities', headers=headers)
        assert res.status_code == 200
        assert res.get_json()['synthetic_fallback'] is True
        assert fleet['asked'] == []


class TestFrame:
    def test_returns_the_frame(self, gui_app, client, headers, fleet):
        _install(ALL_FOUR)
        res = client.get(f'{PREFIX}/{SERVER_ID}/frame', headers=headers)
        assert res.status_code == 200
        assert res.get_json()['image_base64'] == 'AAAA'

    def test_a_failed_capture_is_still_a_502(self, gui_app, client, headers, fleet):
        _install(ALL_FOUR)
        fleet['replies']['gui:screenshot'] = {'success': False, 'error': 'no display',
                                              'code': 'CAPTURE_FAILED'}
        res = client.get(f'{PREFIX}/{SERVER_ID}/frame', headers=headers)
        assert res.status_code == 502
        assert res.get_json()['code'] == 'CAPTURE_FAILED'

    def test_a_handler_failure_inside_a_successful_reply_is_reported(
            self, gui_app, client, headers, fleet):
        # Previously this surfaced as the vague "agent returned no frame";
        # the SDK unwraps it, so the real reason reaches the caller.
        fleet['replies']['gui:screenshot'] = {
            'success': True, 'data': {'success': False, 'error': 'no display'}}
        _install(ALL_FOUR)
        res = client.get(f'{PREFIX}/{SERVER_ID}/frame', headers=headers)
        assert res.status_code == 502
        assert 'no display' in res.get_json()['error']

    def test_a_missing_permission_is_refused_not_dispatched(self, gui_app, client,
                                                            headers, fleet):
        _install([])
        res = client.get(f'{PREFIX}/{SERVER_ID}/frame', headers=headers)
        assert res.status_code == 403
        assert res.get_json()['code'] == 'PERMISSION_DENIED'
        assert fleet['asked'] == []


class TestSynthetic:
    def test_uses_real_agent_data_when_permitted(self, gui_app, client, headers, fleet):
        _install(ALL_FOUR)
        res = client.get(f'{PREFIX}/{SERVER_ID}/synthetic', headers=headers)
        assert res.status_code == 200
        body = res.get_json()
        assert body['hostname'] == 'realhost'
        assert body['taskbar'] == [{'id': 1, 'name': 'sshd'}]

    def test_an_older_install_degrades_instead_of_failing(self, gui_app, client,
                                                          headers, fleet):
        # The regression this endpoint's fallback exists for: declared
        # permissions come from the DB row captured at install time, so an
        # install predating this change lists only the two gui actions.
        _install(GUI_ONLY)

        res = client.get(f'{PREFIX}/{SERVER_ID}/synthetic', headers=headers)

        assert res.status_code == 200
        body = res.get_json()
        assert body['taskbar'] == []
        assert body['offline'] is False
        assert body['hostname'] == 'box'   # falls back to the server's name
        assert fleet['asked'] == []

    def test_a_silent_agent_still_renders_a_desktop(self, gui_app, client,
                                                    headers, fleet):
        _install(ALL_FOUR)
        fleet['replies']['system:info'] = {'success': False, 'error': 'nope'}
        fleet['replies']['system:processes'] = {'success': False, 'error': 'nope'}

        res = client.get(f'{PREFIX}/{SERVER_ID}/synthetic', headers=headers)

        assert res.status_code == 200
        assert res.get_json()['windows'][0]['title'] == 'System — box'
