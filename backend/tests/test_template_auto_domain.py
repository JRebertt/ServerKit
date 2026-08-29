"""The deploy drawer's domain promise must be the install's contract.

The drawer shows the operator the exact ``<name>.<base>`` hostname before they
click Deploy ("Published automatically once the deploy finishes"). Publishing,
however, was gated on a per-template ``auto_domain: true`` flag the operator
cannot see — so for most of the catalog the install silently landed on
``host:port`` instead (which a default firewall doesn't even expose), and the
domain had to be redone by hand in the service's settings.

These tests pin the fix: the install request can opt in explicitly, the flag
rides the plan to the finalizer, and an absent flag still lets the template
YAML decide.
"""

import pytest

from app.services.template_service import TemplateService

# A real bundled catalog template that does NOT declare auto_domain — the
# common case the drawer was over-promising for.
TEMPLATE_ID = 'actualbudget'


@pytest.fixture
def plain_template(app):
    result = TemplateService.get_template(TEMPLATE_ID)
    assert result.get('success'), 'bundled template missing'
    assert not result['template'].get('auto_domain'), (
        'test premise broken: template now opts in by itself')
    return result['template']


class TestPlanFlag:
    def test_request_opt_in_reaches_the_plan(self, app, plain_template):
        result = TemplateService.build_install_plan(
            TEMPLATE_ID, 'promised-app', auto_domain=True)
        assert result['success'] is True
        assert result['plan']['auto_domain'] is True

    def test_without_a_request_flag_the_template_decides(self, app, plain_template):
        result = TemplateService.build_install_plan(
            TEMPLATE_ID, 'quiet-app')
        assert result['success'] is True
        assert result['plan']['auto_domain'] is False

    def test_the_cached_template_is_not_mutated(self, app, plain_template):
        TemplateService.build_install_plan(
            TEMPLATE_ID, 'copy-check-app', auto_domain=True)
        again = TemplateService.get_template(TEMPLATE_ID)['template']
        assert not again.get('auto_domain')


class TestApiPassThrough:
    def test_install_endpoint_forwards_the_flag(self, app, client, auth_headers,
                                                monkeypatch):
        from app.services.deployment_job_service import DeploymentJobService
        seen = {}

        def fake_install(**kwargs):
            seen.update(kwargs)
            return {'success': True, 'job_id': 'j1',
                    'job': {'id': 'j1', 'status': 'pending'}}

        monkeypatch.setattr(DeploymentJobService, 'install_template',
                            staticmethod(fake_install))
        res = client.post(f'/api/v1/templates/{TEMPLATE_ID}/install',
                          headers=auth_headers,
                          json={'app_name': 'promised-app',
                                'server_id': 'local', 'auto_domain': True})
        assert res.status_code in (201, 202), res.get_json()
        assert seen['auto_domain'] is True

    def test_absent_flag_stays_absent(self, app, client, auth_headers, monkeypatch):
        # None, not False: the service must be able to tell "the drawer said
        # nothing" apart from an explicit opt-out.
        from app.services.deployment_job_service import DeploymentJobService
        seen = {}

        def fake_install(**kwargs):
            seen.update(kwargs)
            return {'success': True, 'job_id': 'j2',
                    'job': {'id': 'j2', 'status': 'pending'}}

        monkeypatch.setattr(DeploymentJobService, 'install_template',
                            staticmethod(fake_install))
        res = client.post(f'/api/v1/templates/{TEMPLATE_ID}/install',
                          headers=auth_headers,
                          json={'app_name': 'quiet-app', 'server_id': 'local'})
        assert res.status_code in (201, 202), res.get_json()
        assert seen['auto_domain'] is None
