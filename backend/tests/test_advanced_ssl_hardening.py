"""Trust bugs in the wildcard/SAN certbot path.

The advanced SSL service ran certbot unprivileged (it cannot write
/etc/letsencrypt that way) and returned ``success: True`` without looking at
the result, so a failed issuance reported the would-be cert paths as if they
existed. Cloudflare credentials went to a predictable ``/tmp`` path and were
never deleted. Both issuance entry points are asserted here against the
``run_privileged`` seam, plus the domain validation that keeps crafted
domains from being parsed as certbot flags.
"""

import os
import stat

import pytest

import app.services.advanced_ssl_service as mod
from app.services.advanced_ssl_service import AdvancedSSLService
from subprocess_stub import FakeProc


def _must_not_run_unprivileged(cmd, **kw):
    raise AssertionError(
        f'certbot must run through run_privileged, got run_unprivileged({cmd!r})')


@pytest.fixture
def certbot(monkeypatch):
    """run_privileged seam captured; PackageManager and the unprivileged door
    are both taken out — certbot has no business running unprivileged."""
    from app.utils.system import PackageManager

    monkeypatch.setattr(PackageManager, 'is_available', staticmethod(lambda: False))
    monkeypatch.setattr(mod, 'run_unprivileged', _must_not_run_unprivileged)

    captured = {}

    def fake_run(cmd, **kw):
        captured['cmd'] = list(cmd)
        captured['kw'] = kw
        return captured['proc']

    monkeypatch.setattr(mod, 'run_privileged', fake_run)
    return captured


class TestWildcardIssuance:
    def test_a_failed_certbot_is_a_failure_never_cert_paths(self, certbot):
        certbot['proc'] = FakeProc(returncode=1, stderr='DNS problem: NXDOMAIN')

        res = AdvancedSSLService.issue_wildcard_cert(
            'example.com', 'cloudflare', {'api_token': 'tok'})

        assert res['success'] is False
        assert 'NXDOMAIN' in res['error']
        assert 'certificate_path' not in res, 'a failed issuance reported cert paths'

    def test_a_successful_certbot_reports_the_cert_paths(self, certbot):
        certbot['proc'] = FakeProc(stdout='Congratulations!')

        res = AdvancedSSLService.issue_wildcard_cert(
            'example.com', 'cloudflare', {'api_token': 'tok'})

        assert res['success'] is True
        assert res['certificate_path'] == '/etc/letsencrypt/live/example.com/fullchain.pem'
        assert res['private_key_path'] == '/etc/letsencrypt/live/example.com/privkey.pem'

    def test_an_unsupported_provider_is_refused(self, certbot):
        res = AdvancedSSLService.issue_wildcard_cert(
            'example.com', 'digitalocean', {'api_token': 'tok'})
        assert res['success'] is False
        assert 'cmd' not in certbot, 'certbot ran for an unsupported provider'


class TestCloudflareCredentialsFile:
    """The API token sits on disk while certbot runs: the file must be
    unpredictable, owner-only, and gone afterwards — whatever the outcome."""

    def _run_with_creds_probe(self, monkeypatch, proc):
        """Replace the fixture responder with one that inspects the
        credentials file mid-run (the fixture only sees argv afterwards)."""
        seen = {}

        def fake_run(cmd, **kw):
            path = cmd[cmd.index('--dns-cloudflare-credentials') + 1]
            seen['path'] = path
            seen['existed_during_run'] = os.path.isfile(path)
            if os.name != 'nt':
                seen['mode'] = stat.S_IMODE(os.stat(path).st_mode)
            return proc

        monkeypatch.setattr(mod, 'run_privileged', fake_run)
        return seen

    def test_credentials_file_lifecycle(self, certbot, monkeypatch):
        seen = self._run_with_creds_probe(monkeypatch, FakeProc(stdout='Congratulations!'))

        res = AdvancedSSLService.issue_wildcard_cert(
            'example.com', 'cloudflare', {'api_token': 'tok'})

        assert res['success'] is True
        assert seen['path'] != '/tmp/certbot-cloudflare.ini', 'predictable path'
        assert seen['existed_during_run'] is True
        if os.name != 'nt':
            assert seen['mode'] == 0o600
        assert not os.path.exists(seen['path']), 'credentials file left behind'

    def test_credentials_file_is_deleted_even_when_certbot_fails(self, certbot, monkeypatch):
        seen = self._run_with_creds_probe(monkeypatch, FakeProc(returncode=1, stderr='boom'))

        res = AdvancedSSLService.issue_wildcard_cert(
            'example.com', 'cloudflare', {'api_token': 'tok'})

        assert res['success'] is False
        assert not os.path.exists(seen['path']), 'failed run left credentials behind'


class TestSanIssuance:
    def test_a_failed_certbot_is_a_failure(self, certbot):
        certbot['proc'] = FakeProc(returncode=1, stderr='webroot unreachable')

        res = AdvancedSSLService.issue_san_cert(['a.example.com', 'b.example.com'])

        assert res['success'] is False
        assert 'webroot unreachable' in res['error']

    def test_a_successful_certbot_reports_the_domains(self, certbot):
        certbot['proc'] = FakeProc(stdout='Congratulations!')

        res = AdvancedSSLService.issue_san_cert(['a.example.com', 'b.example.com'])

        assert res['success'] is True
        assert res['domains'] == ['a.example.com', 'b.example.com']
        for d in ('a.example.com', 'b.example.com'):
            assert d in certbot['cmd']


class TestDomainValidation:
    """A crafted domain must not survive into certbot argv, where a leading
    dash would be parsed as a flag, nor into the custom-cert file path."""

    def test_wildcard_rejects_a_flag_like_domain(self, certbot):
        res = AdvancedSSLService.issue_wildcard_cert(
            '--cert-name=evil', 'cloudflare', {'api_token': 'tok'})
        assert res['success'] is False
        assert 'cmd' not in certbot, 'certbot ran for an invalid domain'

    def test_wildcard_rejects_shell_metacharacters(self, certbot):
        res = AdvancedSSLService.issue_wildcard_cert(
            'example.com; rm -rf /', 'cloudflare', {'api_token': 'tok'})
        assert res['success'] is False
        assert 'cmd' not in certbot

    def test_san_rejects_one_bad_domain_out_of_many(self, certbot):
        res = AdvancedSSLService.issue_san_cert(['good.example.com', '--expand'])
        assert res['success'] is False
        assert 'cmd' not in certbot

    def test_upload_custom_cert_rejects_traversal(self):
        with pytest.raises(ValueError):
            AdvancedSSLService.upload_custom_cert('../../etc/cron.d', 'cert', 'key')
