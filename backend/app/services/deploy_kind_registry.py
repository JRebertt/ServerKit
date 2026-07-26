"""Registry of deployment-job kinds contributed outside the core.

``DeploymentJobService.run_job`` dispatches on ``job.kind`` through a hardcoded
switch — fine while every kind lived in core (app_deploy, template_install,
demo_deploy), but it meant a plugin could not own long-running work that
*behaves* like a deployment. Plugin work had to go to the generic job system
instead, which gives no step plan, no streaming console, and no place in Deploy
Activity. WordPress is the case in point: promoting an environment is
deploy-shaped in every respect, yet it was invisible in the one page users open
to see what ran.

A registered kind gets all of that for free: a DeploymentJob row, the Deploy
Console with live logs, retry, and a row in the activity feed — with no
frontend work, because the feed already renders unknown kinds by their id.

Handlers receive the ``DeploymentJob`` and return the same
``{'success': bool, ...}`` shape core handlers use.
"""

import logging

logger = logging.getLogger(__name__)

# kind -> handler(job) -> dict
_HANDLERS = {}

# Kinds contributed here are namespaced by convention (``wordpress.promote``)
# so they cannot collide with the core kinds, which are bare words.
CORE_KINDS = ('app_deploy', 'template_install', 'demo_deploy')


def register(kind: str, handler, replace: bool = False):
    """Register *handler* for deployment-job *kind*."""
    if not kind or not callable(handler):
        raise ValueError('deploy kind requires a name and a callable handler')
    if kind in CORE_KINDS:
        raise ValueError(f'"{kind}" is a core deployment kind and cannot be overridden')
    if kind in _HANDLERS and not replace:
        raise ValueError(f'deploy kind "{kind}" is already registered')
    _HANDLERS[kind] = handler
    logger.info('Registered deployment kind: %s', kind)
    return handler


def get(kind: str):
    """Return the handler for *kind*, or None."""
    return _HANDLERS.get(kind)


def kinds():
    """All registered non-core kinds."""
    return sorted(_HANDLERS)


def clear():
    """Drop every registration. Tests only."""
    _HANDLERS.clear()
