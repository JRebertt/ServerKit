"""Will this actually fit? — capacity preflight for installs.

Deploying a template checked three things: the name is free, the target server
exists, and the directory isn't taken. Nothing asked whether the box could
carry the thing, so a 2 GB app landed on a 1 GB VPS at full speed and the first
sign of trouble was the OOM killer.

Templates already describe what they cost (``requirements: memory / storage``),
the panel already knows what each server has (``Server.total_memory`` /
``total_disk``) and what it is currently using (the latest ``ServerMetrics``
sample). This service is the join, and it answers in the shape a person asks
the question: *does it fit, will it be tight, or can't we tell?*

Deliberately advisory. It reports; it never refuses. An estimate is an estimate
— real usage depends on configuration and traffic — so the operator keeps the
final say, and "tight" is a sentence to read, not a wall to argue with. The
only honest failure mode is ``unknown``: with no recent sample we say so rather
than guessing, because a confident wrong answer is worse than no answer.
"""

import logging
import os
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Leave this much of the box unspoken-for after the install, or call it tight.
# A fraction alone is wrong at both ends (10% of 1 GB is nothing; 10% of 64 GB
# is more than most apps need), so each is a floor-and-fraction pair.
MEMORY_RESERVE_FRACTION = 0.10
MEMORY_RESERVE_MIN = 256 * 1024 ** 2      # 256 MB
DISK_RESERVE_FRACTION = 0.10
DISK_RESERVE_MIN = 2 * 1024 ** 3          # 2 GB

#: A sample older than this describes a server we no longer know. Still shown,
#: but flagged — the numbers may predate whatever else was deployed since.
STALE_AFTER = timedelta(minutes=15)

#: Worst-first, so the overall verdict is the most severe of the per-resource
#: ones. `unknown` outranks `ok`: not knowing is not the same as being fine.
SEVERITY = ('insufficient', 'tight', 'unknown', 'ok')

_SIZE_RE = re.compile(r'^\s*([\d.]+)\s*([kmgt]?)i?b?\s*$', re.I)
_UNIT_BYTES = {'': 1, 'k': 1024, 'm': 1024 ** 2, 'g': 1024 ** 3, 't': 1024 ** 4}


def parse_size(value):
    """``'512MB'`` / ``'2 GB'`` / ``1073741824`` -> bytes, or None if unusable.

    Catalog authors write these by hand, so the parser is forgiving about case,
    spacing and the ``i``/``B`` suffixes — and returns None rather than raising
    on anything it doesn't recognise, since a malformed estimate should degrade
    to "unknown", not break the install dialog.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    match = _SIZE_RE.match(str(value))
    if not match:
        return None
    amount, unit = match.groups()
    try:
        return int(float(amount) * _UNIT_BYTES[unit.lower()])
    except (ValueError, KeyError):
        return None


# Re-exported so existing `from app.services.capacity_service import format_size`
# callers keep working; the implementation moved to the leaf utils module when
# host_inventory_service turned out to hold a byte-for-byte copy (plan 75 §F1).
from app.utils.formatting import format_size  # noqa: E402,F401


def template_footprint(template):
    """What a template says it costs, in bytes.

    Returns ``{'memory': int|None, 'disk': int|None, 'declared': {...}}``.
    Both keys are None for a template that declares nothing — about half the
    catalog today — which surfaces as an honest "unknown" rather than a zero.
    """
    requirements = (template or {}).get('requirements') or {}
    if not isinstance(requirements, dict):
        return {'memory': None, 'disk': None, 'declared': {}}
    # `storage` is the catalog's word for it; `disk` accepted for authors who
    # reach for the more obvious one.
    disk_raw = requirements.get('storage', requirements.get('disk'))
    return {
        'memory': parse_size(requirements.get('memory')),
        'disk': parse_size(disk_raw),
        'declared': {k: v for k, v in requirements.items() if v is not None},
    }


def server_headroom(server_id=None):
    """What the target has spare right now.

    ``server_id=None`` means the panel's own host. Remote servers are read from
    their newest metrics sample; the totals come from the server row, which the
    agent fills in on connect.
    """
    if not server_id or server_id == 'local':
        return _local_headroom()
    return _remote_headroom(server_id)


def check_fit(template, server_id=None):
    """Does *template* fit on *server_id*? Advisory — see the module docstring.

    Returns a dict the install dialog can render as-is: an overall ``verdict``,
    a one-line ``headline`` and ``detail``, and a per-resource breakdown so the
    UI can show which of memory/disk is the problem.
    """
    footprint = template_footprint(template)
    headroom = server_headroom(server_id)

    checks = [
        _check_resource('memory', footprint['memory'], headroom.get('memory_free'),
                        headroom.get('memory_total'),
                        MEMORY_RESERVE_FRACTION, MEMORY_RESERVE_MIN),
        _check_resource('disk', footprint['disk'], headroom.get('disk_free'),
                        headroom.get('disk_total'),
                        DISK_RESERVE_FRACTION, DISK_RESERVE_MIN),
    ]
    _apply_other_mounts(checks, headroom)

    verdict = _worst(check['verdict'] for check in checks)
    return {
        'verdict': verdict,
        'headline': _headline(verdict, headroom, checks),
        'detail': _detail(verdict, checks, footprint, headroom),
        'blocking': False,          # never; the operator decides
        'requirements': footprint,
        'server': headroom,
        'checks': checks,
    }


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _check_resource(name, need, free, total, reserve_fraction, reserve_min):
    """One resource's verdict, with the arithmetic left visible for the UI."""
    check = {'resource': name, 'need': need, 'free': free, 'total': total,
             'after': None, 'reserve': None, 'verdict': 'unknown'}
    if need is None or free is None:
        # Either the template never said, or we have no sample. Both are
        # "we don't know", and the caller is told which by the fields.
        return check

    reserve = max(reserve_min, int((total or 0) * reserve_fraction))
    after = free - need
    check['after'] = after
    check['reserve'] = reserve

    if after < 0:
        check['verdict'] = 'insufficient'
    elif after < reserve:
        check['verdict'] = 'tight'
    else:
        check['verdict'] = 'ok'
    return check


