"""Regression tests for GHSA-8vx6-432p-h62q — authenticated argument injection
into git subprocesses (repo_url transport selection, --upload-pack option
injection via app_path, branch refspec injection).

Pure unit tests: validators are exercised directly, and the git services are
tested with subprocess.run mocked so no git binary or network is needed.
"""

from unittest import mock

from app.utils.git_security import (
    ALLOWED_REPO_SCHEMES,
    git_argv,
    git_env,
    validate_clone_path,
    validate_ref_name,
    validate_repo_url,
)
from app.services.git_service import GitService
from app.services.git_deploy_service import GitDeployService


# --------------------------------------------------------------------------- #
# validate_repo_url
# --------------------------------------------------------------------------- #
class TestValidateRepoUrl:
    def test_accepts_https(self):
        assert validate_repo_url('https://github.com/org/repo.git') is None

    def test_accepts_http_git_ssh_schemes(self):
        assert validate_repo_url('http://git.example.com/org/repo.git') is None
        assert validate_repo_url('git://git.example.com/org/repo.git') is None
        assert validate_repo_url('ssh://git@example.com/org/repo.git') is None

    def test_accepts_scp_like_ssh(self):
        assert validate_repo_url('git@github.com:org/repo.git') is None

    def test_rejects_ext_transport(self):
        assert validate_repo_url('ext::sh -c id>&2') is not None
        assert validate_repo_url('fd::17/foo') is not None

    def test_rejects_file_scheme(self):
        assert validate_repo_url('file:///etc/secret-repo') is not None

    def test_rejects_local_paths(self):
        assert validate_repo_url('/var/serverkit/apps/seed') is not None
        assert validate_repo_url('../outside') is not None
        assert validate_repo_url('relative/path') is not None

    def test_rejects_leading_dash(self):
        assert validate_repo_url('--upload-pack=evil') is not None

    def test_rejects_whitespace_and_control_chars(self):
        assert validate_repo_url('https://example.com/a b.git') is not None
        assert validate_repo_url('https://example.com/a\nb.git') is not None

    def test_rejects_empty(self):
        assert validate_repo_url('') is not None
        assert validate_repo_url(None) is not None
        assert validate_repo_url('   ') is not None


# --------------------------------------------------------------------------- #
# validate_ref_name
# --------------------------------------------------------------------------- #
class TestValidateRefName:
    def test_accepts_common_branch_names(self):
        assert validate_ref_name('main') is None
        assert validate_ref_name('feature/login-page') is None
        assert validate_ref_name('release-1.2.3') is None

    def test_absent_ref_is_allowed(self):
        assert validate_ref_name(None) is None
        assert validate_ref_name('') is None

    def test_rejects_option_injection(self):
        assert validate_ref_name('--upload-pack=sh -c id') is not None
        assert validate_ref_name('-oFoo') is not None

    def test_rejects_ref_metacharacters(self):
        assert validate_ref_name('foo..bar') is not None
        assert validate_ref_name('foo bar') is not None
        assert validate_ref_name('foo:bar') is not None
        assert validate_ref_name('foo@{bar') is not None


# --------------------------------------------------------------------------- #
# validate_clone_path
# --------------------------------------------------------------------------- #
class TestValidateClonePath:
    def test_accepts_absolute_path(self):
        assert validate_clone_path('/var/serverkit/apps/myapp') is None

    def test_rejects_option_injection(self):
        assert validate_clone_path('--upload-pack=sh -c "id>&2"') is not None

    def test_rejects_relative_path(self):
        assert validate_clone_path('apps/myapp') is not None

    def test_rejects_empty(self):
        assert validate_clone_path('') is not None
        assert validate_clone_path(None) is not None


# --------------------------------------------------------------------------- #
# argv/env helpers
# --------------------------------------------------------------------------- #
class TestHelpers:
    def test_git_argv_pins_protocols(self):
        argv = git_argv('ls-remote', '--heads', '--', 'https://x/y.git')
        assert argv[:5] == [
            'git',
            '-c', 'protocol.ext.allow=never',
            '-c', 'protocol.file.allow=never',
        ]
        assert argv[-4:] == ['ls-remote', '--heads', '--', 'https://x/y.git']

    def test_git_env_restricts_protocols(self):
        env = git_env()
        assert env['GIT_ALLOW_PROTOCOL'] == ':'.join(ALLOWED_REPO_SCHEMES)
        assert 'ext' not in env['GIT_ALLOW_PROTOCOL'].split(':')
        assert 'file' not in env['GIT_ALLOW_PROTOCOL'].split(':')


