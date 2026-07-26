"""Plugin-facing SDK for deployment-shaped work.

    from app.plugins_sdk import deploys

    def promote(job):
        with deploys.steps(job) as step:
            with step('Snapshot source'):
                ...
            with step('Sync files'):
                ...
        return {'success': True}

    deploys.register('wordpress.promote', promote)
    deploys.start('wordpress.promote', steps=['Snapshot source', 'Sync files'],
                  app_id=site.application_id)

Use this — rather than ``plugins_sdk.jobs`` — when the work is a *deployment*:
it takes minutes, changes what is running, can fail halfway, and someone will
want to watch it. Registering the kind gets the Deploy Console, live logs,
retry and a row in Deploy Activity with no frontend work at all, because those
surfaces key off the DeploymentJob rather than off any particular kind.

``plugins_sdk.jobs`` remains right for everything else: short, unattended,
retryable background work that nobody watches.
"""

from contextlib import contextmanager

from app.services import deploy_kind_registry
from app.services.deployment_job_service import DeploymentJobService
from app.services.run_log_service import stream_for


class DeploysSdk:
    """Stable deployment surface for plugins."""

    def register(self, kind, handler, replace=False):
        """Register ``handler(job) -> {'success': bool, ...}`` for *kind*.

        Namespace the kind after your plugin (``wordpress.promote``); bare
        names are reserved for core.
        """
        return deploy_kind_registry.register(kind, handler, replace=replace)

    def start(self, kind, *, steps=None, app_id=None, server_id=None,
              user_id=None, trigger='manual', plan=None, wait=False):
        """Queue a deployment of *kind* and return ``{'success', 'job_id'}``.

        ``steps`` are the names the console shows, in order; the returned
        ``job_id`` addresses ``/deployments/<id>`` immediately, so a caller can
        redirect there before the work begins. Everything else the handler will
        need goes in ``plan`` — including ``title``, which is what the console
        heads the run with instead of falling back to the bare kind.
        """
        return DeploymentJobService.start_registered(
            kind, steps=steps, app_id=app_id, server_id=server_id,
            user_id=user_id, trigger=trigger, plan=plan, wait=wait,
        )

    def kinds(self):
        """Deployment kinds registered by plugins."""
        return deploy_kind_registry.kinds()

    # ---------------------------------------------------------------- logging

    def log(self, job, message, level='info', step_index=None):
        """Append one line to a job's console."""
        stream = stream_for(job)
        stream.log(level, message, step_index=step_index)
        stream.flush()

    def progress(self, job, index, name=None):
        """Move *job* onto step *index*, logging *name* as the console line.

        For work whose progress arrives through a callback the handler doesn't
        control — an existing service that already reports ``(step, message)``.
        When the handler owns the sequence itself, ``steps()`` reads better and
        records the failing step for you.
        """
        stream = stream_for(job)
        stream.set_step(index, name)
        if name:
            stream.log('info', name, step_index=index)
            stream.flush()

    @contextmanager
    def steps(self, job):
        """Walk a job's steps, keeping progress and logs in step.

        Yields a ``step(name)`` context manager. Entering advances the job's
        current step (so the console's pipeline strip lights up and the
        activity feed's tick bar fills); leaving normally logs completion,
        while an exception records which step failed before propagating —
        without that, a failure shows only a stack trace and no indication of
        how far the deployment got.
        """
        stream = stream_for(job)
        state = {'index': 0}

        @contextmanager
        def step(name):
            state['index'] += 1
            index = state['index']
            # set_step (rather than a hand-rolled row update) is what records
            # the per-step seconds the console shows and pushes the live status.
            stream.set_step(index, name)
            stream.log('info', f'→ {name}', step_index=index)
            stream.flush()
            try:
                yield index
            except Exception as exc:
                stream.log('error', f'{name} failed: {exc}', step_index=index)
                stream.flush()
                raise
            stream.log('info', f'✓ {name}', step_index=index)
            stream.flush()

        try:
            yield step
        finally:
            stream.flush()


deploys = DeploysSdk()
