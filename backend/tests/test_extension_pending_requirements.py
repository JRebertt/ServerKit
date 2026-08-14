"""Plan 55 task 6 — the Python dependencies an install quietly skipped.

Installing a plugin's requirements runs pip with the backend's privileges, and
a setup.py hook is arbitrary code, so it is opt-in and off by default. The skip
was a `logger.warning` nobody reads: the file was written next to the extension
and nothing in the panel ever said so, leaving an extension running with
imports it may not have.

These pin the read-only surface that answers it — and that it stays read-only.
"""
import os

import pytest

from app.services import plugin_service


SLUG = 'needs-deps'
REQS = '# comment\nrequests>=2\n\npyyaml==6.0\n'


@pytest.fixture
def plugin_with_backend(app, tmp_path):
    """An installed plugin whose backend dir is a real directory on disk."""
    from app import db
    from app.models.plugin import InstalledPlugin

    backend_dir = tmp_path / 'plugins' / SLUG
    backend_dir.mkdir(parents=True)
    row = InstalledPlugin(slug=SLUG, name='Needs Deps', display_name='Needs Deps',
                          version='1.0.0', status='active',
                          backend_path=str(backend_dir), manifest={})
    db.session.add(row)
    db.session.commit()
    return row, backend_dir


@pytest.fixture
def pip_off(monkeypatch):
    monkeypatch.delenv(plugin_service.PLUGIN_PIP_ENV, raising=False)


