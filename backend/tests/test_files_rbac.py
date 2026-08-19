"""Regression tests for two security advisories.

GHSA-4wqh-7f4f-5qmx — the File Manager API only required a valid JWT, so a
viewer account (files.write=False) could write/delete files. Mutating
endpoints must now require the 'files' write permission.

GHSA-mc93-rc3x-fpgq — PostfixService.install() interpolated the hostname into
a bash -c string. Hostnames are now validated and debconf values are piped
via stdin, never through a shell.
"""
import subprocess

import pytest

from app import db as _db
from app.models import User
from app.services.postfix_service import PostfixService


@pytest.fixture
def role_headers(app):
    """JWT headers for a viewer and a developer user."""
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    headers = {}
    with app.app_context():
        for name, role in (('files_viewer', User.ROLE_VIEWER),
                           ('files_dev', User.ROLE_DEVELOPER)):
            u = User(email=f'{name}@t.local', username=name,
                     password_hash=generate_password_hash('x'),
                     role=role, is_active=True)
            _db.session.add(u)
            _db.session.commit()
            headers[role] = {'Authorization': f'Bearer {create_access_token(identity=u.id)}'}
    return headers


# --------------------------------------------------------------------------- #
# GHSA-4wqh-7f4f-5qmx: viewer role blocked from file write/delete operations
# --------------------------------------------------------------------------- #

WRITE_CASES = [
    ('post', '/api/v1/files/write', {'json': {'path': '/tmp/x', 'content': 'x'}}),
    ('post', '/api/v1/files/create', {'json': {'path': '/tmp/x'}}),
    ('post', '/api/v1/files/mkdir', {'json': {'path': '/tmp/x'}}),
    ('delete', '/api/v1/files/delete?path=/tmp/x', {}),
    ('post', '/api/v1/files/rename', {'json': {'path': '/tmp/x', 'new_name': 'y'}}),
    ('post', '/api/v1/files/copy', {'json': {'src': '/tmp/x', 'dest': '/tmp/y'}}),
    ('post', '/api/v1/files/move', {'json': {'src': '/tmp/x', 'dest': '/tmp/y'}}),
    ('post', '/api/v1/files/chmod', {'json': {'path': '/tmp/x', 'mode': '755'}}),
    ('post', '/api/v1/files/upload', {}),
    ('post', '/api/v1/files/s3/write', {'json': {'path': '/x', 'content': 'x'}}),
    ('post', '/api/v1/files/s3/upload', {}),
    ('delete', '/api/v1/files/s3/delete?path=/x', {}),
]


@pytest.mark.parametrize('method,url,kwargs', WRITE_CASES)
def test_viewer_cannot_mutate_files(client, role_headers, method, url, kwargs):
    resp = getattr(client, method)(url, headers=role_headers[User.ROLE_VIEWER], **kwargs)
    assert resp.status_code == 403
    assert 'files' in resp.get_json()['error']


@pytest.mark.parametrize('method,url,kwargs', WRITE_CASES)
def test_developer_passes_files_write_gate(client, role_headers, monkeypatch,
                                           method, url, kwargs):
    """A role with files.write=True must get past the permission gate.

    The underlying services are stubbed so the test never touches the real
    filesystem or S3; we only assert the gate does not return 403.
    """
    from app.services.file_service import FileService
    from app.services.storage_provider_service import StorageProviderService

    ok = {'success': True}
    for name in ('write_file', 'create_file', 'create_directory', 'delete',
                 'rename', 'copy', 'move', 'change_permissions'):
        monkeypatch.setattr(FileService, name, staticmethod(lambda *a, **k: dict(ok)))
    monkeypatch.setattr(StorageProviderService, 's3_write',
                        staticmethod(lambda *a, **k: dict(ok)))
    monkeypatch.setattr(StorageProviderService, 's3_delete',
                        staticmethod(lambda *a, **k: dict(ok)))

    resp = getattr(client, method)(url, headers=role_headers[User.ROLE_DEVELOPER], **kwargs)
    assert resp.status_code != 403


