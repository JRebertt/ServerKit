"""
ServerKit Backend Plugin SDK.

Plugins should depend on names re-exported here rather than reaching into
host internals directly. As long as this surface stays stable, host-side
refactors don't break installed plugins.

Typical plugin module:

    from flask import Blueprint, request, jsonify
    from app.plugins_sdk import (
        db, jwt_required, current_user, audit, logger,
    )

    my_bp = Blueprint('my_plugin', __name__)
    log = logger(__name__)

    @my_bp.route('/things', methods=['GET'])
    @jwt_required()
    def list_things():
        user = current_user()
        # ... do work, use db.session, etc ...
        return jsonify({'ok': True})

Beyond the plumbing re-exported here, the SDK has surfaces a plugin
*contributes to* — ``store`` (state without a migration), ``deploys``,
``backups``, ``doctor``, ``search`` and ``agents``. In each case the plugin
brings the behaviour and the panel brings the UI, the persistence and the error
handling; see each ``*_sdk.py`` module's docstring, and docs/EXTENSIONS.md.

The lifecycle hook contract (called by plugin_service when installing /
uninstalling): a single positional arg — the InstalledPlugin row.

    # In plugins/<slug>/lifecycle.py
    from app.plugins_sdk import db, logger
    log = logger(__name__)

    def on_install(plugin):
        log.info(f'Setting up {plugin.slug}')

    def on_uninstall(plugin):
        log.info(f'Tearing down {plugin.slug}')
"""
import logging

from app import db, jwt
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt


def current_user():
    """Return the current authenticated user, or None if no JWT context.

    Resolves the JWT identity (a stringified user id, per the host's
    @jwt.user_identity_loader) into a User row.
    """
    try:
        uid = get_jwt_identity()
    except Exception:
        return None
    if uid is None:
        return None
    from app.models.user import User
    try:
        return User.query.get(int(uid))
    except (TypeError, ValueError):
        return None


def logger(name):
    """Return a logger scoped to a plugin module name."""
    return logging.getLogger(name)


def audit(action, target_type, target_id=None, details=None, user_id=None):
    """Write an audit log entry from a plugin.

    Thin wrapper around AuditService so plugins don't have to know its
    import path. `user_id` defaults to the current authenticated user.
    """
    if user_id is None:
        u = current_user()
        user_id = u.id if u else None
    from app.services.audit_service import AuditService
    return AuditService.log(
        action=action,
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
    )


# AI extension SDK — plugins do `from app.plugins_sdk import ai` then register
# tools/context against the core assistant (see plugins_sdk/ai.py). Imported
# lazily-safe: ai.py only depends on the AI tool registry, not on a running app.
from app.plugins_sdk import ai
from app.plugins_sdk import permissions
from app.plugins_sdk import sockets
from app.queue_bus.sdk import QueueBusSdk
from app.notifications.sdk import NotifySdk
from app.jobs.sdk import JobsSdk

queue = QueueBusSdk()
notify = NotifySdk()
jobs = JobsSdk()

# Surfaces imported lazily inside __getattr__ — see its docstring. Each entry
# is name -> (module path, attribute).
_LAZY_SURFACES = {
    'deploys': ('app.plugins_sdk.deploys_sdk', 'deploys'),
    'search': ('app.plugins_sdk.search_sdk', 'search'),
    'store': ('app.plugins_sdk.store_sdk', 'store'),
    'doctor': ('app.plugins_sdk.doctor_sdk', 'doctor'),
    'backups': ('app.plugins_sdk.backups_sdk', 'backups'),
    'agents': ('app.plugins_sdk.agents_sdk', 'agents'),
}
_lazy_cache = {}


def panel_version():
    """The panel's version string (for compat checks inside a plugin)."""
    from app.utils.version import get_panel_version
    return get_panel_version()


def config(slug):
    """Saved config values for an installed plugin (empty dict if none).

    The manifest's ``config_schema`` documents the fields; admins edit the
    values from Marketplace → Installed → Configure. Read-only here — the
    panel owns writes (PUT /api/v1/plugins/<id>/config).
    """
    from app.models.plugin import InstalledPlugin
    p = InstalledPlugin.query.filter_by(slug=slug).first()
    return dict(p.config or {}) if p else {}


# Capability gate: `require(slug, 'docker')` raises unless the plugin declared
# that permission in its manifest. See app/plugins_sdk/permissions.py.
require_permission = permissions.require

__all__ = [
    'db',
    'jwt',
    'jwt_required',
    'get_jwt_identity',
    'get_jwt',
    'current_user',
    'logger',
    'audit',
    'ai',
    'queue',
    'notify',
    'jobs',
    'deploys',
    'search',
    'store',
    'doctor',
    'backups',
    'agents',
    'permissions',
    'require_permission',
    'panel_version',
    'config',
    'sockets',
]


def __getattr__(name):
    """Lazily expose the surfaces that reach into host services.

    These SDKs import services (and therefore models), while this module is
    imported early in app setup — binding them eagerly would make plugins_sdk
    import-order sensitive for everyone, including the plugins that never
    contribute to any of these surfaces.

    Each implementation lives in ``<name>_sdk.py``, not ``<name>.py``: a
    submodule of the bare name would be bound as a package attribute on import
    and shadow this accessor, handing callers the module instead of the SDK
    instance.
    """
    target = _LAZY_SURFACES.get(name)
    if target is None:
        raise AttributeError(name)
    if name not in _lazy_cache:
        import importlib
        module, attr = target
        _lazy_cache[name] = getattr(importlib.import_module(module), attr)
    return _lazy_cache[name]
