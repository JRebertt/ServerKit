"""Gitea self-host routes — the serverkit-git extension's blueprint.

Moved verbatim out of core ``app/api/git.py`` (plan 52 Phase 6) and mounted
back at the same ``/api/v1/git`` prefix when the extension is installed, so
route shapes never change. The webhook receiver and deployment routes STAY
core on ``git_bp`` — they are the deploy pipeline.
"""
from flask import Blueprint, request, jsonify

from app.middleware.rbac import admin_required, viewer_required

from .gitea_service import GiteaServerService
from .gitea_api_service import GiteaAPIService

gitea_bp = Blueprint('git_gitea', __name__)


@gitea_bp.route('/status', methods=['GET'])
@viewer_required
def get_status():
    """Get Gitea installation status."""
    result = GiteaServerService.get_gitea_status()
    return jsonify(result), 200


@gitea_bp.route('/requirements', methods=['GET'])
@viewer_required
def get_requirements():
    """Get resource requirements for Gitea installation."""
    result = GiteaServerService.get_gitea_resource_requirements()
    return jsonify(result), 200


@gitea_bp.route('/install', methods=['POST'])
@admin_required
def install():
    """Install Gitea with PostgreSQL."""
    data = request.get_json() or {}

    result = GiteaServerService.install_gitea(
        admin_user=data.get('adminUser', 'admin'),
        admin_email=data.get('adminEmail'),
        admin_password=data.get('adminPassword')
    )

    if result.get('success'):
        return jsonify(result), 201
    return jsonify(result), 400


@gitea_bp.route('/uninstall', methods=['POST'])
@admin_required
def uninstall():
    """Uninstall Gitea and optionally remove data."""
    data = request.get_json() or {}

    result = GiteaServerService.uninstall_gitea(
        remove_data=data.get('removeData', False)
    )

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/start', methods=['POST'])
@admin_required
def start():
    """Start Gitea server."""
    result = GiteaServerService.start_gitea()

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/stop', methods=['POST'])
@admin_required
def stop():
    """Stop Gitea server."""
    result = GiteaServerService.stop_gitea()

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/restart', methods=['POST'])
@admin_required
def restart():
    """Restart Gitea server."""
    result = GiteaServerService.restart_gitea()

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


# ==================== WEBHOOK ENDPOINTS ====================

@gitea_bp.route('/repos', methods=['GET'])
@viewer_required
def list_repositories():
    """List all repositories in Gitea."""
    token = request.args.get('token')
    limit = request.args.get('limit', 50, type=int)

    result = GiteaAPIService.list_repositories(token=token, limit=limit)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/repos/<owner>/<repo>', methods=['GET'])
@viewer_required
def get_repository(owner, repo):
    """Get repository details."""
    token = request.args.get('token')

    result = GiteaAPIService.get_repository(owner, repo, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 404


@gitea_bp.route('/repos/<owner>/<repo>/stats', methods=['GET'])
@viewer_required
def get_repo_stats(owner, repo):
    """Get repository statistics."""
    token = request.args.get('token')

    result = GiteaAPIService.get_repo_stats(owner, repo, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/repos/<owner>/<repo>/branches', methods=['GET'])
@viewer_required
def list_branches(owner, repo):
    """List repository branches."""
    token = request.args.get('token')

    result = GiteaAPIService.list_branches(owner, repo, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/repos/<owner>/<repo>/branches/<branch>', methods=['GET'])
@viewer_required
def get_branch(owner, repo, branch):
    """Get branch details."""
    token = request.args.get('token')

    result = GiteaAPIService.get_branch(owner, repo, branch, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 404


@gitea_bp.route('/repos/<owner>/<repo>/commits', methods=['GET'])
@viewer_required
def list_commits(owner, repo):
    """List repository commits."""
    token = request.args.get('token')
    branch = request.args.get('branch')
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 30, type=int)

    result = GiteaAPIService.list_commits(
        owner, repo,
        branch=branch,
        page=page,
        limit=limit,
        token=token
    )

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/repos/<owner>/<repo>/commits/<sha>', methods=['GET'])
@viewer_required
def get_commit(owner, repo, sha):
    """Get commit details."""
    token = request.args.get('token')

    result = GiteaAPIService.get_commit(owner, repo, sha, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 404


@gitea_bp.route('/repos/<owner>/<repo>/contents', methods=['GET'])
@viewer_required
def list_files(owner, repo):
    """List files in repository directory."""
    token = request.args.get('token')
    ref = request.args.get('ref', 'main')
    path = request.args.get('path', '')

    result = GiteaAPIService.list_files(owner, repo, ref=ref, path=path, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


@gitea_bp.route('/repos/<owner>/<repo>/contents/<path:filepath>', methods=['GET'])
@viewer_required
def get_file_content(owner, repo, filepath):
    """Get file content."""
    token = request.args.get('token')
    ref = request.args.get('ref', 'main')

    result = GiteaAPIService.get_file_content(owner, repo, filepath, ref=ref, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 404


@gitea_bp.route('/repos/<owner>/<repo>/readme', methods=['GET'])
@viewer_required
def get_readme(owner, repo):
    """Get repository README."""
    token = request.args.get('token')
    ref = request.args.get('ref')

    result = GiteaAPIService.get_readme(owner, repo, ref=ref, token=token)

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 404


@gitea_bp.route('/version', methods=['GET'])
@viewer_required
def get_gitea_version():
    """Get Gitea server version."""
    result = GiteaAPIService.get_server_version()

    if result.get('success'):
        return jsonify(result), 200
    return jsonify(result), 400


# ==================== DEPLOYMENT ENDPOINTS ====================
