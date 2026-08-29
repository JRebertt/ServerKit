"""Prove the serverkit-git backend split (plan 52 Phase 6).

The Gitea self-host half (server lifecycle + repo browsing) moved into the
serverkit-git extension; the deploy-side git CLI operations and the webhook +
deployment routes stay core — they ARE the deploy pipeline and must never
depend on the extension. These tests pin the absent-extension shape.
"""
from app.services.git_service import GitService


GITEA_ROUTES = [
    '/api/v1/git/status',
    '/api/v1/git/requirements',
    '/api/v1/git/install',
    '/api/v1/git/repos',
    '/api/v1/git/version',
]

CORE_GIT_ROUTES = [
    '/api/v1/git/webhooks',
    '/api/v1/git/webhooks/receive/<token>',
    '/api/v1/git/deployments/app/<int:app_id>',
    '/api/v1/git/deployments/<int:deployment_id>',
]


def test_gitea_routes_are_unrouted_without_extension(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    for path in GITEA_ROUTES:
        assert path not in rules, f'{path}: Gitea route still in core'


def test_deploy_pipeline_routes_stay_core(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    for path in CORE_GIT_ROUTES:
        assert path in rules, f'{path}: deploy-pipeline route missing from core'


def test_gitea_routes_404_before_auth(client):
    for path in ('/api/v1/git/status', '/api/v1/git/repos'):
        resp = client.get(path)
        assert resp.status_code == 404, f'{path} -> {resp.status_code}'


def test_git_service_shed_the_gitea_half():
    for gone in [
        'get_gitea_status', 'install_gitea', 'uninstall_gitea',
        'start_gitea', 'stop_gitea', 'restart_gitea',
        'get_gitea_resource_requirements', 'GITEA_APP_NAME',
    ]:
        assert not hasattr(GitService, gone), f'GitService.{gone} still exists'


def test_git_service_keeps_the_deploy_half():
    """The 5 core importers (apps/buildpacks/deploy/deployment/manifest_apply)
    keep every method they call."""
    for kept in [
        'get_config', 'save_config', 'get_app_config', 'configure_deployment',
        'remove_deployment', 'clone_repository', 'pull_changes',
        'get_commit_info', 'deploy', '_run_script', 'verify_webhook',
        'get_remote_branches', 'get_remote_branches_from_url', 'handle_webhook',
        'get_deployment_history', 'get_git_status', 'log_webhook',
        'get_webhook_logs',
    ]:
        assert hasattr(GitService, kept), f'GitService.{kept} missing'


def test_gitea_api_service_left_core():
    import pytest
    with pytest.raises(ImportError):
        __import__('app.services.gitea_api_service')


def test_nginx_gitea_helpers_stay_core():
    """Deliberate core seam (the WP two-speed shape): the extension's
    install/uninstall call these; they must keep existing in core."""
    from app.services.nginx_service import NginxService
    for kept in ('create_gitea_config', 'remove_gitea_config', 'get_gitea_config'):
        assert hasattr(NginxService, kept)
