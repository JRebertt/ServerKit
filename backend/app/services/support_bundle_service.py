"""Diagnostic support bundle: gather panel state into a shareable zip.

Everything collected here is meant to leave the box (attached to a bug report),
so the collectors are shape-over-content by design:

* settings are exported as **keys + declared types only** — never values; keys
  in ``SettingsService.SECRET_KEYS`` are additionally flagged as secrets.
* every piece of free text (logs, job errors, doctor details) passes through
  ``_scrub()`` which redacts anything that looks like a token / password /
  secret / key assignment or a bearer header.

Encryption: ``pyzipper`` is NOT in requirements.txt and we deliberately add no
new dependency, so bundles are plain ``zipfile`` zips. When a passphrase is
requested we record the limitation in the bundle README and advise encrypting
with the operator's own tooling (e.g. ``gpg -c serverkit-support-*.zip``).
"""
import json
import logging
import os
import platform
import re
import sys
import tempfile
import zipfile
from datetime import datetime

logger = logging.getLogger(__name__)

LOG_TAIL_LINES = 200
RECENT_JOB_FAILURES = 20

# Candidate panel log files, best-effort — the systemd deployment logs to the
# journal (no file), so absence is normal.
LOG_FILE_CANDIDATES = (
    os.environ.get('SERVERKIT_LOG_FILE') or '',
    '/var/log/serverkit/serverkit.log',
    '/var/log/serverkit.log',
)

# key = value / "key": "value" pairs whose key smells secret-ish.
_SECRETY_KEY = r'[\w.-]*(?:token|secret|passw(?:or)?d|api[_-]?key|private[_-]?key|access[_-]?key|credential|authorization)[\w.-]*'
_ASSIGNMENT_RE = re.compile(
    r'(?i)(["\']?' + _SECRETY_KEY + r'["\']?\s*[:=]\s*)(["\']?)([^\s"\',;}]+)'
)
_BEARER_RE = re.compile(r'(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}')
# Standalone JWTs (three dot-separated base64url segments).
_JWT_RE = re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b')


def _scrub(text):
    """Redact secret-looking material from free text. Idempotent."""
    if not text:
        return text
    if not isinstance(text, str):
        text = str(text)
    # Order matters: catch "Bearer <token>" / bare JWTs before the assignment
    # pattern, so "Authorization: Bearer x" never leaves the raw token behind.
    text = _JWT_RE.sub('[REDACTED-JWT]', text)
    text = _BEARER_RE.sub(lambda m: f'{m.group(1)} [REDACTED]', text)
    text = _ASSIGNMENT_RE.sub(lambda m: f'{m.group(1)}{m.group(2)}[REDACTED]', text)
    return text


def _safe(section_name, fn, default=None):
    """Run a collector; a broken collector must never sink the whole bundle."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - diagnostics are best-effort
        logger.warning(f'support bundle: {section_name} collector failed: {exc}')
        return {'error': f'collector failed: {exc.__class__.__name__}'} if default is None else default


def _collect_meta():
    from app.utils.version import get_panel_version, get_install_dir
    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'panel_version': get_panel_version(),
        'install_dir': get_install_dir(),
        'python_version': sys.version,
        'platform': platform.platform(),
        'os_name': os.name,
    }


def _collect_db():
    from app import db
    info = {'engine': db.engine.url.get_backend_name()}
    try:
        from app.services.migration_service import MigrationService
        status = MigrationService.get_status()
        info['migration_current'] = status.get('current_revision')
        info['migration_head'] = status.get('head_revision')
        info['migration_pending'] = status.get('pending_count')
    except Exception as exc:  # noqa: BLE001
        info['migration_error'] = exc.__class__.__name__
    return info


def _collect_counts():
    from app.models import Application, Domain, Server, User
    from app.jobs.models import Job
    return {
        'applications': Application.query.count(),
        'domains': Domain.query_active().count(),
        'servers': Server.query.count(),
        'users': User.query.count(),
        'jobs': Job.query.count(),
    }


def _collect_services():
    if os.name == 'nt':
        return {'skipped': 'service states are Linux-only'}
    from app.services.process_service import ProcessService
    return {'services': ProcessService.get_services_status()}


def _collect_settings_shapes():
    """Setting keys + declared types ONLY. Values are never exported; secret
    keys are only reported as set/empty."""
    from app.models import SystemSettings
    from app.services.settings_service import SettingsService

    shapes = []
    for row in SystemSettings.query.order_by(SystemSettings.key.asc()).all():
        is_secret = row.key in SettingsService.SECRET_KEYS
        shapes.append({
            'key': row.key,
            'value_type': 'secret' if is_secret else (row.value_type or 'string'),
            'is_set': bool(row.value),
        })
    return {'settings': shapes}


def _collect_job_failures():
    from app.jobs.models import Job
    rows = (
        Job.query
        .filter_by(status=Job.STATUS_FAILED)
        .order_by(Job.created_at.desc())
        .limit(RECENT_JOB_FAILURES)
        .all()
    )
    failures = []
    for job in rows:
        failures.append({
            'id': job.id,
            'kind': job.kind,
            'attempts': job.attempts,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'error_message': _scrub(job.error_message or ''),
        })
    return {'recent_failures': failures}


def _collect_restore_confidence():
    """Per-policy restore-proof summary (plan 23): last run + verify level, last
    drill age/status, cadence, offsite evidence level. Counts and states only —
    no paths, no secrets, matching the bundle's scrub discipline."""
    from datetime import datetime
    from app.models.backup_policy import BackupPolicy
    from app.models.backup_run import BackupRun

    policies = []
    for policy in BackupPolicy.query.order_by(BackupPolicy.id.asc()).all():
        latest = (BackupRun.query
                  .filter_by(policy_id=policy.id, status='success')
                  .order_by(BackupRun.started_at.desc()).first())
        offsite = (latest.get_metadata() or {}).get('offsite') if latest else None
        last_drill_age_days = None
        if policy.last_drill_at:
            last_drill_age_days = (datetime.utcnow() - policy.last_drill_at).days
        policies.append({
            'target_type': policy.target_type,
            'target_id': policy.target_id,
            'enabled': policy.enabled,
            'remote_copy': policy.remote_copy,
            'drill_cadence': policy.drill_cadence or 'off',
            'last_run_status': policy.last_status,
            'latest_verify_level': latest.effective_verify_level() if latest else 'none',
            'latest_verify_error': bool(latest and latest.verify_error),
            'last_drill_status': policy.last_drill_status,
            'last_drill_age_days': last_drill_age_days,
            'offsite_evidence': (offsite or {}).get('evidence') if offsite else None,
            'offsite_deep_evidence': (offsite or {}).get('deep_evidence') if offsite else None,
        })
    return {'policies': policies, 'total': len(policies)}


