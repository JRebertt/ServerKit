"""The panel host's own hardware, recorded so a change can be noticed.

Every other spec reader in the codebase answers "what is it now?" — psutil is
consulted live and the answer is thrown away. That is fine until the operator
resizes the box, at which point the panel reads the new numbers, has nothing to
compare them against, and says nothing.

The subtle part is that a resize requires a power-off, so the process (and any
in-memory cache) dies with it. The baseline has to outlive a reboot or it is
not a baseline, which is why this is a table and not a module-level dict.
"""
import json
from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class HostSnapshot(JsonColumnMixin, db.Model):
    """One reading of the panel host's specs and filesystems."""
    __tablename__ = 'host_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    captured_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # /proc/sys/kernel/random/boot_id — a fresh value every boot. Lets a change
    # that happened while the box was off (a resize) be told apart from one that
    # happened underneath a running panel (a volume attached hot).
    boot_id = db.Column(db.String(64), nullable=True, index=True)

    cpu_cores = db.Column(db.Integer, nullable=True)
    ram_bytes = db.Column(db.BigInteger, nullable=True)
    swap_bytes = db.Column(db.BigInteger, nullable=True)
    container = db.Column(db.String(32), nullable=True)  # lxc | openvz | docker | None

    # [{device, mountpoint, fstype, total, used, free, percent,
    #   in_fstab, is_data_volume}, ...]
    filesystems_json = db.Column(db.Text, nullable=True)

    # Deltas against the previous snapshot: [{field, kind, from, to, summary}].
    # NULL on the first ever capture — there was nothing to compare against,
    # which is different from "compared and found nothing".
    changes_json = db.Column(db.Text, nullable=True)

    # Advisories active at capture time, so the next capture can notify only on
    # a state transition instead of nagging every boot.
    advisories_json = db.Column(db.Text, nullable=True)

    def get_filesystems(self):
        return self._json_read('filesystems_json', [])

    def set_filesystems(self, value):
        self.filesystems_json = json.dumps(value) if value else None

    def get_changes(self):
        """Deltas vs the previous snapshot, or None if this is the first."""
        if self.changes_json is None:
            return None
        return self._json_read('changes_json', [])

    def set_changes(self, value):
        self.changes_json = json.dumps(value) if value is not None else None

    def get_advisories(self):
        return self._json_read('advisories_json', [])

    def set_advisories(self, value):
        self.advisories_json = json.dumps(value) if value else None

    def to_dict(self):
        return {
            'id': self.id,
            'captured_at': self.captured_at.isoformat() if self.captured_at else None,
            'boot_id': self.boot_id,
            'cpu_cores': self.cpu_cores,
            'ram_bytes': self.ram_bytes,
            'swap_bytes': self.swap_bytes,
            'container': self.container,
            'filesystems': self.get_filesystems(),
            'changes': self.get_changes(),
            'advisories': self.get_advisories(),
        }
