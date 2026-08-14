"""Tests for certbot binary resolution and the nginx-plugin preflight.

Plan 73 item 1: certbot's recommended install is snap (/snap/bin/certbot),
but the service used to hardcode /usr/bin/certbot, and issuance with
``--nginx`` had no preflight for the nginx plugin — certbot's raw confusion
was passed through to the panel. Pure unit tests: subprocess is mocked, no
certbot/nginx needed.
"""

import subprocess
from unittest.mock import patch

import pytest

from app.services import ssl_service
from app.services.ssl_service import SSLService, resolve_certbot_bin


@pytest.fixture(autouse=True)
def _clear_resolution_cache():
    ssl_service.reset_certbot_resolution_cache()
    yield
    ssl_service.reset_certbot_resolution_cache()


# ---------------------------------------------------------------------------
# resolve_certbot_bin
# ---------------------------------------------------------------------------
class TestResolveCertbotBin:

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv('CERTBOT_BIN', '/opt/custom/certbot')
        with patch('app.services.ssl_service.shutil.which',
                   return_value='/usr/bin/certbot'):
            assert resolve_certbot_bin() == '/opt/custom/certbot'

    def test_path_lookup_before_candidates(self, monkeypatch):
        monkeypatch.delenv('CERTBOT_BIN', raising=False)
        with patch('app.services.ssl_service.shutil.which',
                   return_value='/usr/local/bin/certbot'), \
                patch('app.services.ssl_service.os.path.isfile', return_value=True):
            assert resolve_certbot_bin() == '/usr/local/bin/certbot'

    def test_snap_only_install_is_found(self, monkeypatch):
        """certbot present only at /snap/bin/certbot (snap install) resolves."""
        monkeypatch.delenv('CERTBOT_BIN', raising=False)
        with patch('app.services.ssl_service.shutil.which', return_value=None), \
                patch('app.services.ssl_service.os.path.isfile',
                      side_effect=lambda p: p == '/snap/bin/certbot'), \
                patch('app.services.ssl_service.os.access', return_value=True):
            assert resolve_certbot_bin() == '/snap/bin/certbot'

    def test_usr_bin_candidate(self, monkeypatch):
        monkeypatch.delenv('CERTBOT_BIN', raising=False)
        with patch('app.services.ssl_service.shutil.which', return_value=None), \
                patch('app.services.ssl_service.os.path.isfile',
                      side_effect=lambda p: p == '/usr/bin/certbot'), \
                patch('app.services.ssl_service.os.access', return_value=True):
            assert resolve_certbot_bin() == '/usr/bin/certbot'

    def test_returns_none_when_missing(self, monkeypatch):
        monkeypatch.delenv('CERTBOT_BIN', raising=False)
        with patch('app.services.ssl_service.shutil.which', return_value=None), \
                patch('app.services.ssl_service.os.path.isfile', return_value=False):
            assert resolve_certbot_bin() is None

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.setenv('CERTBOT_BIN', '/opt/custom/certbot')
        with patch('app.services.ssl_service.shutil.which',
                   return_value='/usr/bin/certbot') as mock_which:
            resolve_certbot_bin()
            resolve_certbot_bin()
            mock_which.assert_not_called()

    def test_certbot_bin_falls_back_to_usr_bin(self, monkeypatch):
        monkeypatch.delenv('CERTBOT_BIN', raising=False)
        with patch('app.services.ssl_service.shutil.which', return_value=None), \
                patch('app.services.ssl_service.os.path.isfile', return_value=False):
            assert SSLService.certbot_bin() == SSLService.CERTBOT_FALLBACK


# ---------------------------------------------------------------------------
# nginx-plugin preflight in obtain_certificate
# ---------------------------------------------------------------------------
class TestNginxPluginPreflight:
    """obtain_certificate(use_nginx=True) must fail with an actionable error
    before ever invoking certbot for issuance when the nginx setup is broken."""

    def _obtain(self, monkeypatch, plugins_stdout=None, plugins_rc=0,
                nginx_available=True, certbot_path='/usr/bin/certbot',
                issue_rc=1, issue_stderr='boom'):
        """Drive obtain_certificate with fully mocked system interaction.

        Returns (result, calls) where calls is every command passed to
        run_privileged.
        """
        calls = []

        def fake_run_privileged(cmd, **kwargs):
            calls.append(cmd)
            if 'plugins' in cmd:
                return subprocess.CompletedProcess(
                    cmd, plugins_rc, stdout=plugins_stdout or '', stderr='')
            return subprocess.CompletedProcess(
                cmd, issue_rc, stdout='', stderr=issue_stderr)

        monkeypatch.setattr(
            SSLService, 'is_certbot_installed', classmethod(lambda cls: True))
        with patch('app.services.ssl_service.run_privileged',
                   side_effect=fake_run_privileged), \
                patch('app.services.ssl_service.is_command_available',
                      side_effect=lambda cmd: nginx_available), \
                patch('app.services.ssl_service.resolve_certbot_bin',
                      return_value=certbot_path):
            result = SSLService.obtain_certificate(
                ['example.com'], 'admin@example.com')
        return result, calls

    def test_missing_nginx_plugin_gives_actionable_error(self, monkeypatch):
        result, calls = self._obtain(
            monkeypatch, plugins_stdout='* standalone\n* webroot\n')

        assert result['success'] is False
        assert 'python3-certbot-nginx' in result['error']
        # certbot was probed for plugins but never invoked for issuance.
        assert not any('certonly' in cmd for cmd in calls)
        assert not any('--nginx' in cmd for cmd in calls)

    def test_missing_nginx_binary_gives_actionable_error(self, monkeypatch):
        result, calls = self._obtain(monkeypatch, nginx_available=False)

        assert result['success'] is False
        assert 'nginx binary not found' in result['error']
        # Not even the plugins probe runs — certbot is never invoked.
        assert calls == []

    def test_preflight_ok_invokes_certbot_with_nginx(self, monkeypatch):
        result, calls = self._obtain(
            monkeypatch, plugins_stdout='* nginx\n* standalone\n',
            certbot_path='/snap/bin/certbot',
            issue_rc=1, issue_stderr='real certbot failure')

        issuance = [cmd for cmd in calls if 'certonly' in cmd]
        assert len(issuance) == 1
        assert issuance[0][0] == '/snap/bin/certbot'
        assert '--nginx' in issuance[0]
        # Genuine issuance failures still pass certbot's stderr through raw.
        assert result == {'success': False, 'error': 'real certbot failure'}

    def test_plugin_probe_failure_falls_back_to_package_check(self, monkeypatch):
        calls = []

        def fake_run_privileged(cmd, **kwargs):
            calls.append(cmd)
            # `certbot plugins` itself fails -> fall back to dpkg/rpm check.
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='err')

        monkeypatch.setattr(
            SSLService, 'is_certbot_installed', classmethod(lambda cls: True))
        with patch('app.services.ssl_service.run_privileged',
                   side_effect=fake_run_privileged), \
                patch('app.services.ssl_service.is_command_available',
                      return_value=True), \
                patch('app.services.ssl_service.resolve_certbot_bin',
                      return_value='/usr/bin/certbot'), \
                patch('app.services.ssl_service.PackageManager.is_installed',
                      return_value=True):
            result = SSLService.obtain_certificate(
                ['example.com'], 'admin@example.com')

        # Package check says the plugin is installed, so issuance proceeds
        # (and fails with the passed-through stderr here).
        assert any('certonly' in cmd for cmd in calls)
        assert result == {'success': False, 'error': 'err'}
