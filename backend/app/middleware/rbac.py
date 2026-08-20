"""Role-Based Access Control middleware and decorators."""
from functools import wraps
from flask import g, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from app.models import User

# App capability tiers, ranked low->high. The single ordering behind
# app_access_tier / require_app_member and the membership visibility model.
_APP_ROLE_RANK = {'viewer': 1, 'member': 2, 'admin': 3, 'owner': 4}


def get_current_user():
    """Get the current authenticated user (via API key or JWT)."""
    # Check API key auth first
    api_key_user = getattr(g, 'api_key_user', None)
    if api_key_user:
        return api_key_user

    # Fall back to JWT
    user_id = get_jwt_identity()
    if user_id:
        return User.query.get(user_id)
    return None


def auth_required():
    """
    Decorator that accepts either API key or JWT authentication.
    Use this instead of @jwt_required() to support both auth methods.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # If API key already authenticated via middleware, proceed
            if getattr(g, 'api_key_user', None):
                return fn(*args, **kwargs)
            # Otherwise require JWT
            verify_jwt_in_request()
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_role(*allowed_roles):
    """
    Decorator that requires the user to have one of the specified roles.

    Usage:
        @require_role('admin', 'developer')
        def my_endpoint():
            ...
    """
    def decorator(fn):
        @wraps(fn)
        @auth_required()
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if not user.is_active:
                return jsonify({'error': 'Account is deactivated'}), 403
            if user.role not in allowed_roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            return fn(*args, **kwargs)
        # Marks this view as carrying an explicit authorization decision, so the
        # default-deny sweep test (tests/test_route_authz_sweep.py) recognizes it
        # as gated rather than flagging it as an unguarded mutating route.
        wrapper._sk_authz = ('require_role', allowed_roles)
        return wrapper
    return decorator


def admin_required(fn):
    """
    Decorator that requires admin role.

    Usage:
        @admin_required
        def admin_only_endpoint():
            ...
    """
    @wraps(fn)
    @auth_required()
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 403
        if not user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    wrapper._sk_authz = ('admin_required',)
    return wrapper


def require_admin_user():
    """Return the calling admin user, or raise a typed error.

    The mid-route counterpart to ``@admin_required``, for handlers that need
    the user object or that gate only part of their work. It raises instead of
    returning a sentinel because the five private ``_require_admin()`` helpers
    this replaces had grown *three mutually incompatible* return contracts —
    ``None``-means-ok, ``None``-means-denied, and ``(user, err)`` — so reading
    a call site told you nothing about which one you were looking at, and
    copying a guard between files inverted it silently.

    Both the unknown-user and the not-an-admin case raise 403 'Admin access
    required': a caller who is not an admin should not learn from the status
    code whether the account behind the token still exists.
    """
    from app.exceptions import PermissionDeniedError

    user = get_current_user()
    if not user:
        raise PermissionDeniedError('Admin access required')
    if not user.is_active:
        raise PermissionDeniedError('Account is deactivated')
    if not user.is_admin:
        raise PermissionDeniedError('Admin access required')
    return user


def developer_required(fn):
    """
    Decorator that requires developer role or higher (admin or developer).

    Usage:
        @developer_required
        def developer_endpoint():
            ...
    """
    @wraps(fn)
    @auth_required()
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 403
        if not user.is_developer:
            return jsonify({'error': 'Developer access required'}), 403
        return fn(*args, **kwargs)
    wrapper._sk_authz = ('developer_required',)
    return wrapper


def permission_required(feature, level='read'):
    """
    Decorator that checks per-feature permissions.

    Usage:
        @permission_required('applications', 'write')
        def create_app():
            ...
    """
    def decorator(fn):
        @wraps(fn)
        @auth_required()
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if not user.is_active:
                return jsonify({'error': 'Account is deactivated'}), 403
            if not user.has_permission(feature, level):
                return jsonify({
                    'error': f'Permission denied: {level} access to {feature} required'
                }), 403
            return fn(*args, **kwargs)
        wrapper._sk_authz = ('permission_required', feature, level)
        return wrapper
    return decorator


def viewer_required(fn):
    """
    Decorator that requires viewer role or higher (any valid role).
    Essentially just requires authentication and active account.

    Usage:
        @viewer_required
        def viewer_endpoint():
            ...
    """
    @wraps(fn)
    @auth_required()
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 403
        if not user.is_viewer:
            return jsonify({'error': 'Access denied'}), 403
        return fn(*args, **kwargs)
    return wrapper


def require_workspace_access(workspace_id, user):
    """Return a 403 response tuple if `user` is neither a panel admin nor a member
    of the workspace, else None. Plain guard (not a decorator) so callers that
    already resolved the workspace id can drop it inline."""
    from app.services.workspace_service import WorkspaceService
    if user.is_admin:
        return None
    if WorkspaceService.get_user_role(workspace_id, user.id) is None:
        return jsonify({'error': 'Workspace access denied'}), 403
    return None


def require_workspace_role(workspace_id, user, roles):
    """Return a 403 response tuple unless `user` is a panel admin or their
    workspace membership role is one of `roles`, else None."""
    from app.services.workspace_service import WorkspaceService
    if user.is_admin:
        return None
    if WorkspaceService.get_user_role(workspace_id, user.id) not in roles:
        return jsonify({'error': 'Insufficient permissions'}), 403
    return None


def app_access_tier(user, application):
    """Fold every path to an application into ONE capability tier
    ('owner'|'admin'|'member'|'viewer') or None (no access):

    - panel admin or the app's owner  -> 'owner'
    - ResourceGrant 'editor'          -> 'member' (may operate, not administer)
    - ResourceGrant 'viewer'          -> 'viewer' (read-only)
    - member of the app's workspace   -> that workspace role
    - otherwise                       -> None

    The highest tier wins. This is the single seam behind require_app_member and
    the membership visibility model (plan 19 Decision 2).
    """
    if user.is_admin or application.user_id == user.id:
        return 'owner'

    from app.services.resource_grant_service import ResourceGrantService
    from app.services.workspace_service import WorkspaceService

    best = None
    grant_role = ResourceGrantService.grant_role(user.id, 'application', application.id)
    if grant_role == 'editor':
        best = 'member'
    elif grant_role == 'viewer':
        best = 'viewer'

    ws_id = getattr(application, 'workspace_id', None)
    if ws_id is not None:
        ws_role = WorkspaceService.get_user_role(ws_id, user.id)
        if ws_role:
            if best is None or _APP_ROLE_RANK[ws_role] > _APP_ROLE_RANK[best]:
                best = ws_role
    return best


def require_app_member(min_role='viewer', arg='app_id'):
    """Decorator: the caller must reach the application named by view kwarg `arg`
    with an effective tier >= `min_role` (see app_access_tier). Resolves the app,
    404s when it is missing (no info leak), 403s on insufficient access, and
    stashes the resolved Application on `g.current_application` for the view.

    Tiers: read surfaces use min_role='viewer'; member-write surfaces 'member';
    app-scoped destructive surfaces 'admin' (workspace admin/owner or panel admin).
    """
    def decorator(fn):
        @wraps(fn)
        @auth_required()
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if not user.is_active:
                return jsonify({'error': 'Account is deactivated'}), 403
            from app.models.application import Application
            # query_active: this decorator is a route guard, and every route
            # behind it ACTS on the app. A tombstone must 404 here rather than
            # be handed to the view in g.current_application.
            application = Application.query_active().filter_by(id=kwargs.get(arg)).first()
            if application is None:
                return jsonify({'error': 'Not found'}), 404
            tier = app_access_tier(user, application)
            if tier is None or _APP_ROLE_RANK[tier] < _APP_ROLE_RANK[min_role]:
                return jsonify({'error': 'Access denied'}), 403
            g.current_application = application
            return fn(*args, **kwargs)
        wrapper._sk_authz = ('require_app_member', min_role)
        return wrapper
    return decorator
