"""Structural and functional checks for route authentication boundaries.

RBAC policy decorators authenticate with either an API key or a JWT through
``auth_required``. Stacking Flask-JWT-Extended's ``jwt_required`` outside one
of those policies is therefore both redundant and harmful: it rejects API-key
callers before the policy has a chance to authorize them.
"""
import ast
from pathlib import Path

from werkzeug.security import generate_password_hash


REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / 'backend' / 'app' / 'api'
RBAC_FILE = REPO_ROOT / 'backend' / 'app' / 'middleware' / 'rbac.py'

# Every decorator in this set performs authentication itself. Keep the
# delegation test below in sync so adding a policy here cannot accidentally
# weaken a route.
AUTHENTICATING_POLICIES = {
    'auth_required',
    'require_role',
    'admin_required',
    'developer_required',
    'permission_required',
    'viewer_required',
    'require_app_member',
}
DELEGATING_POLICIES = AUTHENTICATING_POLICIES - {'auth_required'}


def _decorator_name(decorator):
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _is_route_handler(node):
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == 'route'
        for decorator in node.decorator_list
    )


def test_routes_do_not_stack_jwt_with_authenticating_policy():
    """A policy owns both authentication and authorization for its route."""
    violations = []
    for path in sorted(API_DIR.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _is_route_handler(node):
                continue
            decorators = {
                name for decorator in node.decorator_list
                if (name := _decorator_name(decorator))
            }
            policies = decorators & AUTHENTICATING_POLICIES
            if 'jwt_required' in decorators and policies:
                violations.append(
                    f'{path.name}:{node.lineno}:{node.name} '
                    f'(jwt_required + {", ".join(sorted(policies))})'
                )

    assert not violations, (
        'Routes must use one authentication boundary. Remove jwt_required '
        'when an API-key-compatible policy already authenticates:\n'
        + '\n'.join(violations)
    )


def test_policy_decorators_continue_to_delegate_to_auth_required():
    """Prove that policies classified as authenticating still own that job."""
    tree = ast.parse(RBAC_FILE.read_text(encoding='utf-8'), filename=str(RBAC_FILE))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = []
    for policy in sorted(DELEGATING_POLICIES):
        node = functions.get(policy)
        delegates = node is not None and any(
            isinstance(child, ast.Call)
            and _decorator_name(child) == 'auth_required'
            for child in ast.walk(node)
        )
        if not delegates:
            missing.append(policy)

    assert not missing, (
        'Policy decorators no longer delegating to auth_required; either '
        'restore API-key/JWT authentication or remove them from '
        f'AUTHENTICATING_POLICIES: {missing}'
    )


def _create_api_key(db, role, suffix):
    from app.models import User
    from app.services.api_key_service import ApiKeyService

    user = User(
        email=f'boundary-{suffix}@test.local',
        username=f'boundary_{suffix}',
        password_hash=generate_password_hash('testpass'),
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    _, raw_key = ApiKeyService.create_key(
        user.id,
        name=f'boundary-{suffix}',
        scopes=['*'],
    )
    return raw_key


def test_migrated_admin_route_accepts_admin_api_key(app, client, db_session):
    """Exercise a formerly jwt+admin-stacked route through real middleware."""
    from app.models import User

    raw_key = _create_api_key(db_session, User.ROLE_ADMIN, 'admin')
    response = client.get(
        '/api/v1/notifications/config',
        headers={'X-API-Key': raw_key},
    )

    assert response.status_code == 200


def test_migrated_admin_route_still_accepts_admin_jwt(client, auth_headers):
    """The single policy boundary preserves the existing JWT path."""
    response = client.get('/api/v1/notifications/config', headers=auth_headers)

    assert response.status_code == 200


def test_migrated_admin_route_keeps_role_check_for_api_key(app, client, db_session):
    """Removing the redundant JWT decorator must not weaken authorization."""
    from app.models import User

    raw_key = _create_api_key(db_session, User.ROLE_DEVELOPER, 'developer')
    response = client.get(
        '/api/v1/notifications/config',
        headers={'X-API-Key': raw_key},
    )

    assert response.status_code == 403
    assert response.get_json() == {'error': 'Admin access required'}
