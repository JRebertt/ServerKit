"""Tests for the site import pipeline (cPanel archive importer).

Covers: the analyse report produced from a synthetic cPanel full backup,
tar path-traversal guards, SSRF guards on fetch-by-URL, upload-path
traversal, the plan step list, step execution with retry-from-step, MySQL
password-hash preservation, and the /api/v1/imports HTTP contract.
"""
import io
import json
import os
import tarfile
from types import SimpleNamespace

import pytest

from app.models.site_import import SiteImport
from app.services.site_import_service import (
    SiteImportError,
    SiteImportService,
)
from app.services.site_importers import (
    available_formats,
    detect_format,
    get_importer,
)
from app.services.site_importers.cpanel import CpanelImporter

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app

NATIVE_HASH = '*94BDCEBE19083CE2A1F959FD02F964C7AF4CFC29'
BACKUP_NAME = 'backup-7.3.2026_12-00-00_alice'


# --------------------------------------------------------------------------
# helpers / fixtures
# --------------------------------------------------------------------------

def _build_backup_tree(root, homedir_as_tar=False):
    """Create a synthetic cPanel full-backup content tree under ``root``."""
    def write(rel, content):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(content)

    write('homedir/public_html/index.php', "<?php echo 'imported'; ?>")
    write('homedir/public_html/wp-config.php', "<?php // config")
    write('homedir/etc/example.com/passwd', 'info:x:100\nsales:x:101\n')
    write('mysql/alice_wp.sql', 'CREATE TABLE wp_posts (id INT);\n')
    write('mysql.sql',
          "GRANT USAGE ON *.* TO 'alice_wp'@'localhost' "
          f"IDENTIFIED BY PASSWORD '{NATIVE_HASH}';\n"
          "GRANT ALL PRIVILEGES ON `alice_wp`.* TO 'alice_wp'@'localhost';\n")
    write('cp/alice', 'DNS=example.com\nPLAN=default\n')
    write('userdata/main', 'main_domain: example.com\n')
    write('userdata/example.com',
          'documentroot: /home/alice/public_html\nphpversion: ea-php81\n')
    write('cron/alice',
          'SHELL=/bin/bash\n'
          '# a comment\n'
          '*/5 * * * * /usr/bin/php /home/alice/cron.php\n')
    write('dnszones/example.com.db', '; zone data\n')

    if homedir_as_tar:
        homedir = os.path.join(root, 'homedir')
        with tarfile.open(os.path.join(root, 'homedir.tar'), 'w') as tar:
            for entry in os.listdir(homedir):
                tar.add(os.path.join(homedir, entry), arcname=entry)
        import shutil
        shutil.rmtree(homedir)


