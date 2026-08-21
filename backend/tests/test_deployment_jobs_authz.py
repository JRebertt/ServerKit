"""GHSA-6w78-q5vm-rfmh — deployment-job console endpoints must enforce
app/requester-level authorization, not just authentication.

- GET  /api/v1/deployment-jobs?app_id=N     (any app's deploy history leaked)
- GET  /api/v1/deployment-jobs/<id>         (logs may contain build output)
- GET  /api/v1/deployment-jobs/<id>/logs    (textbook IDOR on the log stream)
- POST /api/v1/deployment-jobs/<id>/retry   (unauthorized deploy trigger)

App-linked jobs follow the app-grant seam (can_access_app for reads,
can_operate_app for retries); app-less jobs (template installs, simulated
deploys) are requester-or-admin only. The job list 403s for an app_id the
caller can't reach and is admin-only when no app_id is given (mirrors
deploy.py get_deployment_history).
"""
import pytest


@pytest.fixture
def job_rbac(app, scoping_rbac):
    """One app-linked failed job (+log) on scoping_rbac's app, plus two
    app-less jobs: one requested by the app owner, one by the foreign user."""
    from types import SimpleNamespace
    from app import db
    from app.models import User
    from app.models.deployment_job import DeploymentJob, DeploymentJobLog

    owner = User.query.filter_by(username='scope_owner').first()
    foreign = User.query.filter_by(username='scope_foreign').first()

    app_job = DeploymentJob(
        id='job-app-linked', kind='app_deploy', status='failed',
        app_id=scoping_rbac.app_id, requested_by=owner.id,
    )
    owner_job = DeploymentJob(
        id='job-owner-appless', kind='template_install', status='failed',
        app_id=None, requested_by=owner.id,
    )
    foreign_job = DeploymentJob(
        id='job-foreign-appless', kind='template_install', status='failed',
        app_id=None, requested_by=foreign.id,
    )
    db.session.add_all([app_job, owner_job, foreign_job])
    db.session.commit()
    db.session.add(DeploymentJobLog(
        job_id=app_job.id, level='info', message='DB_PASSWORD=hunter2'))
    db.session.commit()

    return SimpleNamespace(
        app_job_id=app_job.id, owner_job_id=owner_job.id,
        foreign_job_id=foreign_job.id, s=scoping_rbac,
    )


@pytest.fixture
def no_enqueue(monkeypatch):
    """Retry enqueues a real job run; stub both enqueue paths out."""
    from app.services.deployment_job_service import DeploymentJobService
    monkeypatch.setattr(DeploymentJobService, '_enqueue_app_deploy',
                        classmethod(lambda cls, job: None))
    monkeypatch.setattr(DeploymentJobService, '_enqueue_install',
                        classmethod(lambda cls, job: None))


# --------------------------------------------------------------------- list

def test_list_jobs_app_scoped_requires_access(client, job_rbac):
    """App-scoped listing folds every path to the app (app_access_tier), so
    workspace member/viewer read it too; a foreign caller is denied."""
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs?app_id={s.app_id}'
    for persona in ('owner', 'member', 'viewer', 'admin'):
        response = client.get(url, headers=getattr(s, persona))
        assert response.status_code == 200, persona
        job = response.get_json()['jobs'][0]
        assert job['can_cancel'] is False
        assert job['can_retry'] is (persona != 'viewer')
    assert client.get(url, headers=s.foreign).status_code == 403


def test_list_jobs_global_admin_only(client, job_rbac):
    s = job_rbac.s
    assert client.get('/api/v1/deployment-jobs', headers=s.admin).status_code == 200
    for persona in ('owner', 'member', 'viewer', 'foreign'):
        assert client.get('/api/v1/deployment-jobs',
                          headers=getattr(s, persona)).status_code == 403, persona


def test_list_jobs_unknown_app_404(client, job_rbac):
    assert client.get('/api/v1/deployment-jobs?app_id=999999',
                      headers=job_rbac.s.admin).status_code == 404


