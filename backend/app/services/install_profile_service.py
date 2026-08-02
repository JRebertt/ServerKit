"""
Install Profile Service

An install profile records *what install.sh put on the box* — not what the box
is allowed to do. It is a starting point, chosen once from detected hardware
and always overridable by the operator, and everything a profile skips stays
installable later from Settings. Nothing here is a licence check.

    minimal   Panel + nginx + SQLite. No Docker, no Node toolchain.
              For 512MB-1GB boxes, LXC/OpenVZ containers where Docker will not
              run anyway, and hosts where Docker is managed elsewhere.
              Monitoring, domains, certificates, cron and DNS all still work.

    standard  + Docker and the compose plugin. Can host applications.

    full      + the recommended extension set for the chosen use cases and the
              source-build toolchain.

The recommendation thresholds below are mirrored by ``recommend_profile`` in
install.sh. They have to agree: the installer picks a profile before the panel
exists, and the wizard then shows the operator what was picked. Change one,
change the other.
"""

import logging
import os
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)

# The Docker probe shells out and can block for its full timeout on a host with
# a wedged daemon — exactly the host most likely to be asking. Cache the answer
# briefly so a page load never pays that twice, but keep the window short
# enough that installing Docker shows up without a restart.
_CAPABILITY_TTL_SECONDS = 60
_capability_cache = {'data': None, 'timestamp': 0}

PROFILE_MINIMAL = 'minimal'
PROFILE_STANDARD = 'standard'
PROFILE_FULL = 'full'

VALID_PROFILES = (PROFILE_MINIMAL, PROFILE_STANDARD, PROFILE_FULL)

DEFAULT_PROFILE = PROFILE_STANDARD

# Settings key holding an operator override applied after install (e.g. they
# installed minimal, then added Docker from Settings later).
PROFILE_SETTING_KEY = 'install.profile'

# Recommendation thresholds — keep in sync with install.sh recommend_profile().
MINIMAL_MAX_RAM_GB = 1.5
MINIMAL_MIN_DISK_GB = 5
FULL_MIN_RAM_GB = 4
FULL_MIN_CORES = 4
FULL_MIN_DISK_GB = 20

PROFILE_DESCRIPTIONS = {
    PROFILE_MINIMAL: {
        'label': 'Minimal',
        'summary': 'Panel only — monitoring, domains, certificates, cron and DNS.',
        'installs': ['ServerKit panel', 'nginx', 'SQLite'],
        'skips': ['Docker', 'Node.js build toolchain'],
        'suited_for': '512MB-1GB RAM, or containers where Docker cannot run.',
    },
    PROFILE_STANDARD: {
        'label': 'Standard',
        'summary': 'Everything in Minimal, plus Docker so the server can host apps.',
        'installs': ['ServerKit panel', 'nginx', 'SQLite', 'Docker', 'compose plugin'],
        'skips': ['Use-case extensions (pick them in the next step)'],
        'suited_for': '2GB RAM and up.',
    },
    PROFILE_FULL: {
        'label': 'Full',
        'summary': 'Everything in Standard, plus the daemons the panel\'s security '
                   'and certificate features depend on.',
        'installs': [
            'ServerKit panel', 'nginx', 'SQLite', 'Docker', 'compose plugin',
            'fail2ban (powers jail management)', 'certbot (automatic HTTPS)',
        ],
        'skips': [],
        'suited_for': '4GB RAM, 4 cores and 20GB disk or better.',
    },
}


def recommend_profile(specs):
    """
    Recommend a profile from detected hardware.

    Mirrors install.sh's recommend_profile(). Deliberately conservative: a box
    that is recommended Minimal can still be pushed to Standard by the
    operator, but silently defaulting a 700MB VPS to a Docker install produces
    an OOM during the first deploy.

    Args:
        specs: dict from ResourceTierService._get_system_specs()

    Returns:
        str: one of VALID_PROFILES
    """
    ram_gb = specs.get('ram_gb') or 0
    cores = specs.get('cpu_cores') or 1
    disk_free_gb = specs.get('disk_free_gb')
    container = specs.get('container')

    # Unprivileged LXC/OpenVZ frequently cannot run Docker at all. Recommending
    # Standard there produces an install that looks fine and then fails on the
    # first deploy.
    if container in ('lxc', 'openvz'):
        return PROFILE_MINIMAL

    if ram_gb < MINIMAL_MAX_RAM_GB:
        return PROFILE_MINIMAL

    if disk_free_gb is not None and disk_free_gb < MINIMAL_MIN_DISK_GB:
        return PROFILE_MINIMAL

    if (
        ram_gb >= FULL_MIN_RAM_GB
        and cores >= FULL_MIN_CORES
        and (disk_free_gb is None or disk_free_gb >= FULL_MIN_DISK_GB)
    ):
        return PROFILE_FULL

    return PROFILE_STANDARD