def make_backup_archive(tmp_path, homedir_as_tar=False):
    src = os.path.join(str(tmp_path), 'src', BACKUP_NAME)
    os.makedirs(src, exist_ok=True)
    _build_backup_tree(src, homedir_as_tar=homedir_as_tar)
    archive = os.path.join(str(tmp_path), 'backup.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(src, arcname=BACKUP_NAME)
    return archive


@pytest.fixture(autouse=True)
def imports_base(tmp_path):
    """Point the import service at an isolated temp base dir."""
    SiteImportService.imports_base = os.path.join(str(tmp_path), 'imports')
    os.makedirs(SiteImportService.uploads_dir(), exist_ok=True)
    yield SiteImportService.imports_base
    SiteImportService.imports_base = None


def _stage_upload(tmp_path, archive=None, token='staged.tar.gz'):
    """Copy an archive into the uploads dir; returns the upload_path token."""
    import shutil
    archive = archive or make_backup_archive(tmp_path)
    dest = os.path.join(SiteImportService.uploads_dir(), token)
    shutil.copyfile(archive, dest)
    return f'uploads/{token}'


def _make_import(app, tmp_path, **kwargs):
    upload_path = kwargs.pop('upload_path', None) or _stage_upload(tmp_path)
    return SiteImportService.create(
        kwargs.pop('source_type', 'cpanel'),
        {'upload_path': upload_path},
        options=kwargs.pop('options', {}),
        user_id=kwargs.pop('user_id', None),
    )


class FakeDb:
    """Records DatabaseService calls; every call succeeds."""

    def __init__(self):
        self.calls = []
        self.fail_restore = False

    def install(self, monkeypatch):
        from app.services.database_service import DatabaseService

        def record(name):
            def _fn(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                if name == 'mysql_restore' and self.fail_restore:
                    return {'success': False, 'error': 'boom'}
                return {'success': True, 'output': '3'}
            return _fn

        for name in ('mysql_create_database', 'mysql_restore',
                     'mysql_execute', 'mysql_create_user',
                     'mysql_grant_privileges'):
            monkeypatch.setattr(DatabaseService, name, record(name))
        monkeypatch.setattr(DatabaseService, 'generate_password',
                            lambda *a, **k: 'newpass123')
        return self

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def fake_db(monkeypatch):
    return FakeDb().install(monkeypatch)


@pytest.fixture
def fake_cron(monkeypatch):
    calls = []
    from app.services.cron_service import CronService

    def fake_add_job(schedule, command, name=None, description=None):
        calls.append({'schedule': schedule, 'command': command, 'name': name})
        return {'success': True, 'job_id': 'job_x'}

    monkeypatch.setattr(CronService, 'add_job', fake_add_job)
    return calls


@pytest.fixture
def apps_dir(tmp_path, monkeypatch):
    apps = os.path.join(str(tmp_path), 'apps')
    monkeypatch.setattr('app.paths.APPS_DIR', apps)
    return apps


# --------------------------------------------------------------------------
# importer registry + detection
# --------------------------------------------------------------------------

def test_registry_has_cpanel_and_returns_instances():
    assert 'cpanel' in available_formats()
    importer = get_importer('cpanel')
    assert isinstance(importer, CpanelImporter)
    assert get_importer('nope') is None


def test_detect_format_on_extracted_backup(app, tmp_path):
    extracted = os.path.join(str(tmp_path), 'extracted', BACKUP_NAME)
    os.makedirs(extracted)
    _build_backup_tree(extracted)
    fmt, importer = detect_format(os.path.dirname(extracted))
    assert fmt == 'cpanel'
    assert importer.detect(os.path.dirname(extracted)) is True
    # A foreign layout does not detect.
    other = os.path.join(str(tmp_path), 'other')
    os.makedirs(os.path.join(other, 'random-stuff'))
    assert detect_format(other) == (None, None)


# --------------------------------------------------------------------------
# analyse
# --------------------------------------------------------------------------

def test_analyze_report_shape_and_contents(app, tmp_path):
    imp = _make_import(app, tmp_path)
    report = SiteImportService.analyze(imp)

    assert imp.status == 'analyzed'
    assert imp.error is None

    # Shape: every contract key present.
    for key in ('format', 'homedir_present', 'domains', 'databases',
                'db_users', 'crontab', 'mail_accounts_count', 'php_version',
                'warnings', 'unsupported'):
        assert key in report, f'missing report key {key}'

    assert report['format'] == 'cpanel'
    assert report['homedir_present'] is True
    assert report['php_version'] == '8.1'

    assert report['domains'] == [{
        'domain': 'example.com',
        'docroot': '/home/alice/public_html',
        'type': 'primary',
    }]

    assert len(report['databases']) == 1
    database = report['databases'][0]
    assert database['name'] == 'alice_wp'
    assert database['engine'] == 'mysql'
    assert database['dump_path'].endswith('mysql/alice_wp.sql')
    assert database['size'] > 0

    assert len(report['db_users']) == 1
    db_user = report['db_users'][0]
    assert db_user['user'] == 'alice_wp'
    assert db_user['hash'] == NATIVE_HASH
    assert db_user['hash_format'] == 'mysql_native_password'
    assert any('ALL PRIVILEGES' in g for g in db_user['grants'])
    # Password material never leaks into the grants list.
    assert all(NATIVE_HASH not in g for g in db_user['grants'])

    # Env lines and comments filtered out of the crontab.
    assert report['crontab'] == ['*/5 * * * * /usr/bin/php /home/alice/cron.php']

    assert report['mail_accounts_count'] == 2
    unsupported = ' '.join(report['unsupported'])
    assert 'mail account' in unsupported
    assert 'DNS zone' in unsupported

    # Analysis persisted on the row + logged.
    assert imp.get_analysis()['format'] == 'cpanel'
    assert 'Analysis complete' in imp.log_text


def test_analyze_handles_nested_homedir_tar(app, tmp_path):
    archive = make_backup_archive(tmp_path, homedir_as_tar=True)
    token = _stage_upload(tmp_path, archive=archive, token='nested.tar.gz')
    imp = _make_import(app, tmp_path, upload_path=token)
    report = SiteImportService.analyze(imp)
    assert report['homedir_present'] is True
    assert os.path.isfile(os.path.join(
        SiteImportService.extracted_dir(imp), BACKUP_NAME,
        'homedir', 'public_html', 'index.php'))


def test_analyze_partial_backup_warns_not_crashes(app, tmp_path):
    """A backup missing mysql/, cron/ and userdata/ still analyses."""
    src = os.path.join(str(tmp_path), 'partial', BACKUP_NAME)
    os.makedirs(os.path.join(src, 'cp'))
    with open(os.path.join(src, 'cp', 'alice'), 'w') as fh:
        fh.write('DNS=example.com\n')
    archive = os.path.join(str(tmp_path), 'partial.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(src, arcname=BACKUP_NAME)
    token = _stage_upload(tmp_path, archive=archive, token='partial.tar.gz')
    imp = _make_import(app, tmp_path, upload_path=token)
    report = SiteImportService.analyze(imp)
    assert imp.status == 'analyzed'
    assert report['homedir_present'] is False
    assert report['databases'] == []
    assert report['warnings']  # missing pieces surfaced as warnings


def test_auto_source_type_detects_cpanel(app, tmp_path):
    imp = _make_import(app, tmp_path, source_type='auto')
    SiteImportService.analyze(imp)
    assert imp.source_type == 'cpanel'
    assert imp.status == 'analyzed'


# --------------------------------------------------------------------------
# extraction safety
# --------------------------------------------------------------------------

def _evil_archive(tmp_path, member_name):
    archive = os.path.join(str(tmp_path), 'evil.tar.gz')
    payload = b'owned'
    with tarfile.open(archive, 'w:gz') as tar:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return archive


def test_tar_traversal_member_rejected(app, tmp_path):
    archive = _evil_archive(tmp_path, '../../evil.txt')
    token = _stage_upload(tmp_path, archive=archive, token='evil.tar.gz')
    imp = _make_import(app, tmp_path, upload_path=token)
    with pytest.raises(SiteImportError, match='escapes'):
        SiteImportService.analyze(imp)
    assert imp.status == 'failed'
    assert 'escapes' in imp.error
    assert not os.path.exists(os.path.join(str(tmp_path), 'evil.txt'))


def test_tar_absolute_member_rejected(tmp_path):
    archive = _evil_archive(tmp_path, '/etc/evil.txt')
    with pytest.raises(SiteImportError, match='absolute'):
        SiteImportService._extract_tar(archive,
                                       os.path.join(str(tmp_path), 'out'))


def test_tar_symlink_member_skipped_with_warning(tmp_path):
    archive = os.path.join(str(tmp_path), 'link.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        info = tarfile.TarInfo('innocent.txt')
        info.size = 2
        tar.addfile(info, io.BytesIO(b'ok'))
        link = tarfile.TarInfo('escape')
        link.type = tarfile.SYMTYPE
        link.linkname = '/etc/passwd'
        tar.addfile(link)
    warnings = []
    dest = os.path.join(str(tmp_path), 'out')
    SiteImportService._extract_tar(archive, dest, warnings=warnings)
    assert os.path.isfile(os.path.join(dest, 'innocent.txt'))
    assert not os.path.lexists(os.path.join(dest, 'escape'))
    assert any('escape' in w for w in warnings)


# --------------------------------------------------------------------------
# SSRF + upload-path guards
# --------------------------------------------------------------------------

@pytest.mark.parametrize('url', [
    'http://169.254.169.254/latest/meta-data/',   # cloud metadata
    'http://10.0.0.5/backup.tar.gz',              # private
    'http://192.168.1.10/backup.tar.gz',          # private
    'http://127.0.0.1/backup.tar.gz',             # loopback
    'http://0.0.0.0/backup.tar.gz',               # unspecified
    'file:///etc/passwd',                         # bad scheme
    'ftp://example.com/backup.tar.gz',            # bad scheme
    'http:///backup.tar.gz',                      # no host
])
def test_ssrf_guard_rejects(url):
    with pytest.raises(SiteImportError):
        SiteImportService._validate_url(url)


def test_ssrf_guard_allows_public_address():
    # Literal public IP: resolvable without network access.
    assert SiteImportService._validate_url('https://8.8.8.8/backup.tar.gz')


def test_create_rejects_ssrf_url(app):
    with pytest.raises(SiteImportError):
        SiteImportService.create('cpanel',
                                 {'url': 'http://169.254.169.254/x.tar.gz'})


@pytest.mark.parametrize('token', [
    '../outside.tar.gz',
    'uploads/../../outside.tar.gz',
    '',
])
def test_upload_path_traversal_rejected(token):
    with pytest.raises(SiteImportError):
        SiteImportService._resolve_upload_path(token)


def test_upload_path_absolute_rejected(tmp_path):
    outside = os.path.join(str(tmp_path), 'outside.tar.gz')
    with open(outside, 'wb') as fh:
        fh.write(b'x')
    with pytest.raises(SiteImportError):
        SiteImportService._resolve_upload_path(outside)


def test_fetch_archive_rejects_traversal_source(app, tmp_path):
    imp = SiteImport(source_type='cpanel', status='created')
    imp.set_source({'upload_path': '../../etc/passwd'})
    from app import db
    db.session.add(imp)
    db.session.commit()
    with pytest.raises(SiteImportError):
        SiteImportService.fetch_archive(imp)


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def test_plan_full_step_list(app, tmp_path):
    imp = _make_import(app, tmp_path)
    analysis = SiteImportService.analyze(imp)
    steps = get_importer('cpanel').plan(analysis, {})
    assert [s['key'] for s in steps] == [
        'create_app', 'copy_files', 'create_databases', 'create_db_users',
        'install_crontab', 'fix_permissions', 'validate',
    ]
    assert all(s.get('title') for s in steps)


def test_plan_skips_stepless_inputs():
    importer = get_importer('cpanel')
    empty = CpanelImporter._empty_report('cpanel')
    keys = [s['key'] for s in importer.plan(empty, {})]
    assert 'create_databases' not in keys
    assert 'create_db_users' not in keys
    assert 'install_crontab' not in keys
    assert keys[0] == 'create_app' and keys[-1] == 'validate'


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def _admin_user(app):
    from app import db
    from app.models import User
    from werkzeug.security import generate_password_hash
    user = User(email='imp@test.local', username='impadmin',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.commit()
    return user


def test_run_executes_all_steps(app, tmp_path, fake_db, fake_cron, apps_dir):
    from app.models import Application
    user = _admin_user(app)
    imp = _make_import(app, tmp_path, user_id=user.id)
    SiteImportService.analyze(imp)
    SiteImportService.run(imp)

    assert imp.status == 'completed'
    assert imp.current_step is None
    assert imp.error is None

    result = imp.get_result()
    application = Application.query.get(result['app_id'])
    assert application is not None
    assert application.app_type == 'php'
    assert application.php_version == '8.1'
    assert application.name == 'example-com'
    assert os.path.isfile(os.path.join(application.root_path, 'index.php'))

    # Databases created + dump imported + tracked.
    assert [c[1][0] for c in fake_db.named('mysql_create_database')] == ['alice_wp']
    assert fake_db.named('mysql_restore')[0][1][0] == 'alice_wp'
    from app.models.managed_database import ManagedDatabase
    managed = ManagedDatabase.query.filter_by(name='alice_wp').first()
    assert managed is not None and managed.owner_application_id == application.id

    # Hash-preserving CREATE USER went through mysql_execute.
    executed = ' ;; '.join(c[1][0] for c in fake_db.named('mysql_execute'))
    assert ("IDENTIFIED WITH mysql_native_password AS "
            f"'{NATIVE_HASH}'") in executed
    assert 'alice_wp' in executed
    # Grants re-applied on the imported database.
    assert fake_db.named('mysql_grant_privileges')[0][1][:2] == ('alice_wp', 'alice_wp')

    # Crontab installed through the cron service.
    assert fake_cron == [{'schedule': '*/5 * * * *',
                          'command': '/usr/bin/php /home/alice/cron.php',
                          'name': f'import-{imp.id}'}]
    assert result['cron_installed'] == 1
    assert result['validated'] is True
    assert result['db_users'] == [{'user': 'alice_wp', 'preserved_hash': True}]

    # Per-step log lines.
    for key in ('create_app', 'copy_files', 'create_databases',
                'create_db_users', 'install_crontab', 'fix_permissions',
                'validate'):
        assert f"Step '{key}'" in imp.log_text
        assert f"Step '{key}' done." in imp.log_text
    assert 'Import completed.' in imp.log_text


def test_run_failure_marks_failed_and_retry_skips_earlier_steps(
        app, tmp_path, fake_db, fake_cron, apps_dir):
    from app.models import Application
    user = _admin_user(app)
    imp = _make_import(app, tmp_path, user_id=user.id)
    SiteImportService.analyze(imp)

    fake_db.fail_restore = True
    SiteImportService.run(imp)
    assert imp.status == 'failed'
    assert imp.current_step == 'create_databases'
    assert "Step 'create_databases' failed" in imp.error
    assert "retry with from_step='create_databases'" in imp.log_text
    # Earlier steps completed: app row exists, files copied.
    assert Application.query.count() == 1
    app_id = imp.get_result()['app_id']

    # Retry from the failed step: earlier steps are skipped, run completes.
    fake_db.fail_restore = False
    SiteImportService.run(imp, from_step='create_databases')
    assert imp.status == 'completed'
    assert "Skipping step 'create_app' (already completed)." in imp.log_text
    assert "Skipping step 'copy_files' (already completed)." in imp.log_text
    assert Application.query.count() == 1  # no duplicate app
    assert imp.get_result()['app_id'] == app_id


def test_run_honors_skip_db_and_skip_crontab(app, tmp_path, fake_db,
                                             fake_cron, apps_dir):
    imp = _make_import(app, tmp_path, user_id=_admin_user(app).id,
                       options={'skip_db': True, 'skip_crontab': True})
    SiteImportService.analyze(imp)
    SiteImportService.run(imp)

    assert imp.status == 'completed'
    # DB + cron paths never touched.
    assert fake_db.named('mysql_create_database') == []
    assert fake_db.named('mysql_create_user') == []
    assert fake_cron == []
    assert "Skipping step 'create_databases' (skip_db option)." in imp.log_text
    assert "Skipping step 'create_db_users' (skip_db option)." in imp.log_text
    assert ("Skipping step 'install_crontab' (skip_crontab option)."
            in imp.log_text)
    # The other steps still ran.
    assert "Step 'copy_files' done." in imp.log_text
    assert 'databases' not in imp.get_result() or \
        imp.get_result().get('databases') in (None, [])


def test_run_requires_analysis(app, tmp_path):
    imp = _make_import(app, tmp_path)
    with pytest.raises(SiteImportError, match='analysed'):
        SiteImportService.run(imp)


def test_run_rejects_unknown_from_step(app, tmp_path, fake_db, fake_cron,
                                       apps_dir):
    imp = _make_import(app, tmp_path, user_id=_admin_user(app).id)
    SiteImportService.analyze(imp)
    with pytest.raises(SiteImportError, match='Unknown step'):
        SiteImportService.run(imp, from_step='does_not_exist')


def test_preserve_user_sql_shape():
    sql = SiteImportService._preserve_user_sql('alice_wp', NATIVE_HASH)
    assert sql == ("CREATE USER IF NOT EXISTS 'alice_wp'@'localhost' "
                   "IDENTIFIED WITH mysql_native_password AS "
                   f"'{NATIVE_HASH}'")


def test_non_native_hash_falls_back_to_new_password(app, tmp_path, fake_db,
                                                    fake_cron, apps_dir):
    imp = _make_import(app, tmp_path, user_id=_admin_user(app).id)
    SiteImportService.analyze(imp)
    analysis = imp.get_analysis()
    analysis['db_users'] = [{'user': 'alice_wp', 'hash': '$A$005$opaque',
                             'hash_format': 'caching_sha2_password',
                             'grants': []}]
    imp.set_analysis(analysis)
    from app import db
    db.session.commit()

    SiteImportService.run(imp)
    assert imp.status == 'completed'
    assert fake_db.named('mysql_create_user')[0][1][0] == 'alice_wp'
    warnings = ' '.join(imp.get_result()['warnings'])
    assert 'new password was generated' in warnings
    assert imp.get_result()['db_users'] == [
        {'user': 'alice_wp', 'preserved_hash': False}]


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

def test_register_jobs_registers_both_kinds(app):
    from app.jobs import registry
    SiteImportService.register_jobs()
    assert registry.is_registered('import.analyze')
    assert registry.is_registered('import.run')


def test_job_handlers_resolve_import_row(app, tmp_path, fake_db, fake_cron,
                                         apps_dir):
    imp = _make_import(app, tmp_path, user_id=_admin_user(app).id)
    job = SimpleNamespace(get_payload=lambda: {'import_id': imp.id})
    result = SiteImportService._job_analyze(job)
    assert result == {'import_id': imp.id, 'status': 'analyzed'}
    result = SiteImportService._job_run(job)
    assert result == {'import_id': imp.id, 'status': 'completed'}
    missing = SimpleNamespace(get_payload=lambda: {'import_id': 999999})
    with pytest.raises(ValueError):
        SiteImportService._job_analyze(missing)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@pytest.fixture
def api_app(app):
    from app.api.site_imports import site_imports_bp
    if 'site_imports' not in app.blueprints:
        app.register_blueprint(site_imports_bp, url_prefix='/api/v1/imports')
    return app


@pytest.fixture
def api_client(api_app):
    return api_app.test_client()


@pytest.fixture
def viewer_headers(api_app):
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash
    user = User(email='viewer@test.local', username='viewer',
                password_hash=generate_password_hash('x'),
                role='viewer', is_active=True)
    db.session.add(user)
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


@pytest.fixture
def stub_enqueue(monkeypatch):
    calls = []

    def fake_enqueue(cls, kind, payload=None, **kwargs):
        calls.append({'kind': kind, 'payload': payload})
        return SimpleNamespace(id=4242)

    from app.jobs.service import JobService
    monkeypatch.setattr(JobService, 'enqueue', classmethod(fake_enqueue))
    return calls


def test_api_requires_auth(api_client):
    assert api_client.get('/api/v1/imports').status_code == 401
    assert api_client.post('/api/v1/imports', json={}).status_code == 401
    assert api_client.post('/api/v1/imports/upload').status_code == 401


def test_api_requires_admin(api_client, viewer_headers):
    resp = api_client.get('/api/v1/imports', headers=viewer_headers)
    assert resp.status_code == 403
    assert 'error' in resp.get_json()
    resp = api_client.post('/api/v1/imports', headers=viewer_headers, json={})
    assert resp.status_code == 403


def test_api_upload_create_get_list_delete(api_client, auth_headers,
                                            tmp_path, stub_enqueue):
    # Upload
    archive = make_backup_archive(tmp_path)
    with open(archive, 'rb') as fh:
        resp = api_client.post(
            '/api/v1/imports/upload', headers=auth_headers,
            data={'file': (io.BytesIO(fh.read()), 'backup.tar.gz')},
            content_type='multipart/form-data')
    assert resp.status_code == 201
    upload_path = resp.get_json()['upload_path']
    assert upload_path.startswith('uploads/')
    assert not os.path.isabs(upload_path)

    # Create
    resp = api_client.post('/api/v1/imports', headers=auth_headers, json={
        'source_type': 'cpanel',
        'source': {'upload_path': upload_path},
        'options': {'app_name': 'my-imported-site'},
    })
    assert resp.status_code == 201
    body = resp.get_json()['import']
    assert body['status'] == 'created'
    assert body['source_type'] == 'cpanel'
    assert body['options'] == {'app_name': 'my-imported-site'}
    import_id = body['id']

    # List (newest first)
    resp = api_client.get('/api/v1/imports', headers=auth_headers)
    assert resp.status_code == 200
    imports = resp.get_json()['imports']
    assert imports[0]['id'] == import_id

    # Detail
    resp = api_client.get(f'/api/v1/imports/{import_id}', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['import']['id'] == import_id
    assert 'log_text' in resp.get_json()['import']

    # Analyze → 202 with job id
    resp = api_client.post(f'/api/v1/imports/{import_id}/analyze',
                           headers=auth_headers)
    assert resp.status_code == 202
    assert resp.get_json() == {'job_id': 4242}
    assert stub_enqueue[-1]['kind'] == 'import.analyze'
    assert stub_enqueue[-1]['payload'] == {'import_id': import_id}

    # Run refused before analysis
    resp = api_client.post(f'/api/v1/imports/{import_id}/run',
                           headers=auth_headers, json={})
    assert resp.status_code == 409
    assert 'error' in resp.get_json()

    # Mark analyzed → run accepted, from_step forwarded
    imp = SiteImport.query.get(import_id)
    imp.status = 'analyzed'
    from app import db
    db.session.commit()
    resp = api_client.post(f'/api/v1/imports/{import_id}/run',
                           headers=auth_headers,
                           json={'from_step': 'create_databases'})
    assert resp.status_code == 202
    assert resp.get_json() == {'job_id': 4242}
    assert stub_enqueue[-1]['kind'] == 'import.run'
    assert stub_enqueue[-1]['payload'] == {'import_id': import_id,
                                           'from_step': 'create_databases'}

    # Body options merge into the stored options (body wins).
    resp = api_client.post(f'/api/v1/imports/{import_id}/run',
                           headers=auth_headers,
                           json={'options': {'skip_db': True,
                                             'app_name': 'renamed-site'}})
    assert resp.status_code == 202
    imp = SiteImport.query.get(import_id)
    assert imp.get_options() == {'app_name': 'renamed-site', 'skip_db': True}

    # Delete cleans up
    resp = api_client.delete(f'/api/v1/imports/{import_id}',
                             headers=auth_headers)
    assert resp.status_code == 200
    assert SiteImport.query.get(import_id) is None
    resp = api_client.get(f'/api/v1/imports/{import_id}', headers=auth_headers)
    assert resp.status_code == 404


def test_api_create_validation_errors(api_client, auth_headers):
    resp = api_client.post('/api/v1/imports', headers=auth_headers, json={
        'source_type': 'cpanel', 'source': {},
    })
    assert resp.status_code == 400
    assert 'error' in resp.get_json()

    resp = api_client.post('/api/v1/imports', headers=auth_headers, json={
        'source_type': 'unknown-panel', 'source': {'upload_path': 'uploads/x'},
    })
    assert resp.status_code == 400

    resp = api_client.post('/api/v1/imports', headers=auth_headers, json={
        'source_type': 'cpanel',
        'source': {'url': 'http://169.254.169.254/backup.tar.gz'},
    })
    assert resp.status_code == 400


def test_api_upload_requires_file(api_client, auth_headers):
    resp = api_client.post('/api/v1/imports/upload', headers=auth_headers,
                           data={}, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json() == {'error': 'No file provided'}


def test_model_to_dict_and_log_tail(app):
    imp = SiteImport(source_type='cpanel', status='created')
    imp.set_source({'upload_path': 'uploads/x.tar.gz'})
    for i in range(600):
        imp.append_log(f'line {i}')
    from app import db
    db.session.add(imp)
    db.session.commit()
    data = imp.to_dict(log_lines=500)
    lines = data['log_text'].splitlines()
    assert len(lines) == 500
    assert 'line 599' in lines[-1]
    assert data['source'] == {'upload_path': 'uploads/x.tar.gz'}
    assert data['status'] == 'created'
    assert json.dumps(data)  # JSON-serializable throughout
