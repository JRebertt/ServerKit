"""Site import orchestration — migrate a panel backup archive into ServerKit.

Pipeline: fetch archive → extract (safely) → analyse (format importer) →
run the plan's steps (create app, copy docroot, import databases, recreate
DB users preserving password hashes where the engine allows, install cron
jobs, fix permissions, validate). Runs as jobs on the unified job bus:

  * ``import.analyze`` — fetch + extract + analyse, status → 'analyzed'.
  * ``import.run``     — execute the plan steps; supports ``from_step``
                          retry so a failed step can be re-run without
                          repeating completed ones.

Format knowledge lives in ``app.services.site_importers``; this module owns
every side effect so all formats share the same step implementations.
"""
import ipaddress
import logging
import os
import re
import secrets
import shutil
import socket
import tarfile
from urllib.parse import urlparse

from app import db, paths
from app.models.site_import import SiteImport, VALID_SOURCE_TYPES
from app.services.site_importers import detect_format, get_importer

logger = logging.getLogger(__name__)

ANALYZE_JOB_KIND = 'import.analyze'
RUN_JOB_KIND = 'import.run'

# Hard cap on archive size (upload or URL fetch): 20 GB.
MAX_ARCHIVE_BYTES = 20 * 1024 ** 3
_DOWNLOAD_CHUNK = 1024 * 1024

_SAFE_DB_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_SAFE_DB_USER_RE = re.compile(r'^[A-Za-z0-9_.-]{1,32}$')
_NATIVE_HASH_RE = re.compile(r'^\*[0-9A-Fa-f]{40}$')


class SiteImportError(ValueError):
    """Invalid input or a rejected operation (maps to HTTP 400)."""


