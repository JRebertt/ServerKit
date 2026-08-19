"""
Resource Tier / Server Capacity Service

Answers two questions that the panel has to keep separate:

1. "What did we install?" — the install profile (minimal/standard/full). Decided
   once by install.sh, recorded in config, and readable from
   ``install_profile_service``. It is a starting point, never a permanent SKU.

2. "What can this box still hold?" — headroom. This is live: it changes every
   time the operator deploys something, and it is what the UI should actually
   surface.

The original three-bucket tier (lite/standard/performance) conflated the two.
It classified a server once from total CPU/RAM and then permanently disabled a
button, which is both wrong the moment the VPS is resized and reads like a
paywall on an OSS panel. ``tier`` is still derived and returned for the callers
that display it, but every feature flag is now advisory — the panel reports
headroom and lets the operator decide.
"""

import logging
import os
import shutil
import time

from app.services.cache_service import ttl_cached

import psutil

logger = logging.getLogger(__name__)

# Specs and the tier label are stable enough to cache for an hour (ttl_cached,
# plan 77 F2); headroom is recomputed on every call because it is the number
# that moves. _probe_count lets get_resource_tier report whether this response
# came from cache without a second bookkeeping dict.
_TIER_TTL_SECONDS = 3600
_probe_count = 0

# Memory the panel refuses to hand out to workloads. ServerKit's own process
# floor is ~250MB (gunicorn + SQLAlchemy + the Python interpreter's ~76MB
# baseline); psutil's `available` already excludes that once the panel is up, so
# only the OS margin is subtracted from headroom. PANEL_FOOTPRINT_MB is kept for
# install-time and reporting callers that need the number explicitly.
PANEL_FOOTPRINT_MB = 256
# Kernel page cache, sshd, nginx, journald. Handing an app the last free
# megabyte is how a box becomes unreachable, so this is never offered.
OS_RESERVE_MB = 256

# Rough steady-state RSS per workload kind, used to translate a headroom number
# into something an operator can act on ("about one WordPress site"). These are
# deliberately conservative — over-promising capacity is worse than
# under-promising it.
WORKLOAD_FOOTPRINTS_MB = {
    'static': 32,
    'node': 192,
    'python': 192,
    'database': 384,
    'wordpress': 512,
}

# Disk below this on the data volume means image pulls and backups will fail
# before RAM ever becomes the binding constraint. Defined once in
# host_inventory_service so the panel has a single idea of "low".
from app.services.host_inventory_service import LOW_FREE_GB as LOW_DISK_THRESHOLD_GB  # noqa: E402


