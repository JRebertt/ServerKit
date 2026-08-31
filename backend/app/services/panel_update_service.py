"""Panel self-update — run scripts/update.sh from the UI.

The hard parts of updating (blue/green slot switch, DB migration ordering,
post-switch health check, automatic rollback) already live in
``scripts/update.sh``. This service deliberately adds none of that; it only
answers "can this install self-update?", launches the script, and reports
progress from the script's own log.

The one non-obvious mechanic is *how* the script is launched. The updater
restarts the ``serverkit`` systemd unit — the very unit this process runs in.
A plain ``subprocess.Popen`` child lives in that unit's cgroup, so
``systemctl stop serverkit`` would kill the update mid-flight, exactly at the
point of no return. ``systemd-run`` starts the script in its own transient
unit (its own cgroup), so it survives the panel restart it performs.

Status is stateless on purpose: an update restarts this process, so anything
kept in memory would be lost at the most interesting moment. "Running" is the
transient unit's state; progress is the tail of the ``update-*.log`` file the
script already writes. Both survive the restart and are readable by the new
process.
"""
import glob
import os
import re
import shutil

from app.exceptions import ConflictError, ValidationError
from app.utils.system import run_checked
from app.utils.version import get_install_dir, get_panel_version

# Fixed transient-unit name: makes "is an update already running" a single
# systemctl query and guarantees two concurrent starts collide loudly inside
# systemd instead of racing each other through the updater.
UPDATE_UNIT = 'serverkit-panel-update'

# Must match LOG_DIR in scripts/update.sh — that is what writes update-*.log.
LOG_DIR = '/var/log/serverkit'

# Outcome markers printed by scripts/update.sh (see its summary and rollback()).
_SUCCESS_MARKER = 'Update complete'
_ROLLBACK_MARKER = 'Rolled back to'

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


# Split out so tests can fake a platform without touching the real ``os``
# module (a leaked os.name patch takes the whole pytest run down on Windows).
def _is_windows():
    return os.name == 'nt'


def _in_docker():
    return os.path.exists('/.dockerenv')


def _is_root():
    return hasattr(os, 'geteuid') and os.geteuid() == 0


def get_capability():
    """Whether — and how — this install can self-update.

    ``mode`` is 'systemd' (one-click works), 'docker' (the panel container
    cannot replace itself; the operator pulls a new image on the host), or
    'unsupported' (dev servers, missing tooling), with ``reason`` saying why.
    """
    if _is_windows():
        return {'supported': False, 'mode': 'unsupported',
                'reason': 'Self-update requires a Linux install.'}

    if _in_docker():
        return {'supported': False, 'mode': 'docker',
                'reason': 'The panel runs in a container and cannot replace '
                          'its own image. Update on the host with: '
                          'docker compose pull && docker compose up -d'}

    # Prod installs run the panel as root (templates/serverkit-backend.service.in);
    # anything else is a dev server that must not get a working update button.
    if not _is_root():
        return {'supported': False, 'mode': 'unsupported',
                'reason': 'The panel is not running as root — this looks like '
                          'a development server.'}

    script = os.path.join(get_install_dir(), 'scripts', 'update.sh')
    if not os.path.exists(script):
        return {'supported': False, 'mode': 'unsupported',
                'reason': f'Updater script not found at {script}.'}

    for tool in ('systemd-run', 'systemctl'):
        if not shutil.which(tool):
            return {'supported': False, 'mode': 'unsupported',
                    'reason': f'{tool} not available — self-update needs a '
                              'systemd host.'}

    return {'supported': True, 'mode': 'systemd', 'reason': None,
            'script': script}


def is_running():
    """True while the transient update unit is executing."""
    result = run_checked(['systemctl', 'is-active', UPDATE_UNIT], timeout=10)
    # is-active exits non-zero for every state but 'active'; the output is the
    # state either way. 'activating' covers Type=oneshot-style startup.
    return result['output'].strip() in ('active', 'activating')


def latest_log(max_bytes=8192):
    """Newest update-*.log the script wrote, with an ANSI-stripped tail.

    Returns None when no update has ever logged. ``outcome`` is a best-effort
    hint parsed from the tail — 'success', 'rolled_back', or None while the
    log has neither marker yet.
    """
    try:
        logs = glob.glob(os.path.join(LOG_DIR, 'update-*.log'))
        if not logs:
            return None
        path = max(logs, key=os.path.getmtime)
        size = os.path.getsize(path)
        with open(path, 'rb') as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            tail = fh.read().decode('utf-8', errors='replace')
    except OSError:
        return None

    tail = _ANSI_RE.sub('', tail)
    outcome = None
    if _SUCCESS_MARKER in tail:
        outcome = 'success'
    elif _ROLLBACK_MARKER in tail:
        outcome = 'rolled_back'
    return {
        'path': path,
        'mtime': os.path.getmtime(path),
        'tail': tail,
        'outcome': outcome,
    }


def get_status():
    """One stateless snapshot the UI can poll before, during and after."""
    capability = get_capability()
    status = {
        'capability': capability,
        'running': False,
        'unit': UPDATE_UNIT,
        'version': get_panel_version(),
        'log': None,
    }
    if capability['supported']:
        status['running'] = is_running()
        status['log'] = latest_log()
    return status


def start_update():
    """Launch scripts/update.sh in its own transient systemd unit.

    Raises ValidationError when this install cannot self-update and
    ConflictError when an update is already in flight.
    """
    capability = get_capability()
    if not capability['supported']:
        raise ValidationError(capability['reason'])
    if is_running():
        raise ConflictError('An update is already running.')

    # A previous failed run can leave the fixed-name unit in 'failed' and make
    # systemd-run refuse the name. Best-effort clear; harmless when clean.
    run_checked(['systemctl', 'reset-failed', UPDATE_UNIT], timeout=10)

    result = run_checked([
        'systemd-run',
        '--unit', UPDATE_UNIT,
        # Unload the unit when it finishes even on failure — outcome lives in
        # the update-*.log, not in lingering unit state.
        '--collect',
        '/bin/bash', capability['script'],
    ], timeout=30)
    if not result['success']:
        raise ValidationError(
            f"Failed to launch the updater: {result['error'] or result['stderr']}")

    return {'started': True, 'unit': UPDATE_UNIT}
