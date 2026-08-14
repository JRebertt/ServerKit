"""Plan 55 task 7 — declared-vs-observed extension permissions, honestly.

The manifest's ``permissions`` array was declaration-only: the install dialog
showed it, and nothing ever compared it against what the extension actually
did. These tests pin both halves of the answer — the usage the gate can see,
and the much larger set it cannot.

That second half is the point. The SDK exposes no shell, docker, filesystem or
network helper, and hands out ``db`` as raw SQLAlchemy, so those declarations
are consent signals rather than enforced boundaries. A UI that showed them as
"never used" would be inventing evidence, so the report marks them
``observable: false`` instead.
"""
import pytest

from app.plugins_sdk import permissions as perms


SLUG = 'demo-ext'
AGENT_PERM = 'agent.command:restart'


@pytest.fixture(autouse=True)
def _clean_observations():
    perms.reset_observations()
    yield
    perms.reset_observations()


@pytest.fixture
def installed(app):
    """An installed extension declaring one observable and one declaration-only
    permission."""
    from app import db
    from app.models.plugin import InstalledPlugin

    row = InstalledPlugin(
        slug=SLUG, name='Demo', display_name='Demo', version='1.0.0',
        status='active', manifest={'permissions': [AGENT_PERM, 'shell']},
    )
    db.session.add(row)
    db.session.commit()
    return row


# --------------------------------------------------------------------------- #
# What the gate can see
# --------------------------------------------------------------------------- #
class TestObservation:

    def test_a_declared_use_is_recorded(self, app, installed):
        perms.require(SLUG, AGENT_PERM)
        report = perms.usage_report(SLUG)

        row = next(r for r in report['permissions'] if r['permission'] == AGENT_PERM)
        assert row['declared'] is True
        assert row['observable'] is True
        assert row['used'] is True
        assert row['uses'] == 1
        assert row['first_used_at']

    def test_repeated_use_counts_but_keeps_the_first_timestamp(self, app, installed):
        perms.require(SLUG, AGENT_PERM)
        first = perms.usage_report(SLUG)['permissions'][0]['first_used_at']
        perms.require(SLUG, AGENT_PERM)
        row = next(r for r in perms.usage_report(SLUG)['permissions']
                   if r['permission'] == AGENT_PERM)

        assert row['uses'] == 2
        assert row['first_used_at'] == first

    def test_an_unused_observable_permission_is_reported_as_unused(self, app, installed):
        """Nothing was called — for an observable permission that absence IS
        evidence, and over-declaration is worth showing."""
        report = perms.usage_report(SLUG)

        assert report['unused_observable'] == [AGENT_PERM]

    def test_a_refusal_is_recorded_and_still_raises(self, app, installed):
        """The denial is the interesting one: something reached for a
        capability it never declared."""
        with pytest.raises(perms.PermissionDenied):
            perms.require(SLUG, 'agent.command:rm-rf')

        report = perms.usage_report(SLUG)
        assert report['undeclared_attempts'] == ['agent.command:rm-rf']
        row = next(r for r in report['permissions']
                   if r['permission'] == 'agent.command:rm-rf')
        assert row['declared'] is False
        # It was refused, so it did not happen — 'used' must not claim it did.
        assert row['used'] is False
        assert row['denied'] == 1

    def test_observations_are_per_extension(self, app, installed):
        perms.require(SLUG, AGENT_PERM)

        assert perms.observed_permissions('someone-else') == []

    def test_has_does_not_record(self, app, installed):
        """`has` is a question, not a use — recording it would fabricate
        activity for callers that only checked."""
        perms.has(SLUG, AGENT_PERM)

        assert perms.observed_permissions(SLUG) == []


# --------------------------------------------------------------------------- #
# What the gate CANNOT see — the honesty requirement
# --------------------------------------------------------------------------- #
class TestDeclarationOnlyCapabilities:

    @pytest.mark.parametrize('permission', sorted(perms.KNOWN_PERMISSIONS))
    def test_host_capabilities_are_not_observable(self, permission):
        """docker/shell/filesystem/network/db have no gated seam: the SDK
        exposes no helper for them, so a plugin reaches the host module
        directly and nothing in-process sees it."""
        assert perms.is_observable(permission) is False

    def test_agent_commands_are_observable(self):
        """The SDK is the only way to run a command on an agent, so every use
        must pass the gate."""
        assert perms.is_observable(AGENT_PERM) is True

    def test_an_unused_declaration_only_permission_is_never_called_unused(self, app, installed):
        """'shell' is declared and never seen — but absence of evidence is not
        evidence of absence here, and reporting it as unused would be a claim
        the panel cannot support."""
        report = perms.usage_report(SLUG)

        row = next(r for r in report['permissions'] if r['permission'] == 'shell')
        assert row['declared'] is True
        assert row['observable'] is False
        assert 'shell' not in report['unused_observable']

    def test_the_report_counts_both_kinds(self, app, installed):
        report = perms.usage_report(SLUG)

        assert report['observable_count'] == 1        # agent.command:restart
        assert report['declaration_only_count'] == 1  # shell


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #
@pytest.fixture
def admin_headers(app):
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash
    from app import db
    from app.models import User

    user = User(email='perm@test.local', username='permadmin',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


@pytest.fixture
def viewer_headers(app):
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash
    from app import db
    from app.models import User

    user = User(email='permv@test.local', username='permviewer',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_VIEWER, is_active=True)
    db.session.add(user)
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


class TestPermissionsEndpoint:

    def test_admin_gets_the_report(self, client, app, installed, admin_headers):
        perms.require(SLUG, AGENT_PERM)
        resp = client.get(f'/api/v1/plugins/{installed.id}/permissions',
                          headers=admin_headers)
        body = resp.get_json()

        assert resp.status_code == 200
        assert body['slug'] == SLUG
        assert {r['permission'] for r in body['permissions']} == {AGENT_PERM, 'shell'}

    def test_non_admin_is_refused(self, client, installed, viewer_headers):
        """It describes what third-party code has been doing — operator info."""
        resp = client.get(f'/api/v1/plugins/{installed.id}/permissions',
                          headers=viewer_headers)

        assert resp.status_code == 403

    def test_anonymous_is_refused(self, client, installed):
        assert client.get(
            f'/api/v1/plugins/{installed.id}/permissions').status_code == 401

    def test_unknown_plugin_is_404(self, client, admin_headers):
        assert client.get('/api/v1/plugins/999999/permissions',
                          headers=admin_headers).status_code == 404
