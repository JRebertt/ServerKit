"""Tests for the diagnostic support bundle (#25): build, secret scrubbing,
and the admin-only download API."""
import io
import json
import zipfile

import pytest

from app.services import support_bundle_service

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


EXPECTED_MEMBERS = {
    'README.txt', 'meta.json', 'db.json', 'counts.json', 'services.json',
    'settings_shapes.json', 'jobs.json', 'doctor.json', 'log_tail.txt',
}


def _read_all(zip_path_or_bytes):
    """{member: text} for every file in the zip."""
    if isinstance(zip_path_or_bytes, bytes):
        zf = zipfile.ZipFile(io.BytesIO(zip_path_or_bytes))
    else:
        zf = zipfile.ZipFile(zip_path_or_bytes)
    with zf:
        return {name: zf.read(name).decode('utf-8') for name in zf.namelist()}


def _seed_secrets(tmp_path, monkeypatch):
    """Seed a SECRET_KEYS setting, a leaky job failure, and a leaky log file."""
    from app import db
    from app.models import SystemSettings
    from app.jobs.models import Job
    from app.services.settings_service import SettingsService

    secret_key = 'sso_google_client_secret'
    assert secret_key in SettingsService.SECRET_KEYS
    SystemSettings.set(secret_key, 'supersecretvalue123')
    SystemSettings.set('canonical_domain', 'panel.example.com')

    job = Job(kind='backup.policy.run', status=Job.STATUS_FAILED,
              error_message='upload failed: token=abc123LEAKYTOKEN for bucket x')
    db.session.add(job)
    db.session.commit()

    log_file = tmp_path / 'panel.log'
    log_file.write_text(
        'INFO booting\n'
        'DEBUG auth header Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXNlZ21lbnQ\n'
        'ERROR db password=hunter2 rejected\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(support_bundle_service, 'LOG_FILE_CANDIDATES', (str(log_file),))


def test_bundle_builds_with_expected_members(app, tmp_path):
    out = tmp_path / 'bundle.zip'
    path = support_bundle_service.build(out_path=str(out))
    assert path == str(out.resolve()) or path == str(out)

    members = _read_all(str(out))
    assert EXPECTED_MEMBERS <= set(members)

    meta = json.loads(members['meta.json'])
    assert meta['panel_version']
    assert meta['python_version']

    dbinfo = json.loads(members['db.json'])
    assert dbinfo['engine'] == 'sqlite'

    counts = json.loads(members['counts.json'])
    for key in ('applications', 'domains', 'servers', 'users', 'jobs'):
        assert isinstance(counts[key], int)


def test_bundle_scrubs_secrets(app, tmp_path, monkeypatch):
    _seed_secrets(tmp_path, monkeypatch)

    out = tmp_path / 'bundle.zip'
    support_bundle_service.build(out_path=str(out))
    members = _read_all(str(out))
    everything = '\n'.join(members.values())

    # Secret setting VALUE must never appear; the key may (shape-only export).
    assert 'supersecretvalue123' not in everything
    # Leaky job error and log lines must be redacted.
    assert 'abc123LEAKYTOKEN' not in everything
    assert 'hunter2' not in everything
    assert 'eyJhbGciOiJIUzI1NiJ9' not in everything
    assert '[REDACTED' in everything

    shapes = json.loads(members['settings_shapes.json'])['settings']
    by_key = {s['key']: s for s in shapes}
    assert by_key['sso_google_client_secret']['value_type'] == 'secret'
    assert by_key['sso_google_client_secret']['is_set'] is True
    assert 'value' not in by_key['canonical_domain']

    jobs = json.loads(members['jobs.json'])['recent_failures']
    assert len(jobs) == 1
    assert 'token' in jobs[0]['error_message']  # key survives
    assert 'abc123LEAKYTOKEN' not in jobs[0]['error_message']


def test_scrub_helper_patterns():
    scrub = support_bundle_service._scrub
    assert 'hunter2' not in scrub('password=hunter2')
    assert 'sk-live-123' not in scrub('"api_key": "sk-live-123"')
    assert 'topsecret' not in scrub("JWT_SECRET_KEY: topsecret")
    assert 'Bearer abcdefgh12345678' not in scrub('Authorization: Bearer abcdefgh12345678')
    # plain text passes through
    assert scrub('nginx reloaded ok') == 'nginx reloaded ok'


def test_passphrase_is_documented_not_silently_ignored(app, tmp_path):
    out = tmp_path / 'bundle.zip'
    support_bundle_service.build(out_path=str(out), passphrase='hunter2')
    members = _read_all(str(out))
    assert 'NOT' in members['README.txt']
    assert 'gpg' in members['README.txt']


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def bundle_app(app):
    """conftest app + the support-bundle blueprint (registered in
    app/__init__.py in the real app; that file is owned by another change)."""
    from app.api.support_bundle import support_bundle_bp
    if 'support_bundle' not in app.blueprints:
        app.register_blueprint(support_bundle_bp, url_prefix='/api/v1/support-bundle')
    return app


def _token_for(role):
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token

    user = User(email=f'{role}@test.local', username=f'bundle-{role}',
                role=role, is_active=True)
    user.set_password('x')
    db.session.add(user)
    db.session.commit()
    return create_access_token(identity=user.id)


def test_api_download_requires_auth(bundle_app):
    client = bundle_app.test_client()
    resp = client.post('/api/v1/support-bundle')
    assert resp.status_code == 401


def test_api_download_rejects_non_admin(bundle_app):
    client = bundle_app.test_client()
    token = _token_for('user')
    resp = client.post('/api/v1/support-bundle',
                       headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 403
    assert resp.get_json()['error']


def test_api_download_returns_zip_for_admin(bundle_app):
    client = bundle_app.test_client()
    token = _token_for('admin')
    resp = client.post('/api/v1/support-bundle',
                       headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    assert resp.mimetype == 'application/zip'
    assert 'serverkit-support-' in resp.headers.get('Content-Disposition', '')

    members = _read_all(resp.data)
    assert EXPECTED_MEMBERS <= set(members)