def _collect_doctor():
    """Last doctor report, if the doctor service (built separately) exposes one."""
    try:
        from app.services import doctor_service
    except Exception:  # noqa: BLE001 - module may not exist yet
        return {'skipped': 'doctor service not available'}
    for attr in ('get_last_report', 'last_report'):
        candidate = getattr(doctor_service, attr, None)
        if candidate is None:
            continue
        try:
            report = candidate() if callable(candidate) else candidate
            return {'report': json.loads(_scrub(json.dumps(report, default=str)))}
        except Exception as exc:  # noqa: BLE001
            return {'error': f'doctor report unavailable: {exc.__class__.__name__}'}
    return {'skipped': 'doctor service exposes no last report'}


def _collect_log_tail():
    for candidate in LOG_FILE_CANDIDATES:
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, 'r', encoding='utf-8', errors='replace') as fh:
                lines = fh.readlines()[-LOG_TAIL_LINES:]
            return f'# source: {candidate}\n' + _scrub(''.join(lines))
        except OSError:
            continue
    return '# no panel log file found (systemd deployments log to the journal)\n'


def build(out_path=None, passphrase=None):
    """Build the support bundle zip. Returns the absolute path to the zip.

    Must run inside an app context. ``passphrase`` is accepted for forward
    compatibility but zip encryption is unavailable without pyzipper (not a
    dependency) — the limitation is recorded in the bundle README.
    """
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    if not out_path:
        out_path = os.path.join(tempfile.gettempdir(), f'serverkit-support-{stamp}.zip')
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)

    sections = {
        'meta.json': _safe('meta', _collect_meta),
        'db.json': _safe('db', _collect_db),
        'counts.json': _safe('counts', _collect_counts),
        'services.json': _safe('services', _collect_services),
        'settings_shapes.json': _safe('settings_shapes', _collect_settings_shapes),
        'jobs.json': _safe('jobs', _collect_job_failures),
        'doctor.json': _safe('doctor', _collect_doctor),
        'restore_confidence.json': _safe('restore_confidence', _collect_restore_confidence),
    }
    log_tail = _safe('log_tail', _collect_log_tail, default='# log collection failed\n')

    readme_lines = [
        'ServerKit support bundle',
        f'Generated: {sections["meta.json"].get("generated_at", "unknown")}',
        '',
        'Contents are diagnostic shapes only: setting VALUES are never included,',
        'and all collected text is scrubbed for token/password/secret/key material.',
    ]
    if passphrase:
        readme_lines += [
            '',
            'NOTE: a passphrase was requested, but built-in zip encryption requires',
            'pyzipper, which is not a ServerKit dependency. This bundle is NOT',
            'encrypted — encrypt it yourself before sharing, e.g.:',
            '  gpg -c ' + os.path.basename(out_path),
        ]
        logger.warning('support bundle: passphrase requested but pyzipper is not installed; wrote plain zip')

    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('README.txt', '\n'.join(readme_lines) + '\n')
        for name, payload in sections.items():
            serialized = json.dumps(payload, indent=2, default=str)
            zf.writestr(name, _scrub(serialized))
        zf.writestr('log_tail.txt', log_tail)

    return out_path
