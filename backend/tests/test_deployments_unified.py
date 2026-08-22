"""§3 unification — DeploymentJob links + the unified /api/v1/deployments surface.

DeploymentJob is the canonical execution record (now able to point at the
Deployment/GitDeployment release rows). The /api/v1/deployments namespace gives
one federated read over versioned build deploys and webhook git deploys, and
re-mounts the deployment-jobs surface under /deployments/jobs.
"""
import uuid

from app.models.deployment_job import DeploymentJob


def test_deployment_job_link_columns_round_trip(app):
    from app import db
    from app.models.deployment_job import DeploymentJob
    with app.app_context():
        job = DeploymentJob(
            id=str(uuid.uuid4()), kind='deploy.install', status='succeeded',
            deployment_id=None, commit_hash='abc123', image_tag='img:1', container_id='c1',
        )
        db.session.add(job)
        db.session.commit()
        d = DeploymentJob.query.get(job.id).to_dict()
        assert d['commit_hash'] == 'abc123'
        assert d['image_tag'] == 'img:1'
        assert d['container_id'] == 'c1'
        assert 'deployment_id' in d and 'git_deployment_id' in d and 'webhook_id' in d


def test_non_recipe_serialization_only_parses_an_explicitly_requested_plan(monkeypatch):
    job = DeploymentJob(
        id=str(uuid.uuid4()),
        kind='deploy.install',
        status='pending',
    )
    calls = []

    def get_plan():
        calls.append(True)
        return {'steps': []}

    monkeypatch.setattr(job, 'get_plan', get_plan)

    assert 'plan' not in job.to_dict()
    assert calls == []
    assert job.to_dict(include_plan=True)['plan'] == {'steps': []}
    assert calls == [True]


def _seed_app_with_deploys(app):
    from app import db
    from app.models import User
    from app.models.application import Application
    from app.models.deployment import Deployment
    from app.models.webhook import GitDeployment
    with app.app_context():
        admin = User.query.filter_by(username='testadmin').first()
        a = Application(name='dep-app', app_type='docker', status='running',
                        root_path='/srv/dep', user_id=admin.id if admin else 1)
        db.session.add(a)
        db.session.commit()
        db.session.add(Deployment(app_id=a.id, version=1, status='live'))
        db.session.add(GitDeployment(app_id=a.id, version=1, status='success', branch='main'))
        db.session.commit()
        return a.id


def test_unified_history_federates_sources(app, client, auth_headers):
    app_id = _seed_app_with_deploys(app)
    res = client.get(f'/api/v1/deployments/apps/{app_id}/history', headers=auth_headers)
    assert res.status_code == 200
    deployments = res.get_json()['deployments']
    sources = {d['source'] for d in deployments}
    assert sources == {'build', 'webhook'}


def test_unified_history_source_filter(app, client, auth_headers):
    app_id = _seed_app_with_deploys(app)
    res = client.get(f'/api/v1/deployments/apps/{app_id}/history?source=webhook', headers=auth_headers)
    assert res.status_code == 200
    deployments = res.get_json()['deployments']
    assert deployments and all(d['source'] == 'webhook' for d in deployments)


def test_deployment_detail(app, client, auth_headers):
    from app import db
    from app.models.deployment import Deployment
    app_id = _seed_app_with_deploys(app)
    with app.app_context():
        dep_id = Deployment.query.filter_by(app_id=app_id).first().id
    res = client.get(f'/api/v1/deployments/{dep_id}', headers=auth_headers)
    assert res.status_code == 200
    assert res.get_json()['deployment']['id'] == dep_id


def test_jobs_alias_mounted_under_deployments(app, client, auth_headers):
    canonical = client.get('/api/v1/deployment-jobs', headers=auth_headers)
    alias = client.get('/api/v1/deployments/jobs', headers=auth_headers)
    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert alias.get_json() == canonical.get_json()
