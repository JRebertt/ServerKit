"""Proving tests for plan 51.5 — simulated (demo) deployments.

Demo jobs must flow through the REAL DeploymentJob + RunLogStream pipeline so
the Deploy Console can be exercised locally: these tests prove each scenario
reaches its terminal state with truthful logs, and that the surface is gated
off outside development.
"""

import os

from app import db
from app.models.deployment_job import DeploymentJob, DeploymentJobLog


def _simulate(client, auth_headers, scenario, speed='instant', wait=True):
    qs = '?wait=true' if wait else ''
    return client.post(
        f'/api/v1/deployment-jobs/simulate{qs}',
        json={'scenario': scenario, 'speed': speed},
        headers=auth_headers,
    )


def _job(job_id):
    return DeploymentJob.query.get(job_id)


class TestSimulateInfo:
    def test_lists_scenarios_when_enabled(self, client, auth_headers):
        res = client.get('/api/v1/deployment-jobs/simulate', headers=auth_headers)
        assert res.status_code == 200
        body = res.get_json()
        assert body['enabled'] is True
        ids = [s['id'] for s in body['scenarios']]
        assert ids == ['success', 'repo', 'fail-build', 'long', 'ansi', 'slow']
        assert all(s['name'] and s['description'] for s in body['scenarios'])

    def test_gate_off_returns_404_both_verbs(self, app, client, auth_headers):
        app.config['DEMO_DEPLOYS_ENABLED'] = False
        assert client.get('/api/v1/deployment-jobs/simulate',
                          headers=auth_headers).status_code == 404
        assert _simulate(client, auth_headers, 'success').status_code == 404

    def test_config_defaults(self):
        from config import DevelopmentConfig, ProductionConfig, TestingConfig
        assert TestingConfig.DEMO_DEPLOYS_ENABLED is True
        if os.environ.get('SERVERKIT_DEMO_DEPLOYS') is None:
            assert DevelopmentConfig.DEMO_DEPLOYS_ENABLED is True
            assert ProductionConfig.DEMO_DEPLOYS_ENABLED is False


class TestScenarios:
    def test_success_scenario_succeeds(self, client, auth_headers):
        res = _simulate(client, auth_headers, 'success')
        assert res.status_code == 202
        job = _job(res.get_json()['job_id'])
        assert job.kind == 'demo_deploy'
        assert job.trigger == 'demo'
        assert job.status == 'succeeded'
        assert job.target_server_id is None
        assert job.total_steps == 6
        result = job.get_result()
        assert result['demo'] is True
        assert result['scenario'] == 'success'
        assert len(result['step_timings']) == 6
        assert result['auto_domain']['url'].startswith('http://')
        assert job.logs.count() > 10

    def test_fail_build_has_tail_and_hint(self, client, auth_headers):
        res = _simulate(client, auth_headers, 'fail-build')
        assert res.status_code == 202
        job = _job(res.get_json()['job_id'])
        assert job.status == 'failed'
        assert 'npm run build' in job.error_message
        result = job.get_result()
        assert any('npm ERR!' in line for line in result['failure_tail'])
        # The npm ERR! tail must match the hint table's Node entry.
        assert 'Node build failed' in result['hint']

    def test_long_scenario_caps_persisted_rows(self, client, auth_headers):
        res = _simulate(client, auth_headers, 'long')
        assert res.status_code == 202
        job_id = res.get_json()['job_id']
        assert _job(job_id).status == 'succeeded'
        rows = DeploymentJobLog.query.filter_by(job_id=job_id).count()
        assert rows <= 5001  # cap + one marker row
        marker = DeploymentJobLog.query.filter_by(job_id=job_id).filter(
            DeploymentJobLog.message.contains('Log truncated at 5000 lines')
        ).count()
        assert marker == 1

    def test_ansi_scenario_is_sanitized(self, client, auth_headers):
        res = _simulate(client, auth_headers, 'ansi')
        assert res.status_code == 202
        job_id = res.get_json()['job_id']
        assert _job(job_id).status == 'succeeded'
        messages = [log.message for log in
                    DeploymentJobLog.query.filter_by(job_id=job_id).all()]
        assert messages, 'expected persisted log rows'
        assert all('\x1b' not in m for m in messages)
        # \r overwrites collapse to the final segment.
        assert any(m == 'Progress: [==========] 100%' for m in messages)

    def test_unknown_scenario_400(self, client, auth_headers):
        res = _simulate(client, auth_headers, 'nope')
        assert res.status_code == 400
        assert 'Unknown scenario' in res.get_json()['error']

    def test_unknown_speed_400(self, client, auth_headers):
        res = client.post(
            '/api/v1/deployment-jobs/simulate?wait=true',
            json={'scenario': 'success', 'speed': 'ludicrous'},
            headers=auth_headers,
        )
        assert res.status_code == 400
        assert 'Unknown speed' in res.get_json()['error']