def get_profile():
    """
    The profile this install is running under.

    Resolution order: operator override in settings, then the value install.sh
    wrote to the environment, then the default. An unrecognised value falls
    back to the default rather than raising — a hand-edited .env should not
    take the panel down.
    """
    try:
        from app.services.settings_service import SettingsService
        override = SettingsService.get(PROFILE_SETTING_KEY)
        if override in VALID_PROFILES:
            return override
    except Exception as e:
        # Called before the DB is ready during early boot.
        logger.debug(f'Settings unavailable for install profile: {e}')

    env_profile = (os.environ.get('SERVERKIT_PROFILE') or '').strip().lower()
    if env_profile in VALID_PROFILES:
        return env_profile

    if env_profile:
        logger.warning(
            f'Unrecognised SERVERKIT_PROFILE={env_profile!r}; '
            f'falling back to {DEFAULT_PROFILE}.'
        )
    return DEFAULT_PROFILE


def set_profile(profile, user_id=None):
    """Record an operator's profile change (e.g. after adding Docker later)."""
    if profile not in VALID_PROFILES:
        raise ValueError(f'Unknown profile: {profile}')

    from app.services.settings_service import SettingsService
    SettingsService.set(PROFILE_SETTING_KEY, profile, user_id=user_id)
    return profile


def _binary_present(name):
    return shutil.which(name) is not None


def _docker_usable():
    """
    Whether Docker is present *and* the daemon answers.

    An installed binary proves nothing — inside LXC the client is often present
    while the daemon has never started, which is exactly the case the Minimal
    profile exists for.
    """
    if not _binary_present('docker'):
        return False
    try:
        result = subprocess.run(
            ['docker', 'info', '--format', '{{.ServerVersion}}'],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug(f'Docker probe failed: {e}')
        return False


def get_capabilities(force_refresh=False):
    """
    What this install can actually do right now, probed live.

    The profile says what was *intended*; this says what is *true*. They drift
    — an operator can apt-install Docker on a Minimal box, and a Standard box
    can have a broken daemon. Cached for _CAPABILITY_TTL_SECONDS because the
    Docker probe can block.
    """
    now = time.time()
    if (
        not force_refresh
        and _capability_cache['data'] is not None
        and (now - _capability_cache['timestamp']) < _CAPABILITY_TTL_SECONDS
    ):
        return dict(_capability_cache['data'])

    docker = _docker_usable()
    capabilities = {
        'docker': docker,
        'node': _binary_present('node'),
        'nginx': _binary_present('nginx'),
        'git': _binary_present('git'),
        # The panel is only useful for hosting apps if containers work.
        'can_host_apps': docker,
    }

    _capability_cache['data'] = capabilities
    _capability_cache['timestamp'] = now
    return dict(capabilities)


def get_profile_info(force_refresh=False):
    """Profile, its description, live capabilities, and any drift between them."""
    profile = get_profile()
    capabilities = get_capabilities(force_refresh=force_refresh)

    drift = []
    if profile in (PROFILE_STANDARD, PROFILE_FULL) and not capabilities['docker']:
        drift.append(
            'This install is on the '
            f'{PROFILE_DESCRIPTIONS[profile]["label"]} profile but Docker is not '
            'responding, so apps cannot be deployed.'
        )
    if profile == PROFILE_MINIMAL and capabilities['docker']:
        drift.append(
            'Docker is available even though this install is on the Minimal '
            'profile — app hosting will work.'
        )

    return {
        'profile': profile,
        'profiles': PROFILE_DESCRIPTIONS,
        'capabilities': capabilities,
        'drift': drift,
    }