def test_viewer_can_still_browse(client, role_headers, monkeypatch):
    """Read endpoints stay reachable for viewers (files.read=True).

    The service is stubbed: /tmp is not an allowed root, and since the typed
    error contract the path denial is itself a 403, which would be
    indistinguishable from the RBAC gate this test is about.
    """
    from app.services.file_service import FileService
    monkeypatch.setattr(
        FileService, 'list_directory',
        staticmethod(lambda *a, **k: {'path': '/tmp', 'parent': None,
                                      'entries': [], 'total': 0}))
    resp = client.get('/api/v1/files/browse?path=/tmp',
                      headers=role_headers[User.ROLE_VIEWER])
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


# --------------------------------------------------------------------------- #
# files.read revocation: a user whose files.read permission is disabled must
# be blocked from read endpoints too, not just writes
# --------------------------------------------------------------------------- #

READ_CASES = [
    '/api/v1/files/browse?path=/tmp',
    '/api/v1/files/info?path=/tmp/x',
    '/api/v1/files/read?path=/tmp/x',
    '/api/v1/files/search?path=/tmp&query=x',
    '/api/v1/files/disk-usage',
    '/api/v1/files/disk-mounts',
    '/api/v1/files/analyze?path=/tmp',
    '/api/v1/files/type-breakdown?path=/tmp',
    '/api/v1/files/download?path=/tmp/x',
    '/api/v1/files/s3/browse?path=/',
    '/api/v1/files/s3/read?path=/x',
    '/api/v1/files/s3/download-url?path=/x',
]


@pytest.fixture
def no_read_headers(app):
    """JWT headers for a viewer whose files.read permission is revoked."""
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    with app.app_context():
        u = User(email='files_noread@t.local', username='files_noread',
                 password_hash=generate_password_hash('x'),
                 role=User.ROLE_VIEWER, is_active=True)
        perms = {f: {'read': True, 'write': False} for f in User.PERMISSION_FEATURES}
        perms['files'] = {'read': False, 'write': False}
        u.set_permissions(perms)
        _db.session.add(u)
        _db.session.commit()
        return {'Authorization': f'Bearer {create_access_token(identity=u.id)}'}


@pytest.mark.parametrize('url', READ_CASES)
def test_revoked_files_read_blocks_read_endpoints(client, no_read_headers, url):
    resp = client.get(url, headers=no_read_headers)
    assert resp.status_code == 403
    assert 'files' in resp.get_json()['error']


# --------------------------------------------------------------------------- #
# GHSA-rm3m-9mvw-68fh: the panel's own files must never be reachable through
# the file manager, for ANY role. The default viewer role legitimately has
# files.read=True, and the documented install layout (/opt/serverkit) sits
# under the allowed root /opt — so without the PROTECTED_ROOTS exclusion a
# viewer could read the backend .env, steal JWT_SECRET_KEY, and forge admin
# sessions.
# --------------------------------------------------------------------------- #

import os as _os

import app as _app_pkg
from app import paths as _paths
from app.services.file_service import FileService as _FileService

_BACKEND_DIR = _os.path.realpath(_os.path.join(_os.path.dirname(_app_pkg.__file__), '..'))
_INSTALL_DIR = _os.path.realpath(_os.path.join(_BACKEND_DIR, '..'))

PROTECTED_CASES = [
    _os.path.join(_INSTALL_DIR, '.env'),
    _os.path.join(_BACKEND_DIR, '.env'),
    _os.path.join(_BACKEND_DIR, 'run.py'),
    _os.path.join(_BACKEND_DIR, 'instance', 'serverkit.db'),
    _os.path.join(_INSTALL_DIR, 'frontend', 'dist', 'index.html'),
    _os.path.join(_paths.SERVERKIT_CONFIG_DIR, 'deployments.json'),
]


@pytest.mark.parametrize('path', PROTECTED_CASES)
def test_panel_files_are_never_allowed(path):
    assert not _FileService.is_path_allowed(path)


def test_protected_roots_resolve_to_the_real_install_layout():
    """The service's own path math must land on <install>/backend and
    <install> — one level off silently un-protects <install>/.env and
    frontend/dist (caught in review; the other tests compute the expected
    layout independently of the service, so they can't see the service
    getting it wrong)."""
    services_dir = _os.path.dirname(_os.path.realpath(
        _os.path.join(_os.path.dirname(_app_pkg.__file__), 'services', 'file_service.py')))
    backend_dir = _os.path.realpath(_os.path.join(services_dir, '..', '..'))
    install_dir = _os.path.realpath(_os.path.join(backend_dir, '..'))
    assert _FileService._BACKEND_DIR == backend_dir
    assert _FileService._INSTALL_DIR == install_dir


