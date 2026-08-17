"""What this host is made of, and whether that changed since last time.

The panel already reads CPU, RAM and disk live in three places. What it never
did was *remember*, so a VPS resize or a newly attached volume produced a
different number that nobody was told about. This module is the memory: it
captures a snapshot at boot, diffs it against the last one, and turns the
difference into something worth interrupting an operator for.

It also owns the single definition of "the filesystem that matters"
(``data_path``). Two services used to answer that question privately and
disagree — ``resource_tier_service`` measured the first of
``/var/lib/serverkit`` / ``/var/lib/docker`` / ``/`` while ``capacity_service``
hardcoded ``/``. On a default box those coincide; move Docker onto a volume and
they silently diverge, and neither number said which disk it came from.

Every probe here is best-effort. Windows dev boxes have no ``/proc`` and no
``/etc/fstab``, and a restricted container may refuse any of it — the honest
answer is None/False, never an exception.
"""
import logging
import os

import psutil

logger = logging.getLogger(__name__)

#: Below this, image pulls and backups start failing before RAM is ever the
#: binding constraint. Shared with resource_tier_service so the panel has one
#: idea of "low".
LOW_FREE_GB = 5

#: A data volume with at least this much free space is worth pointing at when
#: something else is short. Deliberately about free space and not emptiness: a
#: volume already holding 20 GB with 40 GB spare is still exactly where backups
#: or Docker data should be relocated to.
SPARE_VOLUME_MIN_FREE_GB = 10

#: Mounts that are never interesting as storage: kernel/pseudo filesystems and
#: the per-container overlays Docker stacks on top of a real disk (counting
#: those would report the same bytes a dozen times).
_EXCLUDED_FSTYPES = {
    'autofs', 'binfmt_misc', 'bpf', 'cgroup', 'cgroup2', 'configfs', 'debugfs',
    'devpts', 'devtmpfs', 'fuse.snapfuse', 'fusectl', 'hugetlbfs', 'iso9660',
    'mqueue', 'nsfs', 'overlay', 'overlayfs', 'proc', 'pstore', 'ramfs',
    'securityfs', 'squashfs', 'sysfs', 'tmpfs', 'tracefs', 'udf',
}

_EXCLUDED_PREFIXES = (
    '/proc', '/sys', '/dev', '/run', '/snap',
    '/var/lib/docker/', '/var/lib/containerd/',
    # WSL's own plumbing on a Windows dev box — not storage anyone manages.
    '/mnt/wsl', '/mnt/wslg',
)


# --------------------------------------------------------------------------- #
# The one definition of "which disk matters"
# --------------------------------------------------------------------------- #

def data_path():
    """The directory whose filesystem holds images, volumes and backups.

    Ordered most-specific-first: an operator who mounted a volume at
    ``/var/lib/serverkit`` means that one, and someone who only moved Docker
    means ``/var/lib/docker``. Falls back to the root filesystem.
    """
    for path in ('/var/lib/serverkit', '/var/lib/docker', '/'):
        if os.path.isdir(path):
            return path
    return os.getcwd()


def data_path_usage():
    """``(mountpoint, usage)`` for :func:`data_path`, or ``(path, None)``.

    Returns the mountpoint alongside the numbers so a caller can say *which*
    filesystem it measured. An unlabelled free-space figure is how the two
    previous implementations managed to disagree without anyone noticing.
    """
    path = data_path()
    try:
        import shutil
        usage = shutil.disk_usage(path)
    except Exception as e:  # noqa: BLE001 — a probe failure is "unknown"
        logger.debug(f'Could not read disk usage for {path}: {e}')
        return path, None
    return mountpoint_for(path) or path, usage


def mountpoint_for(path):
    """Which mounted filesystem *path* actually lives on, or None."""
    try:
        best = None
        real = os.path.realpath(path)
        for part in psutil.disk_partitions(all=False):
            mp = part.mountpoint
            if real == mp or real.startswith(mp.rstrip('/') + '/'):
                if best is None or len(mp) > len(best):
                    best = mp
        return best
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #

def boot_id():
    """This boot's kernel-assigned id, or None off Linux.

    Changes on every reboot, which is what separates "the box was resized while
    it was off" from "a volume was attached under a running panel".
    """
    try:
        with open('/proc/sys/kernel/random/boot_id', 'r') as fh:
            return fh.read().strip() or None
    except Exception:  # noqa: BLE001
        return None


def _fstab_entries():
    """``(device_specs, mountpoints)`` named in /etc/fstab.

    Both are returned because a mount can be named four ways — by device, by
    ``UUID=``, by ``LABEL=`` or simply by where it lands — and matching only one
    of them produces false "not persisted" warnings. On DigitalOcean's Ubuntu
    image the root filesystem is written as ``LABEL=cloudimg-rootfs``, so a
    device-only check would flag ``/`` itself as unpersisted.
    """
    specs, mounts = set(), set()
    try:
        with open('/etc/fstab', 'r') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                fields = line.split()
                if len(fields) < 2:
                    continue
                specs.add(fields[0])
                mounts.add(os.path.normpath(fields[1]))
    except Exception:  # noqa: BLE001 — absent on Windows, unreadable in some sandboxes
        return None, None
    return specs, mounts


