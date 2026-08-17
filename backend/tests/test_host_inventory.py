"""Host inventory and spec-change detection (plan 74).

The bug this pins down: an operator resized a droplet from 1 vCPU / 1 GB to
4 vCPU / 8 GB, attached a 60 GB volume, and the panel never mentioned any of it.
Not because it read stale numbers — a resize forces a power-off, so the process
and its in-memory cache die and the next boot reads the truth — but because
nothing ever persisted the *previous* numbers to compare against.

So the rules worth holding: the baseline survives a reboot, the first capture
does not invent a change, an unchanged reboot stays quiet, and an advisory
already reported does not nag again. Plus the two capacity services must answer
"which disk?" identically, which they did not.
"""

import json

import pytest

from app import db
from app.models.host_snapshot import HostSnapshot
from app.services import capacity_service, host_inventory_service, host_snapshot_service

GB = 1024 ** 3


def _fs(mountpoint, device, total, free, in_fstab=True, is_data_volume=False,
        fstype='ext4'):
    used = total - free
    return {
        'device': device,
        'mountpoint': mountpoint,
        'fstype': fstype,
        'total': total,
        'used': used,
        'free': free,
        'percent': round(used / total * 100, 1) if total else 0,
        'in_fstab': in_fstab,
        'is_data_volume': is_data_volume,
    }


def _capture(cpu=1, ram=1 * GB, swap=0, filesystems=None, boot='boot-a'):
    return {
        'boot_id': boot,
        'cpu_cores': cpu,
        'ram_bytes': ram,
        'swap_bytes': swap,
        'container': None,
        'filesystems': filesystems if filesystems is not None else [
            _fs('/', '/dev/vda1', 25 * GB, 20 * GB),
        ],
    }


@pytest.fixture(autouse=True)
def _clean_snapshots(app):
    HostSnapshot.query.delete()
    db.session.commit()
    yield
    HostSnapshot.query.delete()
    db.session.commit()


@pytest.fixture
def sent(monkeypatch):
    """Capture notification-bus sends instead of delivering them."""
    events = []

    class _Bus:
        @classmethod
        def send(cls, event, to=None, data=None, **kwargs):
            events.append({'event': event, 'to': to, 'data': data or {}})
            return {'notification_id': len(events), 'deliveries': []}

    import app.notifications.service as bus_module
    monkeypatch.setattr(bus_module, 'NotificationBusService', _Bus)
    return events


def _stub_capture(monkeypatch, capture):
    monkeypatch.setattr(host_inventory_service, 'capture', lambda: capture)


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #

def test_first_capture_records_no_changes(monkeypatch, sent):
    """No baseline is not the same as "compared and found nothing"."""
    _stub_capture(monkeypatch, _capture())

    snapshot = host_snapshot_service.record_snapshot()

    # None, not [] — and nothing to announce.
    assert snapshot.get_changes() is None
    assert HostSnapshot.query.count() == 1
    assert [e['event'] for e in sent] == []


def test_resize_across_reboot_is_detected_and_notified(monkeypatch, sent):
    """The actual bug: 1 vCPU/1 GB -> 4 vCPU/8 GB must produce a delta."""
    _stub_capture(monkeypatch, _capture(cpu=1, ram=1 * GB, boot='boot-a'))
    host_snapshot_service.record_snapshot()
    sent.clear()

    _stub_capture(monkeypatch, _capture(cpu=4, ram=8 * GB, boot='boot-b'))
    snapshot = host_snapshot_service.record_snapshot()

    changes = snapshot.get_changes()
    summaries = ' | '.join(c['summary'] for c in changes)
    assert 'CPU cores 1 → 4' in summaries
    assert any(c['field'] == 'ram_bytes' and c['kind'] == 'increased' for c in changes)

    events = [e for e in sent if e['event'] == 'host.specs_changed']
    assert len(events) == 1
    # boot_id moved, so this was a change made while the box was powered off.
    assert events[0]['data']['boot_changed'] is True


def test_unchanged_reboot_is_silent(monkeypatch, sent):
    """A restart that changed nothing must not notify."""
    _stub_capture(monkeypatch, _capture(boot='boot-a'))
    host_snapshot_service.record_snapshot()
    sent.clear()

    _stub_capture(monkeypatch, _capture(boot='boot-b'))
    snapshot = host_snapshot_service.record_snapshot()

    assert snapshot.get_changes() == []
    assert [e['event'] for e in sent] == []


def test_failed_probe_is_not_reported_as_a_loss(monkeypatch, sent):
    """psutil returning None must not read as "the RAM went away"."""
    _stub_capture(monkeypatch, _capture(ram=8 * GB))
    host_snapshot_service.record_snapshot()
    sent.clear()

    _stub_capture(monkeypatch, _capture(ram=None))
    snapshot = host_snapshot_service.record_snapshot()

    assert not any(c['field'] == 'ram_bytes' for c in snapshot.get_changes())
    assert [e['event'] for e in sent] == []