class SiteImportService:

    # Overridable in tests; falls back to env then /var/serverkit/imports.
    imports_base = None

    # ── paths ──
    @classmethod
    def base_dir(cls):
        return (cls.imports_base
                or os.environ.get('SERVERKIT_IMPORTS_DIR')
                or os.path.join(paths.SERVERKIT_DIR, 'imports'))

    @classmethod
    def uploads_dir(cls):
        return os.path.join(cls.base_dir(), 'uploads')

    @classmethod
    def workdir(cls, imp):
        return os.path.join(cls.base_dir(), str(imp.id))

    @classmethod
    def extracted_dir(cls, imp):
        return os.path.join(cls.workdir(imp), 'extracted')

    # ── CRUD ──
    @classmethod
    def create(cls, source_type, source, options=None, user_id=None):
        source_type = (source_type or 'cpanel').strip().lower()
        if source_type not in VALID_SOURCE_TYPES:
            raise SiteImportError(
                f'source_type must be one of {VALID_SOURCE_TYPES}')
        source = source or {}
        if source_type == 'ssh':
            # SSH sources carry connection facts (host/user/docroot), not an
            # archive; validate + normalise (keyfile-only, no password field).
            from app.services.site_importers.ssh import parse_ssh_source
            try:
                source = parse_ssh_source(source)
            except ValueError as exc:
                raise SiteImportError(str(exc))
        else:
            if not source.get('upload_path') and not source.get('url'):
                raise SiteImportError(
                    "source must contain 'upload_path' or 'url'")
            if source.get('url'):
                cls._validate_url(source['url'])  # fail fast at creation time
        imp = SiteImport(source_type=source_type, status='created',
                         created_by=user_id)
        imp.set_source(source)
        imp.set_options(options or {})
        imp.append_log(f'Import created (source_type={source_type}).')
        db.session.add(imp)
        db.session.commit()
        return imp

    @classmethod
    def get(cls, import_id):
        return SiteImport.query.get(import_id)

    @classmethod
    def list(cls):
        return SiteImport.query.order_by(SiteImport.created_at.desc(),
                                         SiteImport.id.desc()).all()

    @classmethod
    def delete(cls, imp):
        # Workdir + uploaded archive cleanup, then the row.
        shutil.rmtree(cls.workdir(imp), ignore_errors=True)
        upload_path = imp.get_source().get('upload_path')
        if upload_path:
            try:
                resolved = cls._resolve_upload_path(upload_path)
                if os.path.isfile(resolved):
                    os.remove(resolved)
            except (SiteImportError, OSError):
                pass
        db.session.delete(imp)
        db.session.commit()

    # ── upload handling ──
    @classmethod
    def save_upload(cls, file_storage):
        """Persist an uploaded archive under the uploads dir with a random
        name; returns the relative token the client passes back as
        ``source.upload_path``."""
        original = getattr(file_storage, 'filename', '') or ''
        suffix = '.tar.gz'
        for known in ('.tar.gz', '.tgz', '.tar'):
            if original.lower().endswith(known):
                suffix = known
                break
        token = f'{secrets.token_hex(16)}{suffix}'
        os.makedirs(cls.uploads_dir(), exist_ok=True)
        dest = os.path.join(cls.uploads_dir(), token)
        file_storage.save(dest)
        if os.path.getsize(dest) > MAX_ARCHIVE_BYTES:
            os.remove(dest)
            raise SiteImportError('Archive exceeds the 20 GB size limit')
        return os.path.join('uploads', token).replace('\\', '/')

    @classmethod
    def _resolve_upload_path(cls, upload_path):
        """Resolve a client-provided upload token; rejects traversal."""
        if not upload_path or os.path.isabs(upload_path):
            raise SiteImportError('Invalid upload_path')
        base = os.path.realpath(cls.uploads_dir())
        resolved = os.path.realpath(os.path.join(cls.base_dir(), upload_path))
        if resolved != base and not resolved.startswith(base + os.sep):
            raise SiteImportError('Invalid upload_path')
        return resolved

    # ── URL fetch + SSRF guards ──
    @staticmethod
    def _validate_url(url):
        parsed = urlparse(url or '')
        if parsed.scheme not in ('http', 'https'):
            raise SiteImportError('Only http:// and https:// URLs are allowed')
        host = parsed.hostname
        if not host:
            raise SiteImportError('URL has no host')
        try:
            infos = socket.getaddrinfo(host, parsed.port or
                                       (443 if parsed.scheme == 'https' else 80),
                                       proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise SiteImportError(f'Could not resolve host {host!r}: {exc}')
        for info in infos:
            addr = ipaddress.ip_address(info[4][0])
            if (addr.is_private or addr.is_loopback or addr.is_link_local
                    or addr.is_reserved or addr.is_multicast
                    or addr.is_unspecified):
                raise SiteImportError(
                    f'URL resolves to a disallowed address ({addr})')
        return parsed

    @classmethod
    def fetch_archive(cls, imp):
        """Materialise the source archive into the workdir; returns its path."""
        source = imp.get_source()
        workdir = cls.workdir(imp)
        os.makedirs(workdir, exist_ok=True)

        if source.get('upload_path'):
            archive = cls._resolve_upload_path(source['upload_path'])
            if not os.path.isfile(archive):
                raise SiteImportError('Uploaded archive not found')
            cls._log(imp, f'Using uploaded archive ({os.path.getsize(archive)} bytes).')
            return archive

        url = source.get('url')
        if not url:
            raise SiteImportError('Import has no source archive')
        cls._validate_url(url)
        dest = os.path.join(workdir, 'archive.tar.gz')
        cls._log(imp, f'Downloading archive from {url} ...')
        import requests
        received = 0
        with requests.get(url, stream=True, timeout=60,
                          allow_redirects=False) as resp:
            resp.raise_for_status()
            length = resp.headers.get('Content-Length')
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise SiteImportError('Archive exceeds the 20 GB size limit')
            with open(dest, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                    received += len(chunk)
                    if received > MAX_ARCHIVE_BYTES:
                        raise SiteImportError(
                            'Archive exceeds the 20 GB size limit')
                    fh.write(chunk)
        cls._log(imp, f'Downloaded {received} bytes.')
        return dest

    # ── safe extraction ──
    @staticmethod
    def _safe_members(tar, warnings=None):
        """Yield tar members that are safe to extract; raises on traversal."""
        for member in tar.getmembers():
            name = member.name.replace('\\', '/')
            if name.startswith('/') or os.path.isabs(member.name):
                raise SiteImportError(
                    f'Archive member has an absolute path: {member.name!r}')
            parts = name.split('/')
            if '..' in parts:
                raise SiteImportError(
                    f'Archive member escapes the extraction dir: {member.name!r}')
            if member.issym() or member.islnk():
                if warnings is not None:
                    warnings.append(f'Skipped link member {member.name!r}')
                continue
            if member.isdev():
                continue
            yield member

    @classmethod
    def _extract_tar(cls, archive_path, dest, warnings=None):
        os.makedirs(dest, exist_ok=True)
        with tarfile.open(archive_path, 'r:*') as tar:
            members = list(cls._safe_members(tar, warnings=warnings))
            tar.extractall(dest, members=members)

    @classmethod
    def _extract_nested_homedir(cls, extracted, analysis_warnings):
        """cPanel often ships the home as homedir.tar next to the metadata —
        unpack it so the copy step sees a plain homedir/ directory."""
        for base, _dirs, files in os.walk(extracted):
            if 'homedir.tar' in files and not os.path.isdir(
                    os.path.join(base, 'homedir')):
                cls._extract_tar(os.path.join(base, 'homedir.tar'),
                                 os.path.join(base, 'homedir'),
                                 warnings=analysis_warnings)
                return

    # ── analyse ──
    @classmethod
    def analyze(cls, imp):
        """Fetch + extract + analyse; sets status analyzed/failed."""
        if imp.source_type == 'ssh':
            return cls._analyze_ssh(imp)
        imp.status = 'analyzing'
        imp.error = None
        imp.current_step = 'analyze'
        db.session.commit()
        try:
            archive = cls.fetch_archive(imp)
            extracted = cls.extracted_dir(imp)
            if os.path.isdir(extracted):
                shutil.rmtree(extracted, ignore_errors=True)
            extraction_warnings = []
            cls._log(imp, 'Extracting archive ...')
            cls._extract_tar(archive, extracted, warnings=extraction_warnings)
            cls._extract_nested_homedir(extracted, extraction_warnings)

            if imp.source_type == 'auto':
                fmt, importer = detect_format(extracted)
                if not importer:
                    raise SiteImportError(
                        'Could not detect the backup format — supported '
                        'formats: cpanel')
                imp.source_type = fmt
                cls._log(imp, f'Detected backup format: {fmt}.')
            else:
                importer = get_importer(imp.source_type)
                if not importer:
                    raise SiteImportError(
                        f'No importer registered for {imp.source_type!r}')
                if not importer.detect(extracted):
                    cls._log(imp, f'Warning: archive does not look like a '
                                  f'{imp.source_type} backup — analysing anyway.')

            cls._log(imp, f'Analysing {imp.source_type} backup ...')
            analysis = importer.analyze(extracted)
            analysis.setdefault('warnings', []).extend(extraction_warnings)
            imp.set_analysis(analysis)
            imp.status = 'analyzed'
            imp.current_step = None
            cls._log(imp, 'Analysis complete: '
                          f"{len(analysis.get('domains', []))} domain(s), "
                          f"{len(analysis.get('databases', []))} database(s), "
                          f"{len(analysis.get('db_users', []))} DB user(s), "
                          f"{len(analysis.get('crontab', []))} cron line(s).")
            for warning in analysis.get('warnings', []):
                cls._log(imp, f'Warning: {warning}')
            db.session.commit()
            return analysis
        except Exception as exc:
            db.session.rollback()
            imp.status = 'failed'
            imp.error = str(exc)
            cls._log(imp, f'Analysis failed: {exc}')
            db.session.commit()
            raise

    @classmethod
    def _analyze_ssh(cls, imp):
        """Stage a live site over SSH, then build the analyse report from the
        source + pull result. Credentials never persist: the DB password is
        scrubbed from the durable source once the pull has consumed it, and the
        staging manifest records no secrets (plan 31 #7/#9, Decision 5)."""
        from app.services.site_importers.ssh import GenericSshImporter

        imp.status = 'analyzing'
        imp.error = None
        imp.current_step = 'analyze'
        db.session.commit()
        try:
            source = imp.get_source()
            staging = cls.extracted_dir(imp)
            if os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)
            os.makedirs(staging, exist_ok=True)

            importer = GenericSshImporter()
            cls._log(imp, "Staging site over SSH from "
                          f"{source.get('user')}@{source.get('host')} ...")
            pull = importer.pull(source, staging)

            analysis = GenericSshImporter.analyze_source(source, pull)
            imp.set_analysis(analysis)

            # Scrub the DB password from the durable record now the pull is done.
            scrubbed = {k: v for k, v in source.items() if k != 'db_password'}
            imp.set_source(scrubbed)

            imp.status = 'analyzed'
            imp.current_step = None
            cls._log(imp, 'Analysis complete (SSH source): '
                          f"{len(analysis.get('domains', []))} domain(s), "
                          f"{len(analysis.get('databases', []))} database(s).")
            for warning in analysis.get('warnings', []):
                cls._log(imp, f'Warning: {warning}')
            db.session.commit()
            return analysis
        except Exception as exc:
            db.session.rollback()
            imp.status = 'failed'
            imp.error = str(exc)
            cls._log(imp, f'Analysis failed: {exc}')
            db.session.commit()
            raise

    # ── run ──
    @classmethod
    def run(cls, imp, from_step=None):
        """Execute the migration plan. ``from_step`` re-runs from a specific
        step key, skipping the ones before it (retry support)."""
        analysis = imp.get_analysis()
        if not analysis:
            raise SiteImportError('Import has not been analysed yet')
        importer = get_importer(imp.source_type)
        if not importer:
            raise SiteImportError(
                f'No importer registered for {imp.source_type!r}')
        options = imp.get_options()
        steps = importer.plan(analysis, options)
        step_keys = [s['key'] for s in steps]
        if from_step and from_step not in step_keys:
            raise SiteImportError(
                f'Unknown step {from_step!r}; plan steps: {step_keys}')

        imp.status = 'running'
        imp.error = None
        db.session.commit()

        ctx = {
            'analysis': analysis,
            'options': options,
            'extracted': cls.extracted_dir(imp),
            'result': imp.get_result() or {'warnings': []},
        }
        ctx['result'].setdefault('warnings', [])

        skipping = bool(from_step)
        for step in steps:
            key = step['key']
            if skipping:
                if key == from_step:
                    skipping = False
                else:
                    cls._log(imp, f"Skipping step '{key}' (already completed).")
                    continue
            # Wizard options can opt out of whole pipeline areas.
            if options.get('skip_db') and key in ('create_databases',
                                                  'create_db_users'):
                cls._log(imp, f"Skipping step '{key}' (skip_db option).")
                continue
            if options.get('skip_crontab') and key == 'install_crontab':
                cls._log(imp, f"Skipping step '{key}' (skip_crontab option).")
                continue
            imp.current_step = key
            db.session.commit()
            cls._log(imp, f"Step '{key}': {step['title']} ...")
            handler = getattr(cls, f'_step_{key}', None)
            if handler is None:
                cls._log(imp, f"Warning: no handler for step '{key}' — skipped.")
                ctx['result']['warnings'].append(f'Step {key} has no handler')
                continue
            try:
                handler(imp, ctx)
            except Exception as exc:
                db.session.rollback()
                imp.status = 'failed'
                imp.error = f"Step '{key}' failed: {exc}"
                imp.set_result(ctx['result'])
                cls._log(imp, f"Step '{key}' failed: {exc}")
                cls._log(imp, f"Fix the cause and retry with from_step='{key}'.")
                db.session.commit()
                return imp
            cls._log(imp, f"Step '{key}' done.")
            imp.set_result(ctx['result'])
            db.session.commit()

        imp.status = 'completed'
        imp.current_step = None
        imp.set_result(ctx['result'])
        cls._log(imp, 'Import completed.')
        db.session.commit()
        return imp

    # ── steps ──
    @classmethod
    def _step_create_app(cls, imp, ctx):
        """Create the Application row + on-disk root for the imported site.

        There is no standalone programmatic app-provisioning service (the
        panel's create paths live inside the apps API), so we create the
        Application row directly — same fields as POST /api/v1/apps — and
        flag that the operator finishes container provisioning (deploy) from
        the panel."""
        from app.models import Application, User

        analysis = ctx['analysis']
        options = ctx['options']
        from app.utils.slug import slugify
        primary = (analysis.get('domains') or [{}])[0]
        raw_name = (options.get('app_name') or primary.get('domain')
                    or analysis.get('account_user') or f'imported-{imp.id}')
        name = slugify(raw_name)[:100] or f'imported-{imp.id}'
        # Unfiltered on purpose: a tombstoned app keeps reserving its name and
        # its APPS_DIR/<name> directory until purge, so reusing the name here
        # would collide with the files a restore expects to find.
        if Application.query.filter_by(name=name).first():
            name = f'{name}-{imp.id}'

        app_type = options.get('app_type') or ('php' if analysis.get('php_version')
                                               else 'php')
        root_path = os.path.join(paths.APPS_DIR, name, 'current')
        try:
            os.makedirs(root_path, exist_ok=True)
        except OSError as exc:
            raise SiteImportError(f'Could not create app directory: {exc}')

        user_id = imp.created_by
        if user_id is None:
            admin = User.query.filter_by(role='admin').first()
            if not admin:
                raise SiteImportError('No admin user to own the imported app')
            user_id = admin.id

        application = Application(
            name=name,
            app_type=app_type,
            status='stopped',
            source='manual',
            php_version=analysis.get('php_version'),
            root_path=root_path,
            user_id=user_id,
        )
        db.session.add(application)
        db.session.commit()
        ctx['app'] = application
        ctx['result']['app_id'] = application.id
        ctx['result']['app_name'] = name
        ctx['result']['warnings'].append(
            'Application row created; complete container provisioning '
            '(deploy) from the Services page.')
        cls._log(imp, f"Created application '{name}' (id={application.id}, "
                      f'type={app_type}).')

    @classmethod
    def _get_app(cls, imp, ctx):
        if ctx.get('app') is not None:
            return ctx['app']
        from app.models import Application
        app_id = ctx['result'].get('app_id') or imp.get_result().get('app_id')
        application = (Application.query_active().filter_by(id=app_id).first()
                       if app_id else None)
        if not application:
            raise SiteImportError('Imported application row not found — '
                                  "retry from step 'create_app'")
        ctx['app'] = application
        ctx['result'].setdefault('app_id', application.id)
        return application

    @classmethod
    def _step_copy_files(cls, imp, ctx):
        application = cls._get_app(imp, ctx)
        analysis = ctx['analysis']
        # SSH imports stage the docroot directly (no homedir layout to walk).
        staged = analysis.get('staged_docroot')
        if staged:
            src = os.path.join(ctx['extracted'], staged)
            if not os.path.isdir(src):
                raise SiteImportError(
                    f'Staged docroot not found: {src}')
            shutil.copytree(src, application.root_path, dirs_exist_ok=True)
            copied = sum(len(files) for _b, _d, files
                         in os.walk(application.root_path))
            cls._log(imp, f'Copied staged site files ({copied} file(s) now in '
                          'docroot).')
            return
        if not analysis.get('homedir_present'):
            ctx['result']['warnings'].append(
                'Backup has no homedir — no site files copied.')
            cls._log(imp, 'Warning: no homedir in backup; nothing to copy.')
            return
        root = os.path.join(ctx['extracted'],
                            analysis.get('source_root') or '.')
        homedir = os.path.join(root, 'homedir')
        primary = (analysis.get('domains') or [{}])[0]
        docroot = primary.get('docroot') or ''
        # docroots are absolute inside the old server ('/home/user/public_html');
        # keep only the path under the home directory.
        rel = re.sub(r'^/home[^/]*/[^/]+/?', '', docroot).strip('/')
        src = os.path.join(homedir, rel) if rel else homedir
        if not os.path.isdir(src):
            fallback = os.path.join(homedir, 'public_html')
            if os.path.isdir(fallback):
                src = fallback
            else:
                src = homedir
        if not os.path.isdir(src):
            raise SiteImportError(f'Docroot source not found in backup: {src}')
        shutil.copytree(src, application.root_path, dirs_exist_ok=True)
        copied = sum(len(files) for _b, _d, files in os.walk(application.root_path))
        cls._log(imp, f'Copied site files from {os.path.relpath(src, ctx["extracted"])} '
                      f'({copied} file(s) now in docroot).')

    @classmethod
    def _step_create_databases(cls, imp, ctx):
        from app.services.database_service import DatabaseService
        from app.services.managed_database_service import ManagedDatabaseService

        application = cls._get_app(imp, ctx)
        imported = ctx['result'].setdefault('databases', [])
        for entry in ctx['analysis'].get('databases', []):
            name = entry.get('name') or ''
            if not _SAFE_DB_NAME_RE.match(name):
                ctx['result']['warnings'].append(
                    f'Skipped database with unsafe name {name!r}')
                cls._log(imp, f'Warning: skipped database with unsafe name {name!r}.')
                continue
            if entry.get('engine') != 'mysql':
                ctx['result']['warnings'].append(
                    f"Database {name}: engine {entry.get('engine')!r} not "
                    'supported yet — skipped.')
                continue
            created = DatabaseService.mysql_create_database(name)
            if not created.get('success'):
                raise SiteImportError(
                    f"Could not create database {name}: {created.get('error')}")
            cls._log(imp, f'Created MySQL database {name}.')
            dump = os.path.join(ctx['extracted'], entry.get('dump_path') or '')
            if entry.get('dump_path') and os.path.isfile(dump):
                restored = DatabaseService.mysql_restore(name, dump)
                if not restored.get('success'):
                    raise SiteImportError(
                        f"Import of dump for {name} failed: {restored.get('error')}")
                cls._log(imp, f'Imported dump into {name} '
                              f"({entry.get('size', 0)} bytes).")
            else:
                ctx['result']['warnings'].append(
                    f'Dump file for database {name} not found — created empty.')
                cls._log(imp, f'Warning: dump for {name} missing; created empty.')
            try:
                ManagedDatabaseService.record_provisioned(
                    'mysql', name, owner_application_id=application.id)
            except Exception as exc:  # tracking is additive, never fatal
                logger.warning('Could not record managed DB %s: %s', name, exc)
            if name not in imported:
                imported.append(name)

    # SQL used to recreate a user with its original password hash.
    @staticmethod
    def _preserve_user_sql(username, hash_value, host='localhost'):
        return (f"CREATE USER IF NOT EXISTS '{username}'@'{host}' "
                f"IDENTIFIED WITH mysql_native_password AS '{hash_value}'")

    @classmethod
    def _step_create_db_users(cls, imp, ctx):
        from app.services.database_service import DatabaseService

        imported_dbs = set(ctx['result'].get('databases') or
                           [d['name'] for d in ctx['analysis'].get('databases', [])])
        created_users = ctx['result'].setdefault('db_users', [])
        for entry in ctx['analysis'].get('db_users', []):
            user = entry.get('user') or ''
            if not _SAFE_DB_USER_RE.match(user):
                ctx['result']['warnings'].append(
                    f'Skipped DB user with unsafe name {user!r}')
                cls._log(imp, f'Warning: skipped DB user with unsafe name {user!r}.')
                continue
            hash_value = entry.get('hash') or ''
            preserved = (entry.get('hash_format') == 'mysql_native_password'
                         and _NATIVE_HASH_RE.match(hash_value))
            if preserved:
                result = DatabaseService.mysql_execute(
                    cls._preserve_user_sql(user, hash_value))
                if not result.get('success'):
                    raise SiteImportError(
                        f"Could not create DB user {user}: {result.get('error')}")
                cls._log(imp, f'Recreated DB user {user} with its original '
                              'password hash (mysql_native_password).')
            else:
                password = DatabaseService.generate_password()
                result = DatabaseService.mysql_create_user(user, password)
                if not result.get('success'):
                    raise SiteImportError(
                        f"Could not create DB user {user}: {result.get('error')}")
                ctx['result']['warnings'].append(
                    f'DB user {user}: original password hash could not be '
                    'preserved — a new password was generated; update the '
                    "site's DB credentials.")
                cls._log(imp, f'Created DB user {user} with a NEW password '
                              '(hash format not portable).')
            # Re-grant on the imported databases the user had grants on.
            granted = set()
            for grant in entry.get('grants', []):
                for name in imported_dbs:
                    if name in granted:
                        continue
                    if re.search(r'ON\s+[`\'"]?' + re.escape(name), grant,
                                 re.IGNORECASE):
                        granted.add(name)
            if not granted and imported_dbs and not entry.get('grants'):
                granted = set(imported_dbs)  # no grant info — grant on all imported
            for name in sorted(granted):
                result = DatabaseService.mysql_grant_privileges(user, name)
                if result.get('success'):
                    cls._log(imp, f'Granted ALL on {name} to {user}.')
                else:
                    ctx['result']['warnings'].append(
                        f"Could not grant {user} access to {name}: "
                        f"{result.get('error')}")
            created_users.append({'user': user, 'preserved_hash': bool(preserved)})

    @classmethod
    def _step_install_crontab(cls, imp, ctx):
        try:
            from app.services.cron_service import CronService
        except ImportError:
            ctx['result']['warnings'].append(
                'Cron service unavailable — crontab lines not installed.')
            return
        installed = 0
        for line in ctx['analysis'].get('crontab', []):
            parts = line.split(None, 5)
            if len(parts) < 6:
                ctx['result']['warnings'].append(
                    f'Unparseable cron line skipped: {line!r}')
                continue
            schedule = ' '.join(parts[:5])
            command = parts[5]
            result = CronService.add_job(
                schedule, command, name=f'import-{imp.id}',
                description=f'Imported from {imp.source_type} backup')
            if result.get('success'):
                installed += 1
                cls._log(imp, f'Installed cron job: {schedule} {command}')
            else:
                ctx['result']['warnings'].append(
                    f"Cron line not installed ({result.get('error')}): {line!r}")
                cls._log(imp, f'Warning: cron line rejected: {line!r} '
                              f"({result.get('error')}).")
        ctx['result']['cron_installed'] = installed

    @classmethod
    def _step_fix_permissions(cls, imp, ctx):
        application = cls._get_app(imp, ctx)
        if os.name == 'nt':
            cls._log(imp, 'Skipping permission fix (not a Linux host).')
            return
        root = application.root_path
        fixed = 0
        for base, dirs, files in os.walk(root):
            for d in dirs:
                try:
                    os.chmod(os.path.join(base, d), 0o755)
                    fixed += 1
                except OSError:
                    pass
            for f in files:
                try:
                    os.chmod(os.path.join(base, f), 0o644)
                    fixed += 1
                except OSError:
                    pass
        try:
            shutil.chown(root, user='www-data', group='www-data')
        except (LookupError, PermissionError, OSError):
            ctx['result']['warnings'].append(
                'Could not chown the docroot to www-data (best-effort).')
        cls._log(imp, f'Permissions normalised on {fixed} path(s).')

    @classmethod
    def _step_validate(cls, imp, ctx):
        from app.services.database_service import DatabaseService

        application = cls._get_app(imp, ctx)
        problems = []
        if ctx['analysis'].get('homedir_present'):
            try:
                non_empty = bool(os.listdir(application.root_path))
            except OSError:
                non_empty = False
            if non_empty:
                cls._log(imp, 'Validate: docroot is non-empty.')
            else:
                problems.append('Docroot is empty after copy')
        for name in ctx['result'].get('databases', []):
            result = DatabaseService.mysql_execute(
                'SELECT COUNT(*) FROM information_schema.tables '
                f"WHERE table_schema='{name}'")
            if result.get('success'):
                cls._log(imp, f'Validate: database {name} reachable '
                              f"(tables: {(result.get('output') or '').strip() or '?'}).")
            else:
                ctx['result']['warnings'].append(
                    f'Could not verify database {name}: '
                    f"{result.get('error')} (best-effort check)")
        if problems:
            raise SiteImportError('; '.join(problems))
        ctx['result']['validated'] = True

    # ── logging ──
    @classmethod
    def _log(cls, imp, msg):
        imp.append_log(msg)
        db.session.commit()
        logger.info('[site-import %s] %s', imp.id, msg)

    # ── jobs ──
    @classmethod
    def enqueue_analyze(cls, imp):
        from app.jobs.service import JobService
        return JobService.enqueue(ANALYZE_JOB_KIND,
                                  payload={'import_id': imp.id},
                                  max_attempts=1,
                                  owner_type='site_import', owner_id=imp.id)

    @classmethod
    def enqueue_run(cls, imp, from_step=None):
        from app.jobs.service import JobService
        payload = {'import_id': imp.id}
        if from_step:
            payload['from_step'] = from_step
        return JobService.enqueue(RUN_JOB_KIND, payload=payload,
                                  max_attempts=1,
                                  owner_type='site_import', owner_id=imp.id)

    @classmethod
    def _job_analyze(cls, job):
        payload = job.get_payload() or {}
        imp = SiteImport.query.get(payload.get('import_id'))
        if not imp:
            raise ValueError(f"site import {payload.get('import_id')!r} not found")
        cls.analyze(imp)
        return {'import_id': imp.id, 'status': imp.status}

    @classmethod
    def _job_run(cls, job):
        payload = job.get_payload() or {}
        imp = SiteImport.query.get(payload.get('import_id'))
        if not imp:
            raise ValueError(f"site import {payload.get('import_id')!r} not found")
        cls.run(imp, from_step=payload.get('from_step'))
        return {'import_id': imp.id, 'status': imp.status}

    @classmethod
    def register_jobs(cls):
        """Register the import job kinds on the unified job bus. Called once
        at boot (see app/__init__.py job wiring)."""
        from app.jobs import registry
        registry.register(ANALYZE_JOB_KIND, cls._job_analyze, replace=True)
        registry.register(RUN_JOB_KIND, cls._job_run, replace=True)