def _apply_other_mounts(checks, headroom):
    """An attached volume can rescue a disk shortfall — say so, don't cry wolf.

    ``disk_free`` measures ONE filesystem (the data path). A box with a volume
    attached has more room than that number admits, and telling its operator
    "this server doesn't have room" is then simply wrong — the app's data can
    live on the volume. When the shortfall is on disk and another writable
    filesystem could hold the whole footprint, downgrade to "tight" and name
    the volume. Memory has no equivalent escape hatch.
    """
    disk = next((c for c in checks if c['resource'] == 'disk'), None)
    if disk is None or disk['verdict'] != 'insufficient':
        return
    candidates = [m for m in (headroom.get('other_mounts') or [])
                  if (m.get('free') or 0) >= disk['need']]
    if not candidates:
        return
    best = max(candidates, key=lambda m: m['free'])
    disk['verdict'] = 'tight'
    disk['alt_mountpoint'] = best['mountpoint']
    disk['alt_free'] = best['free']


def _worst(verdicts):
    seen = set(verdicts)
    for level in SEVERITY:
        if level in seen:
            return level
    return 'unknown'


def _headline(verdict, headroom, checks=()):
    if verdict == 'insufficient':
        return "This server doesn't have room for it"
    if verdict == 'tight':
        if any(c.get('alt_mountpoint') for c in checks):
            return 'It fits, if its data lives on the attached volume'
        return 'It fits, but this server will be tight'
    if verdict == 'ok':
        return 'Fits comfortably'
    if not headroom.get('measured_at'):
        return "No recent readings from this server — can't check the fit"
    return "This template doesn't publish what it needs — can't check the fit"


