"""Resource visibility shared by run sockets and their polling endpoint."""


def can_read_run(user, run_kind, run_id):
    if not user or not user.is_active:
        return False
    if not isinstance(run_id, (str, int)) or isinstance(run_id, bool):
        return False
    if run_kind == 'deploy':
        from app.models.deployment_job import DeploymentJob
        from app.models import Application
        from app.services.resource_grant_service import ResourceGrantService
        job = DeploymentJob.query.populate_existing().filter_by(id=str(run_id)).first()
        if job is None:
            return False
        if job.app_id:
            application = Application.query_active().populate_existing().filter_by(id=job.app_id).first()
            return bool(application and ResourceGrantService.can_access_app(user, application))
        return user.is_admin or job.requested_by == user.id
    if run_kind == 'job':
        # The unified jobs REST surface is admin-only, regardless of owner metadata.
        from app.jobs.models import Job
        return user.is_admin and Job.query.filter_by(id=str(run_id)).first() is not None
    # Adding a new producer requires an explicit visibility policy.
    return False