class ResourceTierService:
    """Server capacity reporting: specs, live headroom, and an advisory tier."""

    TIER_LITE = 'lite'
    TIER_STANDARD = 'standard'
    TIER_PERFORMANCE = 'performance'

    # Comfortable-minimum guidance for WordPress. Advisory only — nothing in
    # the backend refuses a create based on these.
    MIN_CORES_FOR_WORDPRESS = 2
    MIN_RAM_GB_FOR_WORDPRESS = 2

    @classmethod
    def get_tier_info(cls, force_refresh=False):
        """
        Get capacity information: specs, live headroom, tier label, advisories.

        Args:
            force_refresh: If True, bypass the specs cache and re-read hardware

        Returns:
            dict: {
                'tier': 'lite'|'standard'|'performance',
                'specs': {...},
                'headroom': {...},
                'features': {...},   # advisory flags, all currently permissive
                'cached': bool
            }
        """
        if force_refresh:
            _probe_tier.invalidate()
        before = _probe_count
        data = _probe_tier()
        # Headroom is never served from cache — it is the live number.
        return {
            **data,
            'headroom': cls.get_headroom(data['specs']),
            'cached': _probe_count == before,
        }

    @classmethod
    def _get_system_specs(cls):
        """
        Get CPU, RAM, disk, swap and virtualisation facts about this host.

        Both ``ram_gb`` and ``total_memory_gb`` are returned: the original key
        plus the name the setup wizard was already reading. The wizard rendered
        a blank RAM figure for as long as only ``ram_gb`` existed.
        """
        cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 1
        memory = psutil.virtual_memory()
        ram_bytes = memory.total
        ram_gb = round(ram_bytes / (1024 ** 3), 2)

        swap_mb = 0
        try:
            swap_mb = int(psutil.swap_memory().total / (1024 ** 2))
        except Exception as e:  # pragma: no cover - platform dependent
            logger.debug(f'Could not read swap: {e}')

        disk_free_gb = None
        try:
            disk_free_gb = round(shutil.disk_usage(cls._data_path()).free / (1024 ** 3), 2)
        except Exception as e:  # pragma: no cover - platform dependent
            logger.debug(f'Could not read disk usage: {e}')

        return {
            'cpu_cores': cpu_cores,
            'ram_gb': ram_gb,
            'total_memory_gb': ram_gb,
            'ram_bytes': ram_bytes,
            'swap_mb': swap_mb,
            'disk_free_gb': disk_free_gb,
            'container': cls._detect_container(),
        }

    @staticmethod
    def _data_path():
        """Volume to measure free space on — where images and backups land.

        Delegates to host_inventory_service so this and capacity_service can no
        longer answer the same question differently (plan 74).
        """
        from app.services import host_inventory_service
        return host_inventory_service.data_path()

    @staticmethod
    def _detect_container():
        """
        Identify container virtualisation, or None on bare metal / a full VM.

        This matters more than core count on small hosts: Docker frequently
        cannot run inside an unprivileged LXC or OpenVZ container at all, so a
        box can look adequate on paper and still be unable to host anything.
        """
        try:
            if os.path.exists('/.dockerenv'):
                return 'docker'
            if os.path.isdir('/proc/vz') and not os.path.isdir('/proc/bc'):
                return 'openvz'
            # systemd-nspawn and LXC both advertise themselves here.
            with open('/proc/1/environ', 'rb') as fh:
                environ = fh.read().decode('utf-8', 'replace')
            for entry in environ.split('\0'):
                if entry.startswith('container='):
                    return entry.split('=', 1)[1] or 'container'
        except Exception:
            # /proc is absent on Windows dev boxes and restricted in some
            # sandboxes — "unknown" is the honest answer, not an error.
            return None
        return None

    @classmethod
    def get_headroom(cls, specs=None):
        """
        How much room is actually left for workloads, right now.

        Unlike the tier label this is computed from *available* memory rather
        than installed memory, so it reflects what the operator has already
        deployed. Returns the raw numbers plus a plain-language summary and a
        per-workload fit map the UI can render without doing arithmetic.

        Returns:
            dict: {
                'ram_available_mb': int,
                'ram_for_apps_mb': int,
                'disk_free_gb': float|None,
                'swap_mb': int,
                'fits': {workload: bool},
                'summary': str,
                'warnings': [str],
            }
        """
        if specs is None:
            specs = cls._get_system_specs()

        try:
            available_mb = int(psutil.virtual_memory().available / (1024 ** 2))
        except Exception as e:  # pragma: no cover - platform dependent
            logger.debug(f'Could not read available memory: {e}')
            available_mb = 0

        ram_for_apps_mb = max(0, available_mb - OS_RESERVE_MB)

        fits = {
            name: ram_for_apps_mb >= need
            for name, need in WORKLOAD_FOOTPRINTS_MB.items()
        }

        warnings = []
        if specs.get('container') in ('lxc', 'openvz'):
            warnings.append(
                f"This host is an {specs['container'].upper()} container. Docker often "
                'cannot run in one — if container features fail, that is why.'
            )
        disk_free_gb = specs.get('disk_free_gb')
        if disk_free_gb is not None and disk_free_gb < LOW_DISK_THRESHOLD_GB:
            warnings.append(
                f'Only {disk_free_gb} GB of disk free. Image pulls and backups '
                'need room before RAM becomes the limit.'
            )
        if specs.get('ram_gb', 0) < 2 and not specs.get('swap_mb'):
            warnings.append(
                'No swap on a low-RAM box. Builds are likely to be OOM-killed.'
            )

        return {
            'ram_available_mb': available_mb,
            'ram_for_apps_mb': ram_for_apps_mb,
            'panel_footprint_mb': PANEL_FOOTPRINT_MB,
            'os_reserve_mb': OS_RESERVE_MB,
            'disk_free_gb': disk_free_gb,
            'swap_mb': specs.get('swap_mb', 0),
            'fits': fits,
            'summary': cls._describe_headroom(ram_for_apps_mb),
            'warnings': warnings,
        }

    @classmethod
    def _describe_headroom(cls, ram_for_apps_mb):
        """
        Turn a megabyte count into something an operator can act on.

        "1.2 GB free — about one WordPress site" beats "you are Lite tier",
        which says nothing about what they can actually do next.
        """
        if ram_for_apps_mb < WORKLOAD_FOOTPRINTS_MB['static']:
            return 'No room for new workloads right now.'

        gb = round(ram_for_apps_mb / 1024, 1)
        amount = f'{gb} GB' if ram_for_apps_mb >= 1024 else f'{ram_for_apps_mb} MB'

        # Describe capacity with the largest workload that fits, so the phrasing
        # degrades gracefully on small boxes instead of claiming "0 sites".
        if ram_for_apps_mb >= WORKLOAD_FOOTPRINTS_MB['wordpress']:
            count = ram_for_apps_mb // WORKLOAD_FOOTPRINTS_MB['wordpress']
            unit = 'WordPress site' if count == 1 else 'WordPress sites'
            return f'{amount} free — roughly {count} {unit}.'
        if ram_for_apps_mb >= WORKLOAD_FOOTPRINTS_MB['node']:
            count = ram_for_apps_mb // WORKLOAD_FOOTPRINTS_MB['node']
            unit = 'small app' if count == 1 else 'small apps'
            return f'{amount} free — roughly {count} {unit}, but not WordPress.'
        return f'{amount} free — enough for static sites only.'

    @classmethod
    def _calculate_tier(cls, specs):
        """
        Derive the advisory tier label from installed specs.

        Retained for display and for callers that still read ``tier``. Nothing
        is gated on it any more — see ``_get_features_for_tier``.

        - Lite: 1 core OR <2GB RAM
        - Performance: 4+ cores AND >4GB RAM
        - Standard: everything else
        """
        cpu_cores = specs['cpu_cores']
        ram_gb = specs['ram_gb']

        if cpu_cores < 2 or ram_gb < 2:
            return cls.TIER_LITE

        if cpu_cores >= 4 and ram_gb > 4:
            return cls.TIER_PERFORMANCE

        return cls.TIER_STANDARD

    @classmethod
    def _get_features_for_tier(cls, tier, specs):
        """
        Advisory capability flags.

        Every flag is permissive. ``*_advised`` companions carry the
        recommendation so the UI can warn at the point of action instead of
        hiding the action, which is the difference between protecting an
        operator and overruling them.
        """
        wordpress_advised = (
            specs['cpu_cores'] >= cls.MIN_CORES_FOR_WORDPRESS and
            specs['ram_gb'] >= cls.MIN_RAM_GB_FOR_WORDPRESS
        )

        return {
            'wordpress_create': True,
            'wordpress_create_advised': wordpress_advised,
            'wordpress_manage': True,
            'docker': True,
            'databases': True,
        }

    @classmethod
    def can_create_wordpress(cls):
        """
        Whether WordPress creation is permitted. Always True.

        Kept so existing callers keep working; use
        ``is_wordpress_advised()`` for the resource recommendation.
        """
        return True

    @classmethod
    def is_wordpress_advised(cls):
        """Whether this server comfortably meets the WordPress recommendation."""
        tier_info = cls.get_tier_info()
        return tier_info['features']['wordpress_create_advised']

    @classmethod
    def get_minimum_requirements(cls):
        """Recommended minimum specs for WordPress."""
        return {
            'cpu_cores': cls.MIN_CORES_FOR_WORDPRESS,
            'ram_gb': cls.MIN_RAM_GB_FOR_WORDPRESS
        }


@ttl_cached(_TIER_TTL_SECONDS, key_fn=lambda: 'tier')
def _probe_tier():
    """The cacheable part of the tier answer: specs, label, feature flags."""
    global _probe_count
    _probe_count += 1
    specs = ResourceTierService._get_system_specs()
    tier = ResourceTierService._calculate_tier(specs)
    features = ResourceTierService._get_features_for_tier(tier, specs)
    return {'tier': tier, 'specs': specs, 'features': features}