def _detail(verdict, checks, footprint, headroom):
    """The sentence under the headline: what it needs, against what's spare."""
    need_bits = [f'{format_size(c["need"])} {c["resource"]}'
                 for c in checks if c['need'] is not None]
    free_bits = [f'{format_size(c["free"])} {c["resource"]}'
                 for c in checks if c['free'] is not None]

    if not need_bits:
        return ('This template does not declare a memory or storage estimate, '
                'so there is nothing to compare against.')
    if not free_bits:
        return (f'Needs about {" and ".join(need_bits)}. '
                'No recent usage readings for this server, so its free space '
                'is unknown.')

    sentence = (f'Needs about {" and ".join(need_bits)}; '
                f'this server has {" and ".join(free_bits)} free.')

    short = [c for c in checks if c['verdict'] == 'insufficient']
    if short:
        names = ' and '.join(c['resource'] for c in short)
        sentence += f' That is more {names} than it has free.'
    else:
        # A check rescued by an attached volume explains itself; the generic
        # "would leave only" arithmetic is meaningless for it (negative).
        rescued = [c for c in checks if c.get('alt_mountpoint')]
        tight = [c for c in checks
                 if c['verdict'] == 'tight' and not c.get('alt_mountpoint')]
        if tight:
            leftovers = ' and '.join(
                f'{format_size(c["after"])} {c["resource"]}' for c in tight)
            sentence += f' Installing it would leave only {leftovers} spare.'
        for c in rescued:
            sentence += (f' The volume at {c["alt_mountpoint"]} has '
                         f'{format_size(c["alt_free"])} free — point the '
                         f"app's data there and it fits.")

    if headroom.get('stale'):
        sentence += ' These readings are more than 15 minutes old.'
    return sentence


def _local_headroom():
    """The panel's own host, read live — no sample to go stale."""
    result = {'server_id': None, 'name': 'This server', 'measured_at': None,
              'stale': False, 'source': 'local'}
    try:
        import psutil
    except ImportError:
        return result
    try:
        from app.services import host_inventory_service

        memory = psutil.virtual_memory()
        # Not hardcoded `/` any more: images, volumes and backups may live on an
        # attached volume, and measuring root would then answer a question
        # nobody asked. `mountpoint` records which filesystem this actually is,
        # so an unlabelled number can never be misread again (plan 74).
        mountpoint, disk = host_inventory_service.data_path_usage()
        result.update({
            'memory_total': memory.total,
            # `available`, not `free`: cache and buffers are reclaimable, and
            # counting them as used would call every healthy Linux box full.
            'memory_free': memory.available,
            'disk_total': disk.total if disk else None,
            'disk_free': disk.free if disk else None,
            'disk_mountpoint': mountpoint,
            'measured_at': datetime.utcnow().isoformat() + 'Z',
        })
    except Exception:  # noqa: BLE001 — a probe failure is "unknown", not fatal
        logger.warning('capacity: could not read local host usage', exc_info=True)
        return result
    try:
        # The other real filesystems on this box — an attached volume can hold
        # data the measured mountpoint can't, and the verdict must know that
        # before declaring "no room" (see _apply_other_mounts).
        measured = os.path.normpath(mountpoint) if mountpoint else None
        result['other_mounts'] = [
            {'mountpoint': fs['mountpoint'], 'free': fs['free'],
             'total': fs['total']}
            for fs in host_inventory_service.enumerate_filesystems()
            if os.path.normpath(fs['mountpoint']) != measured
        ]
    except Exception:  # noqa: BLE001 — no volumes known is just an empty list
        logger.debug('capacity: could not enumerate filesystems', exc_info=True)
    return result


def _remote_headroom(server_id):
    """A managed server, from its newest metrics sample."""
    from app.models.server import Server, ServerMetrics

    result = {'server_id': server_id, 'name': None, 'measured_at': None,
              'stale': False, 'source': 'agent'}
    server = Server.query.get(server_id)
    if not server:
        return result

    result['name'] = server.name
    result['memory_total'] = server.total_memory
    result['disk_total'] = server.total_disk

    sample = (ServerMetrics.query
              .filter_by(server_id=server_id)
              .order_by(ServerMetrics.timestamp.desc())
              .first())
    if not sample:
        return result

    if sample.timestamp:
        result['measured_at'] = sample.timestamp.isoformat() + 'Z'
        result['stale'] = (datetime.utcnow() - sample.timestamp) > STALE_AFTER

    if server.total_memory and sample.memory_used is not None:
        result['memory_free'] = max(0, server.total_memory - sample.memory_used)
    if sample.disk_used is not None:
        total_disk = server.total_disk or _implied_total(sample.disk_used,
                                                         sample.disk_percent)
        if total_disk:
            result['disk_total'] = total_disk
            result['disk_free'] = max(0, total_disk - sample.disk_used)
    return result


def _implied_total(used, percent):
    """Recover a total from used+percent when the server row never got one.

    Agents report the percentage even when the absolute total is missing from
    the row, and a disk check that silently does nothing is worse than one
    working off a derived figure.
    """
    try:
        if used and percent and percent > 0:
            return int(used / (float(percent) / 100.0))
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None