# --------------------------------------------------------------------------- #
# GitService.clone_repository
# --------------------------------------------------------------------------- #
class TestCloneRepository:
    def _run_clone(self, app_path='/tmp/sk-clone-target', repo_url='https://x/y.git',
                   branch='main'):
        completed = mock.Mock(returncode=0, stdout='', stderr='')
        with mock.patch('app.services.git_service.subprocess.run',
                        return_value=completed) as run_mock, \
             mock.patch('app.services.git_service.os.path.exists', return_value=False):
            result = GitService.clone_repository(app_path, repo_url, branch)
        return result, run_mock

    def test_valid_clone_invocation_is_hardened(self):
        result, run_mock = self._run_clone()
        assert result['success'] is True
        argv = run_mock.call_args[0][0]
        # Protocol pinning present.
        assert 'protocol.ext.allow=never' in argv
        assert 'protocol.file.allow=never' in argv
        # '--' terminator separates options from positionals.
        terminator = argv.index('--')
        assert argv[terminator + 1] == 'https://x/y.git'
        assert argv[terminator + 2] == '/tmp/sk-clone-target'
        # Restrictive protocol env.
        assert run_mock.call_args[1]['env']['GIT_ALLOW_PROTOCOL'] == 'https:http:git:ssh'

    def test_ext_transport_rejected_without_subprocess(self):
        result, run_mock = self._run_clone(repo_url='ext::sh -c id>&2')
        assert result['success'] is False
        run_mock.assert_not_called()

    def test_file_scheme_rejected_without_subprocess(self):
        result, run_mock = self._run_clone(repo_url='file:///etc/repo')
        assert result['success'] is False
        run_mock.assert_not_called()

    def test_local_path_repo_rejected_without_subprocess(self):
        result, run_mock = self._run_clone(repo_url='/var/serverkit/apps/seed')
        assert result['success'] is False
        run_mock.assert_not_called()

    def test_upload_pack_option_in_app_path_rejected_without_subprocess(self):
        result, run_mock = self._run_clone(
            app_path='--upload-pack=sh -c "id>&2"')
        assert result['success'] is False
        run_mock.assert_not_called()

    def test_malicious_branch_rejected_without_subprocess(self):
        result, run_mock = self._run_clone(branch='--upload-pack=evil')
        assert result['success'] is False
        run_mock.assert_not_called()


# --------------------------------------------------------------------------- #
# GitService.get_remote_branches_from_url
# --------------------------------------------------------------------------- #
class TestGetRemoteBranchesFromUrl:
    def _run_ls_remote(self, repo_url):
        completed = mock.Mock(returncode=0, stdout='abc123\trefs/heads/main\n',
                              stderr='')
        with mock.patch('app.services.git_service.subprocess.run',
                        return_value=completed) as run_mock:
            result = GitService.get_remote_branches_from_url(repo_url)
        return result, run_mock

    def test_valid_url_uses_terminator_and_pinning(self):
        result, run_mock = self._run_ls_remote('https://github.com/org/repo.git')
        assert result['success'] is True
        assert result['branches'] == ['main']
        argv = run_mock.call_args[0][0]
        assert 'protocol.ext.allow=never' in argv
        assert argv[-2:] == ['--', 'https://github.com/org/repo.git']

    def test_ext_transport_rejected_without_subprocess(self):
        result, run_mock = self._run_ls_remote('ext::sh -c id>&2')
        assert result['success'] is False
        run_mock.assert_not_called()

    def test_file_scheme_rejected_without_subprocess(self):
        result, run_mock = self._run_ls_remote('file:///etc/repo')
        assert result['success'] is False
        run_mock.assert_not_called()

    def test_leading_dash_rejected_without_subprocess(self):
        result, run_mock = self._run_ls_remote('--upload-pack=evil')
        assert result['success'] is False
        run_mock.assert_not_called()


# --------------------------------------------------------------------------- #
# GitDeployService._git_pull
# --------------------------------------------------------------------------- #
class TestGitPull:
    def _run_pull(self, branch='main'):
        completed = mock.Mock(returncode=0, stdout='', stderr='')
        with mock.patch('app.services.git_deploy_service.subprocess.run',
                        return_value=completed) as run_mock, \
             mock.patch('app.services.git_deploy_service.os.path.exists',
                        return_value=True):
            result = GitDeployService._git_pull('/srv/app', branch)
        return result, run_mock

    def test_fetch_uses_terminator(self):
        result, run_mock = self._run_pull('main')
        assert result['success'] is True
        fetch_argv = run_mock.call_args_list[0][0][0]
        assert fetch_argv[-3:] == ['origin', '--', 'main']
        assert 'protocol.ext.allow=never' in fetch_argv

    def test_malicious_branch_rejected_without_subprocess(self):
        result, run_mock = self._run_pull('--upload-pack=evil')
        assert result['success'] is False
        run_mock.assert_not_called()