def _resolve_spec(spec):
    """Turn a ``UUID=``/``LABEL=``/``PARTUUID=`` fstab spec into a device path."""
    by_dir = {
        'UUID': '/dev/disk/by-uuid',
        'LABEL': '/dev/disk/by-label',
        'PARTUUID': '/dev/disk/by-partuuid',
        'PARTLABEL': '/dev/disk/by-partlabel',
    }
    if '=' not in spec:
        return spec
    kind, _, value = spec.partition('=')
    directory = by_dir.get(kind.upper())
    if not directory:
        return spec
    try:
        return os.path.realpath(os.path.join(directory, value))
    except Exception:  # noqa: BLE001
        return spec


def enumerate_filesystems():
    """Every real mounted filesystem, with usage and persistence facts."""
    specs, fstab_mounts = _fstab_entries()
    resolved = {_resolve_spec(s) for s in specs} if specs else set()
    fstab_known = specs is not None

    root_device = None
    filesystems = []
    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception as e:  # noqa: BLE001
        logger.debug(f'Could not enumerate partitions: {e}')
        return []

    # A device mounted more than once (bind mounts, btrfs subvolumes) is still
    # one disk. Counting each mountpoint separately would report the same free
    # space several times and invent storage that does not exist — measured on
    # a dev box where one disk surfaced as six mounts of 936 GB each.
    seen_devices = set()

    for part in sorted(partitions, key=lambda p: len(p.mountpoint)):
        if part.fstype in _EXCLUDED_FSTYPES:
            continue
        mount = os.path.normpath(part.mountpoint)
        if any(mount.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        # Read-only media is not storage anything can be relocated onto.
        opts = (part.opts or '').split(',')
        if 'ro' in opts:
            continue
        if part.device in seen_devices:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        seen_devices.add(part.device)

        if mount == os.sep or mount == '/':
            root_device = part.device

        # `in_fstab` is None — not False — when /etc/fstab could not be read at
        # all. "We don't know" must not render as "it will vanish on reboot".
        in_fstab = None
        if fstab_known:
            in_fstab = (part.device in specs
                        or part.device in resolved
                        or mount in fstab_mounts)

        filesystems.append({
            'device': part.device,
            'mountpoint': mount,
            'fstype': part.fstype,
            'total': usage.total,
            'used': usage.used,
            'free': usage.free,
            'percent': usage.percent,
            'in_fstab': in_fstab,
            'is_data_volume': False,  # filled in below, once root is known
        })

    for entry in filesystems:
        entry['is_data_volume'] = (
            entry['mountpoint'] not in ('/', '/boot', '/boot/efi')
            and entry['device'] != root_device
        )
    # Stable order so a snapshot diff and the UI both read predictably.
    return sorted(filesystems, key=lambda f: f['mountpoint'])


def capture():
    """A full reading of this host, ready to persist or diff."""
    try:
        cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 1
    except Exception:  # noqa: BLE001
        cpu_cores = None
    try:
        ram_bytes = psutil.virtual_memory().total
    except Exception:  # noqa: BLE001
        ram_bytes = None
    try:
        swap_bytes = psutil.swap_memory().total
    except Exception:  # noqa: BLE001
        swap_bytes = None

    return {
        'boot_id': boot_id(),
        'cpu_cores': cpu_cores,
        'ram_bytes': ram_bytes,
        'swap_bytes': swap_bytes,
        'container': _detect_container(),
        'filesystems': enumerate_filesystems(),
    }


def _detect_container():
    """Container virtualisation, or None on bare metal / a full VM."""
    try:
        if os.path.exists('/.dockerenv'):
            return 'docker'
        if os.path.isdir('/proc/vz') and not os.path.isdir('/proc/bc'):
            return 'openvz'
        with open('/proc/1/environ', 'rb') as fh:
            environ = fh.read().decode('utf-8', 'replace')
        for entry in environ.split('\0'):
            if entry.startswith('container='):
                return entry.split('=', 1)[1] or 'container'
    except Exception:  # noqa: BLE001
        return None
    return None


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #

def _format_bytes(num_bytes):
    if num_bytes is None:
        return 'unknown'
    step = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if step < 1024 or unit == 'TB':
            return f'{step:.0f} {unit}' if step >= 10 or unit == 'B' else f'{step:.1f} {unit}'
        step /= 1024
    return f'{step:.1f} TB'


#: Ignore total-size jitter below this. A filesystem's reported total can move
#: by a few blocks across remounts without anything having actually changed.
_SIZE_NOISE_FLOOR = 64 * 1024 ** 2  # 64 MB


def diff(previous, current):
    """Human-readable deltas between two captures.

    ``previous`` is a dict in :func:`capture` shape (or a HostSnapshot's
    equivalent). Returns ``[]`` when nothing moved — which is a real answer,
    distinct from the ``None`` a first-ever capture records.
    """
    changes = []
    if not previous:
        return changes

    for field, label, fmt in (
        ('cpu_cores', 'CPU cores', str),
        ('ram_bytes', 'RAM', _format_bytes),
        ('swap_bytes', 'Swap', _format_bytes),
    ):
        before, after = previous.get(field), current.get(field)
        # A probe that failed this time must not be reported as a loss.
        if before is None or after is None or before == after:
            continue
        changes.append({
            'field': field,
            'kind': 'increased' if after > before else 'decreased',
            'from': before,
            'to': after,
            'summary': f'{label} {fmt(before)} → {fmt(after)}',
        })

    before_fs = {f['mountpoint']: f for f in (previous.get('filesystems') or [])}
    after_fs = {f['mountpoint']: f for f in (current.get('filesystems') or [])}

    for mount in sorted(after_fs.keys() - before_fs.keys()):
        entry = after_fs[mount]
        changes.append({
            'field': 'filesystem',
            'kind': 'mounted',
            'from': None,
            'to': mount,
            'summary': (f'New filesystem {mount} '
                        f'({_format_bytes(entry.get("total"))}, {entry.get("device")})'),
        })

    for mount in sorted(before_fs.keys() - after_fs.keys()):
        changes.append({
            'field': 'filesystem',
            'kind': 'unmounted',
            'from': mount,
            'to': None,
            'summary': f'Filesystem {mount} is no longer mounted',
        })

    for mount in sorted(after_fs.keys() & before_fs.keys()):
        before_total = before_fs[mount].get('total')
        after_total = after_fs[mount].get('total')
        if before_total is None or after_total is None:
            continue
        if abs(after_total - before_total) < _SIZE_NOISE_FLOOR:
            continue
        changes.append({
            'field': 'filesystem',
            'kind': 'resized',
            'from': before_total,
            'to': after_total,
            'summary': (f'{mount} {_format_bytes(before_total)} → '
                        f'{_format_bytes(after_total)}'),
        })

    return changes


# --------------------------------------------------------------------------- #
# Advisories
# --------------------------------------------------------------------------- #

def advisories(filesystems=None):
    """Correlations worth telling an operator about.

    Each has a stable ``key`` so the caller can notify on a state *transition*
    rather than on every boot — an fstab entry nobody has got round to adding
    should not produce a notification every time the panel restarts.
    """
    if filesystems is None:
        filesystems = enumerate_filesystems()

    found = []
    gb = 1024 ** 3

    # 1. Mounted, in use, and absent from /etc/fstab: it disappears on the next
    #    reboot, taking whatever was written to it out of the panel's reach.
    for entry in filesystems:
        if entry.get('in_fstab') is False and entry.get('is_data_volume'):
            found.append({
                'key': f'fstab_missing:{entry["mountpoint"]}',
                'severity': 'warning',
                'mountpoint': entry['mountpoint'],
                'summary': (
                    f'{entry["mountpoint"]} ({entry["device"]}) is mounted but has no '
                    f'/etc/fstab entry — it will not come back after a reboot.'
                ),
            })

    # 2. Somewhere is short while a data volume has room to spare. This is the
    #    sentence that turns "disk full" into a next step.
    low = [f for f in filesystems
           if f.get('free') is not None and f['free'] < LOW_FREE_GB * gb]
    spare_volumes = [f for f in filesystems
                     if f.get('is_data_volume')
                     and f.get('free') is not None
                     and f['free'] >= SPARE_VOLUME_MIN_FREE_GB * gb]

    for short in low:
        for spare in spare_volumes:
            if spare['mountpoint'] == short['mountpoint']:
                continue
            found.append({
                'key': f'spare_volume:{short["mountpoint"]}:{spare["mountpoint"]}',
                'severity': 'warning',
                'mountpoint': short['mountpoint'],
                'summary': (
                    f'{short["mountpoint"]} has only {_format_bytes(short["free"])} free '
                    f'while {spare["mountpoint"]} has {_format_bytes(spare["free"])} '
                    f'spare. Consider relocating Docker data or backups onto it.'
                ),
            })

    # 3. Plain low space, reported once per filesystem regardless of #2.
    for short in low:
        found.append({
            'key': f'low_space:{short["mountpoint"]}',
            'severity': 'warning',
            'mountpoint': short['mountpoint'],
            'summary': (
                f'{short["mountpoint"]} is at {short.get("percent")}% — '
                f'{_format_bytes(short["free"])} free.'
            ),
        })

    return found
