"""Persist a host reading, compare it to the last one, and speak up.

Split from ``host_inventory_service`` on purpose: that module is pure probing
and stays importable during early boot, before the database is ready. This one
owns the parts that need a session and the notification bus.

The notification is the whole point. The panel already *knew* it had four cores
the moment it booted; what it never did was tell anyone the number used to be
one.
"""
import logging

from app import db
from app.models.host_snapshot import HostSnapshot
from app.services import host_inventory_service

logger = logging.getLogger(__name__)

#: Snapshots are small and only written at boot, but an appliance that reboots
#: often should not accumulate them forever.
RETAIN_SNAPSHOTS = 50


def latest():
    """The most recent snapshot, or None on a panel that has never captured."""
    return (HostSnapshot.query
            .order_by(HostSnapshot.captured_at.desc(), HostSnapshot.id.desc())
            .first())


def _as_capture(snapshot):
    """A stored row in the shape :func:`host_inventory_service.diff` expects."""
    return {
        'cpu_cores': snapshot.cpu_cores,
        'ram_bytes': snapshot.ram_bytes,
        'swap_bytes': snapshot.swap_bytes,
        'container': snapshot.container,
        'filesystems': snapshot.get_filesystems(),
    }


def record_snapshot(notify=True):
    """Capture, diff against the previous row, persist, and notify on a change.

    Returns the new :class:`HostSnapshot`. Raises nothing the caller must
    handle — boot callers wrap it anyway, but a failure here must never be the
    reason a panel does not start.
    """
    current = host_inventory_service.capture()
    current_advisories = host_inventory_service.advisories(current['filesystems'])

    previous = latest()
    # None (not []) on the first ever capture: there was no baseline, which is a
    # different statement from "compared and found nothing".
    changes = None
    if previous is not None:
        changes = host_inventory_service.diff(_as_capture(previous), current)

    snapshot = HostSnapshot(
        boot_id=current.get('boot_id'),
        cpu_cores=current.get('cpu_cores'),
        ram_bytes=current.get('ram_bytes'),
        swap_bytes=current.get('swap_bytes'),
        container=current.get('container'),
    )
    snapshot.set_filesystems(current['filesystems'])
    snapshot.set_changes(changes)
    snapshot.set_advisories(current_advisories)
    db.session.add(snapshot)
    db.session.commit()

    if notify:
        try:
            _notify(previous, snapshot, changes or [], current_advisories)
        except Exception:  # noqa: BLE001 — a notification failure is not a capture failure
            logger.exception('Host snapshot recorded but notification failed')

    _prune()
    return snapshot


def _prune():
    """Drop all but the newest RETAIN_SNAPSHOTS rows."""
    try:
        stale = (HostSnapshot.query
                 .order_by(HostSnapshot.captured_at.desc(), HostSnapshot.id.desc())
                 .offset(RETAIN_SNAPSHOTS)
                 .all())
        if not stale:
            return
        for row in stale:
            db.session.delete(row)
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        logger.debug('Host snapshot prune skipped', exc_info=True)


def _notify(previous, snapshot, changes, current_advisories):
    from app.notifications.service import NotificationBusService

    if changes:
        summary = '; '.join(c['summary'] for c in changes)
        data = {
            'summary': summary,
            'count': len(changes),
            'changes': changes,
            'boot_changed': bool(
                previous is not None
                and previous.boot_id
                and snapshot.boot_id
                and previous.boot_id != snapshot.boot_id
            ),
        }
        data.update(_profile_advice(snapshot))
        NotificationBusService.send('host.specs_changed', to='admins', data=data)

    # Only transitions. An fstab entry nobody has got round to adding should
    # not produce a fresh notification on every restart.
    previous_keys = {a.get('key') for a in (previous.get_advisories() if previous else [])}
    fresh = [a for a in current_advisories if a.get('key') not in previous_keys]
    if fresh:
        NotificationBusService.send('host.storage_advisory', to='admins', data={
            'summary': ' '.join(a['summary'] for a in fresh),
            'count': len(fresh),
            'advisories': fresh,
        })


def _profile_advice(snapshot):
    """Whether the install profile still suits the hardware.

    Advice only. ``recommend_profile`` is re-run and reported; the profile is
    never silently rewritten, matching the "reports, never refuses" stance the
    capacity services already take.
    """
    try:
        from app.services import install_profile_service

        _, usage = host_inventory_service.data_path_usage()
        specs = {
            'ram_gb': round((snapshot.ram_bytes or 0) / (1024 ** 3), 2),
            'cpu_cores': snapshot.cpu_cores or 1,
            'disk_free_gb': round(usage.free / (1024 ** 3), 2) if usage else None,
            'container': snapshot.container,
        }
        current = install_profile_service.get_profile()
        recommended = install_profile_service.recommend_profile(specs)
        return {
            'profile': current,
            'recommended_profile': recommended,
            'profile_outdated': current != recommended,
        }
    except Exception:  # noqa: BLE001 — advice is optional; the delta is not
        logger.debug('Could not re-evaluate install profile', exc_info=True)
        return {}


def current_state():
    """Live inventory plus the stored delta — what the API and UI render."""
    filesystems = host_inventory_service.enumerate_filesystems()
    mountpoint, usage = host_inventory_service.data_path_usage()
    snapshot = latest()
    return {
        'filesystems': filesystems,
        'advisories': host_inventory_service.advisories(filesystems),
        'data_path': host_inventory_service.data_path(),
        'data_mountpoint': mountpoint,
        'data_free_bytes': usage.free if usage else None,
        'last_snapshot': snapshot.to_dict() if snapshot else None,
    }
