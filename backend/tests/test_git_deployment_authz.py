"""GHSA-6w78-q5vm-rfmh — git deployment read endpoints must enforce app-level
authorization, not just authentication.

- GET /api/v1/git/deployments/<id>          (deployment logs may contain secrets)
- GET /api/v1/git/deployments/webhook/<id>  (deployment metadata across tenants)
- GET /api/v1/deploy/history                (global leak when app_id omitted)
- GET /api/v1/deploy/webhook-logs           (global leak when app_id omitted)

A caller with no path to the linked application gets 403/404; app-scoped
queries stay open to anyone who can reach the app; global (no app_id) history
queries are restricted to panel admins.
"""
import pytest


@pytest.fixture
def deployment_rbac(app, scoping_rbac):
    """One app-linked webhook + one deployment on scoping_rbac's app, plus one
    unlinked webhook."""
    from types import SimpleNamespace
    from app import db
    from app.models import GitDeployment, GitWebhook

    linked = GitWebhook(
        name='dep-linked', source='github',
        source_repo_url='https://example.com/r.git',
        secret='s', webhook_token='tok-dep-linked',
        app_id=scoping_rbac.app_id,
    )
    unlinked = GitWebhook(
        name='dep-unlinked', source='github',
        source_repo_url='https://example.com/r2.git',
        secret='s', webhook_token='tok-dep-unlinked',
        app_id=None,
    )
    db.session.add_all([linked, unlinked])
    db.session.commit()

    deployment = GitDeployment(
        app_id=scoping_rbac.app_id, webhook_id=linked.id,
        version=1, commit_sha='abc123', status='success',
        deploy_output='DB_PASSWORD=hunter2',
    )
    db.session.add(deployment)
    db.session.commit()

    return SimpleNamespace(
        linked_id=linked.id, unlinked_id=unlinked.id,
        deployment_id=deployment.id, s=scoping_rbac,
    )


def test_deployment_detail_requires_app_access(client, deployment_rbac):
    """Anyone who can reach the app reads the deployment (incl. logs); a
    foreign caller is denied before any log bytes are returned."""
    s = deployment_rbac.s
    url = f'/api/v1/git/deployments/{deployment_rbac.deployment_id}?logs=true'
    for persona in ('owner', 'member', 'viewer', 'admin'):
        assert client.get(url, headers=getattr(s, persona)).status_code == 200, persona
    assert client.get(url, headers=s.foreign).status_code == 403


def test_deployment_detail_missing_404(client, deployment_rbac):
    assert client.get('/api/v1/git/deployments/999999',
                      headers=deployment_rbac.s.admin).status_code == 404


def test_webhook_deployments_scoped_to_app_visibility(client, deployment_rbac):
    s = deployment_rbac.s
    url = f'/api/v1/git/deployments/webhook/{deployment_rbac.linked_id}'
    assert client.get(url, headers=s.member).status_code == 200
    assert client.get(url, headers=s.foreign).status_code == 403


def test_webhook_deployments_unlinked_stays_visible(client, deployment_rbac):
    """Unlinked webhooks remain panel-wide viewer-visible (plan 29 #11)."""
    url = f'/api/v1/git/deployments/webhook/{deployment_rbac.unlinked_id}'
    assert client.get(url, headers=deployment_rbac.s.foreign).status_code == 200


def test_webhook_deployments_missing_404(client, deployment_rbac):
    assert client.get('/api/v1/git/deployments/webhook/999999',
                      headers=deployment_rbac.s.admin).status_code == 404


def test_deploy_history_app_scoped_requires_access(client, deployment_rbac):
    s = deployment_rbac.s
    url = f'/api/v1/deploy/history?app_id={s.app_id}'
    assert client.get(url, headers=s.member).status_code == 200
    assert client.get(url, headers=s.foreign).status_code == 403


def test_deploy_history_global_admin_only(client, deployment_rbac):
    s = deployment_rbac.s
    assert client.get('/api/v1/deploy/history', headers=s.admin).status_code == 200
    for persona in ('owner', 'member', 'viewer', 'foreign'):
        assert client.get('/api/v1/deploy/history',
                          headers=getattr(s, persona)).status_code == 403, persona


def test_webhook_logs_app_scoped_requires_access(client, deployment_rbac):
    s = deployment_rbac.s
    url = f'/api/v1/deploy/webhook-logs?app_id={s.app_id}'
    assert client.get(url, headers=s.member).status_code == 200
    assert client.get(url, headers=s.foreign).status_code == 403


def test_webhook_logs_global_admin_only(client, deployment_rbac):
    s = deployment_rbac.s
    assert client.get('/api/v1/deploy/webhook-logs', headers=s.admin).status_code == 200
    assert client.get('/api/v1/deploy/webhook-logs', headers=s.foreign).status_code == 403