class TestLifecycle:
    def test_async_create_leaves_pending_job(self, client, auth_headers):
        res = _simulate(client, auth_headers, 'success', wait=False)
        assert res.status_code == 202
        job = _job(res.get_json()['job_id'])
        # No consumer runs in tests: the job sits queued, not failed.
        assert job.status == 'pending'
        assert job.get_plan()['scenario'] == 'success'

    def test_retry_failed_demo_job_clones_it(self, client, auth_headers):
        res = _simulate(client, auth_headers, 'fail-build')
        original_id = res.get_json()['job_id']
        assert _job(original_id).status == 'failed'

        retry = client.post(f'/api/v1/deployment-jobs/{original_id}/retry',
                            headers=auth_headers)
        assert retry.status_code == 202
        clone_id = retry.get_json()['job_id']
        assert clone_id != original_id
        clone = _job(clone_id)
        assert clone.kind == 'demo_deploy'
        assert clone.status == 'pending'
        assert clone.trigger == 'retry'
        assert clone.get_plan()['scenario'] == 'fail-build'

    def test_run_job_dispatches_demo_kind(self, app, auth_headers, client):
        from app.services.deployment_job_service import DeploymentJobService
        res = _simulate(client, auth_headers, 'success', wait=False)
        job_id = res.get_json()['job_id']
        result = DeploymentJobService.run_job(job_id)
        assert result['success'] is True
        assert _job(job_id).status == 'succeeded'


class TestRepoScenario:
    """The 'repo' scenario is parameterised so a demo reads like a real deploy."""

    def test_repo_scenario_uses_params_and_title(self, client, auth_headers):
        params = {'app_name': 'agentsite', 'repo_url': 'https://github.com/jhd3197/AgentSite.git',
                  'branch': 'main', 'port': 6391, 'health_path': '/api/health',
                  'url': 'https://agentsite.example.com'}
        r = client.post('/api/v1/deployment-jobs/simulate?wait=true',
                        json={'scenario': 'repo', 'speed': 'instant', 'params': params,
                              'title': 'Deploying agentsite'},
                        headers=auth_headers)
        assert r.status_code == 202, r.get_json()
        job = r.get_json()['job']
        assert job['status'] == 'succeeded'
        assert job['result']['auto_domain']['url'] == 'https://agentsite.example.com'
        messages = [l['message'] for l in job['logs']]
        assert any('AgentSite.git' in m for m in messages)
        assert any('6391' in m and '/api/health' in m for m in messages)
        detail = client.get(f"/api/v1/deployment-jobs/{job['id']}?plan=true", headers=auth_headers).get_json()['job']
        assert detail['plan']['title'] == 'Deploying agentsite'
        assert detail['plan']['params']['app_name'] == 'agentsite'

    def test_repo_scenario_without_params_still_runs(self, client, auth_headers):
        r = client.post('/api/v1/deployment-jobs/simulate?wait=true',
                        json={'scenario': 'repo', 'speed': 'instant'}, headers=auth_headers)
        assert r.status_code == 202
        assert r.get_json()['job']['status'] == 'succeeded'