# --------------------------------------------------------------------------- #
# The predicate the installer and the surface share
# --------------------------------------------------------------------------- #
class TestPipOptIn:

    @pytest.mark.parametrize('value', ['1', 'true', 'TRUE', 'yes', 'Yes'])
    def test_recognised_opt_in_values(self, monkeypatch, value):
        monkeypatch.setenv(plugin_service.PLUGIN_PIP_ENV, value)
        assert plugin_service.plugin_pip_enabled() is True

    @pytest.mark.parametrize('value', ['', '0', 'false', 'no', 'maybe'])
    def test_everything_else_is_off(self, monkeypatch, value):
        monkeypatch.setenv(plugin_service.PLUGIN_PIP_ENV, value)
        assert plugin_service.plugin_pip_enabled() is False

    def test_unset_is_off(self, pip_off):
        """Default-off is the security property; an unset var must never read
        as opt-in."""
        assert plugin_service.plugin_pip_enabled() is False


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
class TestPendingRequirements:

    def test_nothing_pending_when_no_file(self, app, plugin_with_backend, pip_off):
        plugin, _ = plugin_with_backend
        info = plugin_service.pending_requirements(plugin)

        assert info['pending'] is False
        assert info['content'] == ''
        assert info['packages'] == []

    def test_a_skipped_file_is_reported_with_its_contents(self, app, plugin_with_backend, pip_off):
        plugin, backend_dir = plugin_with_backend
        (backend_dir / 'requirements.txt').write_text(REQS, encoding='utf-8')

        info = plugin_service.pending_requirements(plugin)

        assert info['pending'] is True
        assert info['content'] == REQS
        # Comments and blank lines are not dependencies.
        assert info['packages'] == ['requests>=2', 'pyyaml==6.0']
        assert info['path'].endswith('requirements.txt')

    def test_the_report_names_the_exact_opt_in_var(self, app, plugin_with_backend, pip_off):
        """The whole point is telling the operator what to do about it."""
        plugin, backend_dir = plugin_with_backend
        (backend_dir / 'requirements.txt').write_text(REQS, encoding='utf-8')

        info = plugin_service.pending_requirements(plugin)

        assert info['env_var'] == 'SERVERKIT_ALLOW_PLUGIN_PIP'
        assert info['pip_enabled'] is False

    def test_pip_enabled_is_reported_so_the_ui_can_explain_a_stale_file(
            self, app, plugin_with_backend, monkeypatch):
        """A file written while the opt-in was off survives turning it on —
        the surface reports both facts rather than guessing which applies."""
        plugin, backend_dir = plugin_with_backend
        (backend_dir / 'requirements.txt').write_text(REQS, encoding='utf-8')
        monkeypatch.setenv(plugin_service.PLUGIN_PIP_ENV, '1')

        info = plugin_service.pending_requirements(plugin)

        assert info['pending'] is True
        assert info['pip_enabled'] is True

    def test_a_plugin_without_a_backend_path_is_not_pending(self, app, pip_off):
        from app import db
        from app.models.plugin import InstalledPlugin

        row = InstalledPlugin(slug='fe-only', name='FE', display_name='FE',
                              version='1.0.0', status='active', manifest={})
        db.session.add(row)
        db.session.commit()

        assert plugin_service.pending_requirements(row)['pending'] is False

    def test_an_unreadable_file_does_not_raise(self, app, plugin_with_backend, pip_off, monkeypatch):
        plugin, backend_dir = plugin_with_backend
        (backend_dir / 'requirements.txt').write_text(REQS, encoding='utf-8')
        monkeypatch.setattr(plugin_service.os.path, 'getsize',
                            lambda p: (_ for _ in ()).throw(OSError('boom')))

        assert plugin_service.pending_requirements(plugin)['pending'] is False

    def test_an_oversized_file_is_truncated_not_streamed(self, app, plugin_with_backend, pip_off):
        """This is echoed into a browser; a pathological file must not be."""
        plugin, backend_dir = plugin_with_backend
        (backend_dir / 'requirements.txt').write_text(
            'x' * (plugin_service._MAX_REQUIREMENTS_BYTES + 500), encoding='utf-8')

        info = plugin_service.pending_requirements(plugin)

        assert info['truncated'] is True
        assert len(info['content']) == plugin_service._MAX_REQUIREMENTS_BYTES

    def test_reporting_never_installs_anything(self, app, plugin_with_backend, pip_off, monkeypatch):
        """Read-only by design — the plan is explicit that this surface
        introduces no auto-install behaviour change."""
        plugin, backend_dir = plugin_with_backend
        (backend_dir / 'requirements.txt').write_text(REQS, encoding='utf-8')
        monkeypatch.setattr(plugin_service, '_install_requirements',
                            lambda *a, **k: pytest.fail('must not install'))

        assert plugin_service.pending_requirements(plugin)['pending'] is True
        # and the file is left exactly where it was
        assert (backend_dir / 'requirements.txt').read_text(encoding='utf-8') == REQS


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #
@pytest.fixture
def headers(app):
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash
    from app import db
    from app.models import User

    out = {}
    for name, role in (('reqadmin', User.ROLE_ADMIN), ('reqviewer', User.ROLE_VIEWER)):
        u = User(email=f'{name}@t.local', username=name,
                 password_hash=generate_password_hash('x'), role=role, is_active=True)
        db.session.add(u)
        db.session.commit()
        out[role] = {'Authorization': f'Bearer {create_access_token(identity=u.id)}'}
    return out


class TestRequirementsEndpoint:

    def test_admin_sees_the_pending_file(self, client, app, plugin_with_backend, headers, pip_off):
        from app.models import User
        plugin, backend_dir = plugin_with_backend
        (backend_dir / 'requirements.txt').write_text(REQS, encoding='utf-8')

        resp = client.get(f'/api/v1/plugins/{plugin.id}/requirements',
                          headers=headers[User.ROLE_ADMIN])
        body = resp.get_json()

        assert resp.status_code == 200
        assert body['pending'] is True
        assert body['packages'] == ['requests>=2', 'pyyaml==6.0']

    def test_non_admin_is_refused(self, client, plugin_with_backend, headers):
        from app.models import User
        plugin, _ = plugin_with_backend
        resp = client.get(f'/api/v1/plugins/{plugin.id}/requirements',
                          headers=headers[User.ROLE_VIEWER])

        assert resp.status_code == 403

    def test_anonymous_is_refused(self, client, plugin_with_backend):
        plugin, _ = plugin_with_backend
        assert client.get(
            f'/api/v1/plugins/{plugin.id}/requirements').status_code == 401

    def test_unknown_plugin_is_404(self, client, headers):
        from app.models import User
        assert client.get('/api/v1/plugins/999999/requirements',
                          headers=headers[User.ROLE_ADMIN]).status_code == 404