def test_new_volume_appears_as_a_change(monkeypatch, sent):
    _stub_capture(monkeypatch, _capture())
    host_snapshot_service.record_snapshot()
    sent.clear()

    _stub_capture(monkeypatch, _capture(filesystems=[
        _fs('/', '/dev/vda1', 25 * GB, 20 * GB),
        _fs('/mnt/vol', '/dev/sda', 60 * GB, 57 * GB, is_data_volume=True),
    ]))
    snapshot = host_snapshot_service.record_snapshot()

    mounted = [c for c in snapshot.get_changes() if c['kind'] == 'mounted']
    assert len(mounted) == 1
    assert mounted[0]['to'] == '/mnt/vol'


def test_total_size_jitter_below_the_noise_floor_is_ignored(monkeypatch):
    """A few blocks' drift across a remount is not a resize."""
    before = _capture(filesystems=[_fs('/', '/dev/vda1', 25 * GB, 20 * GB)])
    after = _capture(filesystems=[_fs('/', '/dev/vda1', 25 * GB + 1024 ** 2, 20 * GB)])

    assert host_inventory_service.diff(before, after) == []


# --------------------------------------------------------------------------- #
# fstab detection
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('spec_line', [
    '/dev/sda /mnt/vol ext4 defaults 0 2',              # by device
    'UUID=abc-123 /mnt/vol ext4 defaults 0 2',          # by UUID
    'LABEL=data /mnt/vol ext4 defaults 0 2',            # by label
    '/dev/disk/by-id/scsi-x /mnt/vol ext4 defaults 0 2',  # by mountpoint only
])
def test_fstab_entry_recognised_in_every_spelling(monkeypatch, tmp_path, spec_line):
    """A mount can be named four ways; matching one produces false warnings.

    DigitalOcean's Ubuntu image writes root as ``LABEL=cloudimg-rootfs``, so a
    device-only check flags ``/`` itself as unpersisted.
    """
    fstab = tmp_path / 'fstab'
    fstab.write_text(spec_line + '\n')

    real_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == '/etc/fstab':
            return real_open(fstab, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr('builtins.open', fake_open)

    specs, mounts = host_inventory_service._fstab_entries()
    assert specs is not None
    assert '/mnt/vol' in mounts


def test_unreadable_fstab_yields_unknown_not_false(monkeypatch):
    """No /etc/fstab (Windows dev box) must not render as "will vanish"."""
    def boom(path, *args, **kwargs):
        raise FileNotFoundError(path)

    monkeypatch.setattr('builtins.open', boom)
    specs, mounts = host_inventory_service._fstab_entries()
    assert specs is None and mounts is None


# --------------------------------------------------------------------------- #
# Enumeration
# --------------------------------------------------------------------------- #

class _Part:
    def __init__(self, device, mountpoint, fstype='ext4', opts='rw,relatime'):
        self.device = device
        self.mountpoint = mountpoint
        self.fstype = fstype
        self.opts = opts


def _stub_partitions(monkeypatch, parts, usage_free=10 * GB):
    monkeypatch.setattr(host_inventory_service.psutil, 'disk_partitions',
                        lambda all=False: parts)

    class _Usage:
        total, used, free, percent = 100 * GB, 90 * GB, usage_free, 90.0

    monkeypatch.setattr(host_inventory_service.psutil, 'disk_usage',
                        lambda path: _Usage())
    monkeypatch.setattr(host_inventory_service, '_fstab_entries',
                        lambda: ({'/dev/sdc'}, {'/'}))


def test_one_device_mounted_many_times_is_counted_once(monkeypatch):
    """Bind mounts and subvolumes are one disk, not several.

    Found by running the real probe: a dev box reported one 936 GB disk as six
    separate filesystems, which would have invented storage that isn't there.
    """
    _stub_partitions(monkeypatch, [
        _Part('/dev/sdc', '/'),
        _Part('/dev/sdc', '/home/user/bind-a'),
        _Part('/dev/sdc', '/home/user/bind-b'),
        _Part('/dev/sda', '/mnt/vol'),
    ])

    filesystems = host_inventory_service.enumerate_filesystems()

    assert [f['mountpoint'] for f in filesystems] == ['/', '/mnt/vol']


def test_read_only_media_is_not_storage(monkeypatch):
    """A read-only loop mount raised a bogus "missing from fstab" warning."""
    _stub_partitions(monkeypatch, [
        _Part('/dev/sdc', '/'),
        _Part('/dev/loop0', '/mnt/cli-tools', fstype='iso9660', opts='ro'),
        _Part('/dev/loop1', '/mnt/readonly', opts='ro,relatime'),
    ])

    filesystems = host_inventory_service.enumerate_filesystems()

    assert [f['mountpoint'] for f in filesystems] == ['/']


def test_the_root_device_is_never_a_data_volume(monkeypatch):
    _stub_partitions(monkeypatch, [
        _Part('/dev/sdc', '/'),
        _Part('/dev/sda', '/mnt/vol'),
    ])

    by_mount = {f['mountpoint']: f for f in host_inventory_service.enumerate_filesystems()}

    assert by_mount['/']['is_data_volume'] is False
    assert by_mount['/mnt/vol']['is_data_volume'] is True


# --------------------------------------------------------------------------- #
# Advisories
# --------------------------------------------------------------------------- #

def test_mounted_but_not_in_fstab_raises_an_advisory():
    found = host_inventory_service.advisories([
        _fs('/', '/dev/vda1', 25 * GB, 20 * GB),
        _fs('/mnt/vol', '/dev/sda', 60 * GB, 57 * GB,
            in_fstab=False, is_data_volume=True),
    ])
    keys = [a['key'] for a in found]
    assert 'fstab_missing:/mnt/vol' in keys


def test_unknown_fstab_state_does_not_raise_an_advisory():
    """in_fstab=None means we could not read it — not that it is missing."""
    found = host_inventory_service.advisories([
        _fs('/mnt/vol', '/dev/sda', 60 * GB, 57 * GB,
            in_fstab=None, is_data_volume=True),
    ])
    assert not any(a['key'].startswith('fstab_missing') for a in found)


def test_spare_volume_beside_a_full_disk_is_correlated():
    """The sentence that turns "disk full" into a next step.

    Mirrors the box that prompted this: / at 1 GiB free with a 60 GB volume
    attached and essentially untouched.
    """
    found = host_inventory_service.advisories([
        _fs('/', '/dev/vda1', 25 * GB, 1 * GB),
        _fs('/mnt/vol', '/dev/sda', 60 * GB, 59 * GB, is_data_volume=True),
    ])
    spare = [a for a in found if a['key'].startswith('spare_volume:')]
    assert len(spare) == 1
    assert '/mnt/vol' in spare[0]['summary']
    assert spare[0]['mountpoint'] == '/'


def test_a_volume_in_use_still_counts_as_somewhere_to_relocate():
    """Spare room is the signal, not emptiness — 20 GB used, 40 GB free."""
    found = host_inventory_service.advisories([
        _fs('/', '/dev/vda1', 25 * GB, 1 * GB),
        _fs('/mnt/vol', '/dev/sda', 60 * GB, 40 * GB, is_data_volume=True),
    ])
    assert any(a['key'].startswith('spare_volume:') for a in found)


def test_healthy_host_raises_nothing():
    found = host_inventory_service.advisories([
        _fs('/', '/dev/vda1', 25 * GB, 20 * GB),
    ])
    assert found == []


def test_advisory_already_reported_does_not_notify_again(monkeypatch, sent):
    """An fstab entry nobody has fixed must not nag on every restart."""
    filesystems = [
        _fs('/', '/dev/vda1', 25 * GB, 20 * GB),
        _fs('/mnt/vol', '/dev/sda', 60 * GB, 57 * GB,
            in_fstab=False, is_data_volume=True),
    ]
    _stub_capture(monkeypatch, _capture(filesystems=filesystems))

    host_snapshot_service.record_snapshot()
    first = [e for e in sent if e['event'] == 'host.storage_advisory']
    assert len(first) == 1

    sent.clear()
    host_snapshot_service.record_snapshot()   # same state, next boot
    assert [e for e in sent if e['event'] == 'host.storage_advisory'] == []


# --------------------------------------------------------------------------- #
# The divergence this plan repaired
# --------------------------------------------------------------------------- #

def test_capacity_and_tier_measure_the_same_filesystem():
    """Two services used to answer "which disk?" privately, and disagree."""
    from app.services.resource_tier_service import ResourceTierService

    assert ResourceTierService._data_path() == host_inventory_service.data_path()


def test_local_headroom_reports_which_filesystem_it_measured():
    """An unlabelled free-space number is how the two managed to diverge."""
    headroom = capacity_service.server_headroom(None)

    assert 'disk_mountpoint' in headroom


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #

def test_snapshots_are_pruned_to_the_retention_limit(monkeypatch, sent):
    _stub_capture(monkeypatch, _capture())
    monkeypatch.setattr(host_snapshot_service, 'RETAIN_SNAPSHOTS', 3)

    for _ in range(6):
        host_snapshot_service.record_snapshot()

    assert HostSnapshot.query.count() == 3


def test_snapshot_round_trips_through_json_columns(monkeypatch, sent):
    filesystems = [_fs('/mnt/vol', '/dev/sda', 60 * GB, 57 * GB, is_data_volume=True)]
    _stub_capture(monkeypatch, _capture(filesystems=filesystems))

    snapshot = host_snapshot_service.record_snapshot()
    db.session.expire(snapshot)

    stored = HostSnapshot.query.get(snapshot.id)
    assert stored.get_filesystems()[0]['mountpoint'] == '/mnt/vol'
    assert json.loads(stored.filesystems_json)[0]['device'] == '/dev/sda'
