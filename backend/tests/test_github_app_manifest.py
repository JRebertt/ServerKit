"""Proving tests for the one-click GitHub App manifest setup flow.

Covers the pure/mockable half of the flow: building the manifest, converting the
returned code into stored credentials, routing the connect URL through the app's
install screen when an app slug exists, surfacing app info in the config, and
listing repositories via installations in app mode. The live github.com
round-trip (create app → install → authorize) is verified manually.
"""
import flask
import pytest

from app.services.settings_service import SettingsService
from app.services.source_connection_service import SourceConnectionService as SC


def test_build_manifest_shape_and_state(app):
    with app.test_request_context():
        manifest, state, post_url = SC.build_github_app_manifest(
            'https://panel.example/connections/github-app/callback',
            'https://panel.example',
        )
        assert post_url == SC.GITHUB_APP_NEW_URL
        assert manifest['name'].startswith('ServerKit')
        assert manifest['url'] == 'https://panel.example'
        assert manifest['redirect_url'].endswith('/connections/github-app/callback')
        assert manifest['hook_attributes'] == {
            'url': 'https://panel.example/api/v1/source-connections/github/webhook',
            'active': False,
        }
        assert manifest['callback_urls'] == ['https://panel.example/connections/callback/github']
        assert manifest['default_permissions']['contents'] == 'read'
        assert manifest['request_oauth_on_install'] is True
        assert manifest['public'] is False
        # State is remembered for the conversion step.
        assert flask.session['source_github_app_state'] == state


def test_build_manifest_requires_urls(app):
    with app.test_request_context():
        with pytest.raises(ValueError):
            SC.build_github_app_manifest('', 'https://panel.example')


def test_manifest_webhook_url_has_no_double_slash(app):
    with app.test_request_context():
        manifest, _, _ = SC.build_github_app_manifest(
            'https://panel.example/connections/github-app/callback',
            'https://panel.example/',
        )

        assert manifest['hook_attributes']['url'] == (
            'https://panel.example/api/v1/source-connections/github/webhook'
        )


def _fake_conversion_response():
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                'id': 424242,
                'slug': 'serverkit-abc123',
                'name': 'ServerKit abc123',
                'client_id': 'Iv1.deadbeef',
                'client_secret': 'super-secret',
                'pem': '-----BEGIN RSA PRIVATE KEY-----\nkey\n-----END RSA PRIVATE KEY-----',
                'webhook_secret': 'wh-secret',
                'html_url': 'https://github.com/apps/serverkit-abc123',
            }
    return FakeResp()


def test_complete_manifest_stores_credentials(app, monkeypatch):
    from app.services import source_connection_service as mod
    monkeypatch.setattr(mod.requests, 'post', lambda *a, **k: _fake_conversion_response())

    with app.test_request_context():
        flask.session['source_github_app_state'] = 'state-xyz'
        result = SC.complete_github_app_manifest('code-123', 'state-xyz', user_id=None)

        assert result['slug'] == 'serverkit-abc123'
        assert result['install_url'] == 'https://github.com/apps/serverkit-abc123/installations/new'

        cfg = SC.get_github_config()
        assert cfg['configured'] is True
        assert cfg['provider_kind'] == 'app'
        assert cfg['app_slug'] == 'serverkit-abc123'
        assert cfg['install_url'].endswith('/installations/new')
        # The raw client id is stored; the PEM is stored encrypted (not plaintext).
        assert SettingsService.get('source_github_client_id') == 'Iv1.deadbeef'
        pem = SettingsService.get('source_github_app_pem') or ''
        assert pem and 'BEGIN RSA PRIVATE KEY' not in pem


def test_complete_manifest_rejects_bad_state(app):
    with app.test_request_context():
        flask.session['source_github_app_state'] = 'good'
        with pytest.raises(ValueError):
            SC.complete_github_app_manifest('code', 'bad', user_id=None)


def test_authorize_url_uses_install_when_app(app):
    with app.test_request_context():
        SettingsService.set('source_github_client_id', 'cid')
        SettingsService.set('source_github_client_secret', 'sec')
        SettingsService.set('source_github_app_slug', 'serverkit-abc123')
        url, state = SC.generate_github_authorize_url('https://panel.example/cb')
        assert 'apps/serverkit-abc123/installations/new' in url
        assert f'state={state}' in url


def test_authorize_url_classic_without_app(app):
    with app.test_request_context():
        SettingsService.set('source_github_client_id', 'cid')
        SettingsService.set('source_github_client_secret', 'sec')
        # No app slug -> classic OAuth authorize screen.
        url, _ = SC.generate_github_authorize_url('https://panel.example/cb')
        assert 'login/oauth/authorize' in url
        assert 'client_id=cid' in url


def test_list_repositories_app_mode_uses_installations(app, monkeypatch):
    monkeypatch.setattr(SC, '_get_github_token', classmethod(lambda cls, uid: 'tok'))

    def fake_get(cls, token, path):
        if path.startswith('/user/installations?'):
            return {'installations': [{'id': 1}, {'id': 2}]}
        if '/installations/1/repositories' in path:
            return {'repositories': [
                {'id': 10, 'name': 'alpha', 'full_name': 'me/alpha', 'updated_at': '2024-02-01'},
            ]}
        if '/installations/2/repositories' in path:
            return {'repositories': [
                {'id': 20, 'name': 'beta', 'full_name': 'me/beta', 'updated_at': '2024-03-01'},
            ]}
        return []

    monkeypatch.setattr(SC, '_github_get', classmethod(fake_get))

    with app.test_request_context():
        SettingsService.set('source_github_app_slug', 'serverkit-abc123')
        repos = SC.list_github_repositories(user_id=1)
        names = [r['full_name'] for r in repos]
        assert names == ['me/beta', 'me/alpha']  # sorted by updated_at desc
