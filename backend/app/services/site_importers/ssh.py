"""Generic SSH site importer — pull a live site off a reachable box over SSH.

Unlike the archive importers (cPanel/DirectAdmin/Hestia) which unpack a backup
tarball, this importer connects to a running server and STAGES the site: it
rsyncs the docroot and (optionally) dumps the site database into the import
run's work directory, then hands the standard pipeline a ready-to-copy
``docroot/`` directory via the analysis' ``staged_docroot`` key.

Security posture (plan 31 Decision 5):

* **Keyfile-only auth.** Authentication is by an SSH *key file on the panel
  host* (``ssh -i``) under ``BatchMode=yes`` — no interactive password, no
  ``sshpass`` dependency. ``parse_ssh_source`` deliberately has NO ``password``
  field.
* **No secrets persist.** The keyfile stays a path reference; the DB password is
  piped to the remote over stdin (never on the argv, never in the env of the
  local process) and is scrubbed from the durable import record after the pull.
  The staging manifest records only non-secret facts.
* **Linux-gated.** The live pull shells out to ``ssh``/``rsync``/``mysqldump``
  and runs on a Linux panel host only; the wizard says so on Windows dev.
"""
import json
import os
import shlex
import subprocess

from app.utils.system import run_checked

from .base import BaseSiteImporter


class SshImportError(ValueError):
    """Invalid SSH source spec or a failed remote step (maps to HTTP 400)."""


def parse_ssh_source(source):
    """Validate + normalise an SSH import source into the durable spec.

    Required: ``host``, ``user``, ``docroot``. Auth is keyfile-only — any
    ``password`` field is dropped (plan 31 #8). DB fields are carried through
    only when present (they drive an optional remote dump). Raises
    :class:`ValueError` when a required field is missing.
    """
    source = source or {}
    host = (source.get('host') or '').strip()
    user = (source.get('user') or source.get('username') or '').strip()
    docroot = (source.get('docroot') or '').strip()

    missing = [name for name, value in
               (('host', host), ('user', user), ('docroot', docroot)) if not value]
    if missing:
        raise SshImportError('SSH source requires: ' + ', '.join(missing))

    try:
        port = int(source.get('port') or 22)
    except (TypeError, ValueError):
        raise SshImportError('SSH port must be a number')

    parsed = {
        'host': host,
        'port': port,
        'user': user,
        'docroot': docroot,
        'domain': (source.get('domain') or '').strip() or host,
        # Keyfile path on the panel host (never the key material itself).
        'ssh_key': (source.get('ssh_key') or source.get('keyfile') or '').strip() or None,
    }
    # Optional DB facts for a remote dump — carried through, never required.
    for key in ('db_name', 'db_user', 'db_password', 'db_host'):
        value = source.get(key)
        if value:
            parsed[key] = value
    return parsed


