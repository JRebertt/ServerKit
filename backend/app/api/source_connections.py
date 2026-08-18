"""Source provider connection API."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from requests import HTTPError

from app.middleware.rbac import admin_required, get_current_user
from app.services.source_connection_service import SourceConnectionService

source_connections_bp = Blueprint('source_connections', __name__)


@source_connections_bp.route('/github/status', methods=['GET'])
@jwt_required()
def github_status():
    user_id = int(get_jwt_identity())
    return jsonify(SourceConnectionService.get_status(user_id)), 200


@source_connections_bp.route('/github/authorize', methods=['GET'])
@jwt_required()
def github_authorize():
    redirect_uri = request.args.get('redirect_uri', '')
    if not redirect_uri:
        return jsonify({'error': 'redirect_uri is required'}), 400

    try:
        auth_url, state = SourceConnectionService.generate_github_authorize_url(redirect_uri)
        return jsonify({'auth_url': auth_url, 'state': state}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@source_connections_bp.route('/github/callback', methods=['POST'])
@jwt_required()
def github_callback():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    code = data.get('code', '')
    state = data.get('state', '')
    redirect_uri = data.get('redirect_uri', '')

    if not code or not state or not redirect_uri:
        return jsonify({'error': 'code, state, and redirect_uri are required'}), 400

    try:
        connection = SourceConnectionService.complete_github_callback(
            user_id=user_id,
            code=code,
            state=state,
            redirect_uri=redirect_uri,
        )
        return jsonify({'connection': connection.to_dict()}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _github_error(exc)}), 400


@source_connections_bp.route('/github/repos', methods=['GET'])
@jwt_required()
def github_repositories():
    user_id = int(get_jwt_identity())
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    try:
        repos = SourceConnectionService.list_github_repositories(user_id, search, page, per_page)
        return jsonify({'repos': repos}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _github_error(exc)}), 400


@source_connections_bp.route('/github/repos/<path:full_name>/branches', methods=['GET'])
@jwt_required()
def github_branches(full_name):
    user_id = int(get_jwt_identity())

    try:
        branches = SourceConnectionService.list_github_branches(user_id, full_name)
        return jsonify({'branches': branches}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _github_error(exc)}), 400


@source_connections_bp.route('/github/repos/<path:full_name>/manifest', methods=['GET'])
@jwt_required()
def github_repository_manifest(full_name):
    user_id = int(get_jwt_identity())
    ref = request.args.get('ref') or None

    try:
        manifest = SourceConnectionService.get_github_repository_manifest(user_id, full_name, ref)
        return jsonify({'manifest': manifest}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _github_error(exc)}), 400


@source_connections_bp.route('/github', methods=['DELETE'])
@jwt_required()
def disconnect_github():
    user_id = int(get_jwt_identity())
    try:
        SourceConnectionService.disconnect(user_id, 'github')
        return jsonify({'message': 'GitHub disconnected'}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404


@source_connections_bp.route('/admin/github', methods=['GET'])
@admin_required
def github_admin_config():
    return jsonify({'config': SourceConnectionService.get_github_config(redacted=True)}), 200


@source_connections_bp.route('/admin/github', methods=['PUT'])
@admin_required
def update_github_admin_config():
    user = get_current_user()
    result = SourceConnectionService.update_github_config(
        request.get_json() or {},
        user_id=user.id if user else None,
    )
    return jsonify(result), 200


@source_connections_bp.route('/admin/github/app-manifest', methods=['GET'])
@admin_required
def github_app_manifest():
    """Build the GitHub App manifest for the one-click setup flow."""
    redirect_uri = request.args.get('redirect_uri', '')
    base_url = request.args.get('base_url', '') or request.host_url
    try:
        manifest, state, post_url = SourceConnectionService.build_github_app_manifest(
            redirect_uri, base_url)
        return jsonify({'manifest': manifest, 'state': state, 'post_url': post_url}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@source_connections_bp.route('/admin/github/app-manifest/complete', methods=['POST'])
@admin_required
def complete_github_app_manifest():
    """Convert the manifest code GitHub returned into a stored GitHub App."""
    user = get_current_user()
    data = request.get_json() or {}
    try:
        result = SourceConnectionService.complete_github_app_manifest(
            code=data.get('code', ''),
            state=data.get('state', ''),
            user_id=user.id if user else None,
        )
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _github_error(exc)}), 400


def _github_error(exc):
    response = getattr(exc, 'response', None)
    if response is None:
        return str(exc)
    try:
        data = response.json()
        return data.get('message') or str(exc)
    except Exception:
        return response.text or str(exc)


@source_connections_bp.route('/gitlab/status', methods=['GET'])
@jwt_required()
def gitlab_status():
    user_id = int(get_jwt_identity())
    return jsonify(SourceConnectionService.get_gitlab_status(user_id)), 200


@source_connections_bp.route('/gitlab/authorize', methods=['GET'])
@jwt_required()
def gitlab_authorize():
    redirect_uri = request.args.get('redirect_uri', '')
    if not redirect_uri:
        return jsonify({'error': 'redirect_uri is required'}), 400

    try:
        auth_url, state = SourceConnectionService.generate_gitlab_authorize_url(redirect_uri)
        return jsonify({'auth_url': auth_url, 'state': state}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@source_connections_bp.route('/gitlab/callback', methods=['POST'])
@jwt_required()
def gitlab_callback():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    code = data.get('code', '')
    state = data.get('state', '')
    redirect_uri = data.get('redirect_uri', '')

    if not code or not state or not redirect_uri:
        return jsonify({'error': 'code, state, and redirect_uri are required'}), 400

    try:
        connection = SourceConnectionService.complete_gitlab_callback(
            user_id=user_id,
            code=code,
            state=state,
            redirect_uri=redirect_uri,
        )
        return jsonify({'connection': connection.to_dict()}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _gitlab_error(exc)}), 400


@source_connections_bp.route('/gitlab/repos', methods=['GET'])
@jwt_required()
def gitlab_repositories():
    user_id = int(get_jwt_identity())
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    try:
        repos = SourceConnectionService.list_gitlab_repositories(user_id, search, page, per_page)
        return jsonify({'repos': repos}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _gitlab_error(exc)}), 400


@source_connections_bp.route('/gitlab/repos/<path:full_name>/branches', methods=['GET'])
@jwt_required()
def gitlab_branches(full_name):
    user_id = int(get_jwt_identity())

    try:
        branches = SourceConnectionService.list_gitlab_branches(user_id, full_name)
        return jsonify({'branches': branches}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _gitlab_error(exc)}), 400


@source_connections_bp.route('/gitlab/repos/<path:full_name>/manifest', methods=['GET'])
@jwt_required()
def gitlab_repository_manifest(full_name):
    user_id = int(get_jwt_identity())
    ref = request.args.get('ref') or None

    try:
        manifest = SourceConnectionService.get_gitlab_repository_manifest(user_id, full_name, ref)
        return jsonify({'manifest': manifest}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _gitlab_error(exc)}), 400


@source_connections_bp.route('/gitlab', methods=['DELETE'])
@jwt_required()
def disconnect_gitlab():
    user_id = int(get_jwt_identity())
    try:
        SourceConnectionService.disconnect(user_id, 'gitlab')
        return jsonify({'message': 'GitLab disconnected'}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404


@source_connections_bp.route('/admin/gitlab', methods=['GET'])
@admin_required
def gitlab_admin_config():
    return jsonify({'config': SourceConnectionService.get_gitlab_config(redacted=True)}), 200


@source_connections_bp.route('/admin/gitlab', methods=['PUT'])
@admin_required
def update_gitlab_admin_config():
    user = get_current_user()
    result = SourceConnectionService.update_gitlab_config(
        request.get_json() or {},
        user_id=user.id if user else None,
    )
    return jsonify(result), 200


def _gitlab_error(exc):
    response = getattr(exc, 'response', None)
    if response is None:
        return str(exc)
    try:
        data = response.json()
        return data.get('message') or data.get('error_description') or data.get('error') or str(exc)
    except Exception:
        return response.text or str(exc)


@source_connections_bp.route('/bitbucket/status', methods=['GET'])
@jwt_required()
def bitbucket_status():
    user_id = int(get_jwt_identity())
    return jsonify(SourceConnectionService.get_bitbucket_status(user_id)), 200


@source_connections_bp.route('/bitbucket/authorize', methods=['GET'])
@jwt_required()
def bitbucket_authorize():
    redirect_uri = request.args.get('redirect_uri', '')
    if not redirect_uri:
        return jsonify({'error': 'redirect_uri is required'}), 400

    try:
        auth_url, state = SourceConnectionService.generate_bitbucket_authorize_url(redirect_uri)
        return jsonify({'auth_url': auth_url, 'state': state}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@source_connections_bp.route('/bitbucket/callback', methods=['POST'])
@jwt_required()
def bitbucket_callback():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    code = data.get('code', '')
    state = data.get('state', '')
    redirect_uri = data.get('redirect_uri', '')

    if not code or not state or not redirect_uri:
        return jsonify({'error': 'code, state, and redirect_uri are required'}), 400

    try:
        connection = SourceConnectionService.complete_bitbucket_callback(
            user_id=user_id,
            code=code,
            state=state,
            redirect_uri=redirect_uri,
        )
        return jsonify({'connection': connection.to_dict()}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _bitbucket_error(exc)}), 400


@source_connections_bp.route('/bitbucket/repos', methods=['GET'])
@jwt_required()
def bitbucket_repositories():
    user_id = int(get_jwt_identity())
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    try:
        repos = SourceConnectionService.list_bitbucket_repositories(user_id, search, page, per_page)
        return jsonify({'repos': repos}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _bitbucket_error(exc)}), 400


@source_connections_bp.route('/bitbucket/repos/<path:full_name>/branches', methods=['GET'])
@jwt_required()
def bitbucket_branches(full_name):
    user_id = int(get_jwt_identity())

    try:
        branches = SourceConnectionService.list_bitbucket_branches(user_id, full_name)
        return jsonify({'branches': branches}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _bitbucket_error(exc)}), 400


@source_connections_bp.route('/bitbucket/repos/<path:full_name>/manifest', methods=['GET'])
@jwt_required()
def bitbucket_repository_manifest(full_name):
    user_id = int(get_jwt_identity())
    ref = request.args.get('ref') or None

    try:
        manifest = SourceConnectionService.get_bitbucket_repository_manifest(user_id, full_name, ref)
        return jsonify({'manifest': manifest}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except HTTPError as exc:
        return jsonify({'error': _bitbucket_error(exc)}), 400


@source_connections_bp.route('/bitbucket', methods=['DELETE'])
@jwt_required()
def disconnect_bitbucket():
    user_id = int(get_jwt_identity())
    try:
        SourceConnectionService.disconnect(user_id, 'bitbucket')
        return jsonify({'message': 'Bitbucket disconnected'}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404


@source_connections_bp.route('/admin/bitbucket', methods=['GET'])
@admin_required
def bitbucket_admin_config():
    return jsonify({'config': SourceConnectionService.get_bitbucket_config(redacted=True)}), 200


@source_connections_bp.route('/admin/bitbucket', methods=['PUT'])
@admin_required
def update_bitbucket_admin_config():
    user = get_current_user()
    result = SourceConnectionService.update_bitbucket_config(
        request.get_json() or {},
        user_id=user.id if user else None,
    )
    return jsonify(result), 200


def _bitbucket_error(exc):
    response = getattr(exc, 'response', None)
    if response is None:
        return str(exc)
    try:
        data = response.json()
        return data.get('error_description') or data.get('error', {}).get('message') or data.get('message') or str(exc)
    except Exception:
        return response.text or str(exc)