# ------------------------------------------------------------------- detail

def test_job_detail_requires_app_access(client, job_rbac):
    """Reads gate on can_access_app (owner/admin/any grant — workspace
    membership alone does NOT confer it), so only owner and admin pass."""
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.app_job_id}?logs=true'
    for persona in ('owner', 'admin'):
        response = client.get(url, headers=getattr(s, persona))
        assert response.status_code == 200, persona
        job = response.get_json()['job']
        assert job['can_cancel'] is False
        assert job['can_retry'] is True
    for persona in ('member', 'viewer', 'foreign'):
        assert client.get(url, headers=getattr(s, persona)).status_code == 403, persona


def test_job_detail_missing_404(client, job_rbac):
    assert client.get('/api/v1/deployment-jobs/no-such-job',
                      headers=job_rbac.s.admin).status_code == 404


def test_appless_job_detail_requester_or_admin(client, job_rbac):
    """An app-less job belongs to its requester (or a panel admin)."""
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.owner_job_id}'
    assert client.get(url, headers=s.owner).status_code == 200
    assert client.get(url, headers=s.admin).status_code == 200
    for persona in ('member', 'viewer', 'foreign'):
        assert client.get(url, headers=getattr(s, persona)).status_code == 403, persona


def test_appless_job_detail_foreign_own_job(client, job_rbac):
    """The foreign user reads its OWN app-less job; the app owner cannot."""
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.foreign_job_id}'
    assert client.get(url, headers=s.foreign).status_code == 200
    assert client.get(url, headers=s.owner).status_code == 403


# --------------------------------------------------------------------- logs

def test_job_logs_require_app_access(client, job_rbac):
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.app_job_id}/logs'
    assert client.get(url, headers=s.owner).status_code == 200
    assert client.get(url, headers=s.admin).status_code == 200
    for persona in ('member', 'viewer', 'foreign'):
        assert client.get(url, headers=getattr(s, persona)).status_code == 403, persona


def test_job_logs_appless_requester_only(client, job_rbac):
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.owner_job_id}/logs'
    assert client.get(url, headers=s.owner).status_code == 200
    assert client.get(url, headers=s.foreign).status_code == 403


def test_job_logs_missing_404(client, job_rbac):
    assert client.get('/api/v1/deployment-jobs/no-such-job/logs',
                      headers=job_rbac.s.admin).status_code == 404


# -------------------------------------------------------------------- retry

def test_retry_app_linked_requires_operate_access(client, job_rbac, no_enqueue):
    """Retry is a mutation: can_operate_app (member+). Owner, workspace member
    and panel admin pass; viewer and foreign are denied before any clone."""
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.app_job_id}/retry'
    for persona in ('owner', 'member', 'admin'):
        assert client.post(url, headers=getattr(s, persona)).status_code == 202, persona
    for persona in ('viewer', 'foreign'):
        assert client.post(url, headers=getattr(s, persona)).status_code == 403, persona


def test_retry_appless_requester_or_admin(client, job_rbac, no_enqueue):
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.owner_job_id}/retry'
    assert client.post(url, headers=s.owner).status_code == 202
    assert client.post(url, headers=s.admin).status_code == 202
    for persona in ('member', 'viewer', 'foreign'):
        assert client.post(url, headers=getattr(s, persona)).status_code == 403, persona


def test_retry_appless_foreign_own_job(client, job_rbac, no_enqueue):
    s = job_rbac.s
    url = f'/api/v1/deployment-jobs/{job_rbac.foreign_job_id}/retry'
    assert client.post(url, headers=s.foreign).status_code == 202
    assert client.post(url, headers=s.owner).status_code == 403


def test_retry_missing_404(client, job_rbac, no_enqueue):
    assert client.post('/api/v1/deployment-jobs/no-such-job/retry',
                       headers=job_rbac.s.admin).status_code == 404