class GenericSshImporter(BaseSiteImporter):
    """Pull a site off a reachable box over SSH and stage it for the pipeline."""

    format = 'ssh'

    #: Non-secret staging manifest written next to the pulled artifacts.
    MANIFEST_NAME = 'ssh-import-manifest.json'

    # Timeouts (seconds) for the remote steps.
    _CONNECT_TIMEOUT = 15
    _RSYNC_TIMEOUT = 3600
    _DUMP_TIMEOUT = 3600

    # ── the archive-importer interface (this format is never auto-detected) ──
    def detect(self, extracted_dir):
        return False

    def analyze(self, extracted_dir):
        # SSH analysis is built from the source + pull result, not from a
        # extracted archive dir — see ``analyze_source`` / SiteImportService.
        return self._empty_report('ssh')

    # ── SSH options (keyfile-only, batch mode) ──
    @classmethod
    def _ssh_opts(cls, port, ssh_key):
        opts = ['-p', str(port),
                '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=accept-new',
                '-o', f'ConnectTimeout={cls._CONNECT_TIMEOUT}']
        if ssh_key:
            opts += ['-i', ssh_key]
        return opts

    # ── the pull ──
    def pull(self, source, staging_dir):
        """Stage the remote site under ``staging_dir``: rsync the docroot into
        ``docroot/`` and, when DB facts are present, dump the database.

        Returns ``{'staging_dir', 'docroot_dir': 'docroot', 'db_dump': <name|None>}``.
        Linux-only; raises :class:`SshImportError` elsewhere.
        """
        if os.name == 'nt':
            raise SshImportError(
                'SSH site import runs on a Linux panel host only.')

        source = parse_ssh_source(source)
        os.makedirs(staging_dir, exist_ok=True)
        docroot_dst = os.path.join(staging_dir, 'docroot')
        os.makedirs(docroot_dst, exist_ok=True)

        ssh_opts = self._ssh_opts(source['port'], source.get('ssh_key'))
        remote = f"{source['user']}@{source['host']}"

        self._rsync_docroot(remote, source['docroot'], docroot_dst, ssh_opts)

        db_dump = None
        if source.get('db_name'):
            db_dump = 'database.sql'
            self._dump_database(remote, source, ssh_opts,
                                os.path.join(staging_dir, db_dump))

        self._write_manifest(staging_dir, source, db_dump)
        return {'staging_dir': staging_dir, 'docroot_dir': 'docroot',
                'db_dump': db_dump}

    @classmethod
    def _rsync_docroot(cls, remote, docroot, dest, ssh_opts):
        ssh_cmd = 'ssh ' + ' '.join(shlex.quote(o) for o in ssh_opts)
        src = f"{remote}:{docroot.rstrip('/')}/"
        cmd = ['rsync', '-az', '--delete', '-e', ssh_cmd, src, dest + os.sep]
        result = run_checked(cmd, timeout=cls._RSYNC_TIMEOUT, errors='replace')
        if not result['success']:
            raise SshImportError(f"Failed to pull docroot over SSH: {result['error']}")

    @classmethod
    def _dump_database(cls, remote, source, ssh_opts, out_path):
        """Dump the remote database to ``out_path``. The DB password is piped to
        the remote over stdin (``MYSQL_PWD=$(cat)``) so it never appears on the
        command line or in the local process environment."""
        db_user = source.get('db_user') or source['user']
        db_name = source['db_name']
        db_host = source.get('db_host') or 'localhost'
        password = source.get('db_password') or ''
        # Read the password from stdin into MYSQL_PWD, then run mysqldump.
        remote_cmd = (
            'MYSQL_PWD="$(cat)" mysqldump '
            f'-h {shlex.quote(db_host)} -u {shlex.quote(db_user)} '
            f'{shlex.quote(db_name)}')
        cmd = ['ssh'] + ssh_opts + [remote, remote_cmd]
        with open(out_path, 'wb') as fh:
            # text=False: the dump itself is written straight to a binary file
            # handle; only stderr is captured, and it is decoded below.
            proc = run_checked(
                cmd, input=(password + '\n').encode(), stdout=fh,
                stderr=subprocess.PIPE, timeout=cls._DUMP_TIMEOUT, text=False)
        if proc['returncode'] is None:
            raise SshImportError(f"Failed to dump remote database: {proc['error']}")
        if not proc['success']:
            stderr = (proc['stderr'] or b'').decode('utf-8', 'replace').strip()
            raise SshImportError(f'Remote mysqldump failed: {stderr}')

    # ── analysis (built from the source + pull result) ──
    @staticmethod
    def analyze_source(source, pull_result):
        """Build the neutral analyse report from the SSH source + pull result.

        The pipeline copies the staged ``docroot/`` directly (``staged_docroot``)
        instead of walking a homedir layout.
        """
        source = parse_ssh_source(source)
        report = BaseSiteImporter._empty_report('ssh')
        report['homedir_present'] = True
        report['staged_docroot'] = (pull_result or {}).get('docroot_dir', 'docroot')
        report['domains'] = [{
            'domain': source.get('domain') or source.get('host'),
            'docroot': source.get('docroot'),
            'type': 'php',
        }]
        if source.get('db_name'):
            report['databases'] = [{
                'name': source['db_name'],
                'engine': 'mysql',
                'dump_path': (pull_result or {}).get('db_dump'),
                'size': 0,
            }]
            if source.get('db_user'):
                report['db_users'] = [{
                    'user': source['db_user'],
                    'hash': '',
                    'hash_format': None,
                    'grants': [],
                }]
        return report

    # ── manifest (no secrets) ──
    @staticmethod
    def _write_manifest(staging_dir, source, db_dump):
        """Write a staging manifest recording ONLY non-secret facts — never the
        DB password or the key material/path (plan 31 #9)."""
        source = source or {}
        manifest = {
            'source_type': 'ssh',
            'host': source.get('host'),
            'port': source.get('port', 22),
            'user': source.get('user'),
            'docroot': source.get('docroot'),
            'domain': source.get('domain') or source.get('host'),
            'db_name': source.get('db_name'),
            'db_user': source.get('db_user'),
            'db_dump': db_dump,
            'auth': 'keyfile' if source.get('ssh_key') else 'agent',
            # Presence flags only — the secrets themselves never land here.
            'db_password_present': bool(source.get('db_password')),
        }
        os.makedirs(staging_dir, exist_ok=True)
        path = os.path.join(staging_dir, GenericSshImporter.MANIFEST_NAME)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh, indent=2)
        return path

    # ── optional preflight probe (wizard "test connection") ──
    @classmethod
    def probe(cls, source):
        """Preflight: verify the box is reachable and inspect the docroot.

        Returns ``{'reachable': bool, 'files': [...], 'has_wp_config': bool,
        'error': str|None}``. Linux-only; never raises — the wizard renders the
        result. Keyfile-only, BatchMode (so an un-set-up key fails fast rather
        than hanging on a password prompt)."""
        if os.name == 'nt':
            return {'reachable': False,
                    'error': 'SSH import preflight runs on a Linux panel host only.'}
        try:
            source = parse_ssh_source(source)
        except ValueError as exc:
            return {'reachable': False, 'error': str(exc)}

        ssh_opts = cls._ssh_opts(source['port'], source.get('ssh_key'))
        remote = f"{source['user']}@{source['host']}"
        docroot = source['docroot']
        remote_cmd = (
            f'ls -1a {shlex.quote(docroot)} 2>/dev/null | head -50; '
            f'test -f {shlex.quote(docroot.rstrip("/") + "/wp-config.php")} '
            '&& echo __HAS_WP_CONFIG__')
        cmd = ['ssh'] + ssh_opts + [remote, remote_cmd]
        proc = run_checked(cmd, timeout=cls._CONNECT_TIMEOUT + 10, errors='replace')
        if not proc['success']:
            return {'reachable': False,
                    'error': proc['error'] or 'SSH connection failed'}
        lines = proc['output'].splitlines()
        has_wp = '__HAS_WP_CONFIG__' in lines
        files = [ln for ln in lines
                 if ln and ln != '__HAS_WP_CONFIG__' and ln not in ('.', '..')]
        return {'reachable': True, 'files': files, 'has_wp_config': has_wp,
                'error': None}