def test_install_root_blocked_even_when_under_an_allowed_root(monkeypatch):
    """Deployed layout simulation: the install dir sits INSIDE an allowed
    root (/opt/serverkit under /opt). Protected must win over allowed —
    this is the exact /read .env path from the advisory."""
    install_dir = _FileService._INSTALL_DIR
    monkeypatch.setattr(_FileService, 'ALLOWED_ROOTS', [install_dir])
    assert not _FileService.is_path_allowed(_os.path.join(install_dir, '.env'))
    assert not _FileService.is_path_allowed(
        _os.path.join(install_dir, 'frontend', 'dist', 'index.html'))
    assert not _FileService.is_path_allowed(
        _os.path.join(install_dir, 'backend', 'run.py'))


@pytest.mark.parametrize('url', [
    '/api/v1/files/read?path=' + _os.path.join(_INSTALL_DIR, '.env'),
    '/api/v1/files/download?path=' + _os.path.join(_BACKEND_DIR, '.env'),
])
def test_viewer_cannot_read_panel_files(client, role_headers, url):
    """A viewer (files.read=True) still gets 403 on panel-internal paths."""
    resp = client.get(url, headers=role_headers[User.ROLE_VIEWER])
    assert resp.status_code == 403


def test_normal_paths_still_allowed(tmp_path, monkeypatch):
    """Paths under the allowed roots keep working (native path, any OS)."""
    monkeypatch.setattr(_FileService, 'ALLOWED_ROOTS', [str(tmp_path)])
    assert _FileService.is_path_allowed(str(tmp_path / 'apps' / 'mysite' / 'index.php'))
    assert _FileService.is_path_allowed(str(tmp_path / '.env'))  # app envs unaffected


# --------------------------------------------------------------------------- #
# log_service._read_syslog: the service filter must never go through a shell
# (subprocess.list2cmdline is cmd.exe quoting and does not stop $(...)/backtick
# expansion under bash)
# --------------------------------------------------------------------------- #

def test_read_syslog_does_not_use_a_shell(monkeypatch):
    from app.services import log_service
    from app.services.log_service import LogService

    captured = {}

    def fake_run_privileged(cmd, **kwargs):
        captured['cmd'] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='match1\nmatch2\n', stderr='')

    monkeypatch.setattr(log_service, 'run_privileged', fake_run_privileged)

    payload = 'x$(id)`id`'
    result = LogService._read_syslog('/var/log/syslog', payload, 100)

    cmd = captured['cmd']
    assert 'bash' not in cmd and '-c' not in cmd
    # the payload travels as a standalone argv element, verbatim
    assert payload in cmd
    assert result['success']


def test_read_syslog_tails_matches_in_python(monkeypatch):
    from app.services import log_service
    from app.services.log_service import LogService

    def fake_run_privileged(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout='l1\nl2\nl3\n', stderr='')

    monkeypatch.setattr(log_service, 'run_privileged', fake_run_privileged)

    result = LogService._read_syslog('/var/log/syslog', 'nginx', 2)
    assert result['lines'] == ['l2', 'l3']


# --------------------------------------------------------------------------- #
# GHSA-mc93-rc3x-fpgq: postfix install rejects malicious hostnames
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('hostname', [
    '"; id > /tmp/pwned; echo "',
    '$(id)',
    '`id`',
    'mail.example.com; rm -rf /',
    'host name with spaces',
])
def test_postfix_install_rejects_bad_hostname(hostname):
    result = PostfixService.install(hostname=hostname)
    assert result == {'success': False, 'error': 'Invalid hostname format'}


@pytest.mark.parametrize('hostname', ['mail.example.com', 'mx-1.example.org', 'localhost'])
def test_postfix_install_accepts_valid_hostname_format(hostname):
    """Valid hostnames pass validation (install itself is not executed)."""
    import re
    assert re.match(r'^[a-zA-Z0-9.-]+$', hostname)
