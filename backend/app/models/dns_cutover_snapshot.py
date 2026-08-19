"""Reversible DNS cutover snapshot model."""
from datetime import datetime

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class DnsCutoverSnapshot(JsonColumnMixin, db.Model):
    """A point-in-time capture of a domain's live DNS records, taken right before
    a migration cutover flips them to the new box (plan 27 Phase 6 #13, Decision 6).

    ServerKit's DNS activity ledger (:class:`~app.models.dns_change.DnsChange`)
    only records the *after* value of each write, so it cannot power a revert. A
    cutover therefore snapshots the domain's existing records
    (name / type / content / ttl) into this row *first*; the revert step then
    re-applies that snapshot to restore the old target.

    ``status`` walks ``captured`` -> ``cutover`` -> ``reverted``:

    * **captured** — records saved, nothing changed yet.
    * **cutover**  — the record(s) were repointed at the new box.
    * **reverted** — the snapshot was re-applied, restoring the pre-cutover state.
    * **reverted_with_deletions** — as *reverted*, plus records the cutover
      *created* (no predecessor in the snapshot) were deleted (plan 31 #3).
    """

    __tablename__ = 'dns_cutover_snapshots'

    STATUSES = ('captured', 'cutover', 'reverted', 'reverted_with_deletions')

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(256), nullable=False, index=True)
    provider = db.Column(db.String(64), nullable=True)
    provider_zone_id = db.Column(db.String(128), nullable=True)

    # JSON list of the records captured before cutover (the world to restore).
    records_json = db.Column(db.Text, nullable=True)
    # JSON list of records the cutover CREATED (no snapshot predecessor); revert
    # deletes these so the world is restored byte-for-byte (plan 31 #3).
    created_records_json = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(24), nullable=False, default='captured')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)
    applied_at = db.Column(db.DateTime, nullable=True)

    def get_records(self):
        return self._json_read('records_json', [], expect=list)

    def set_records(self, records):
        self._json_write('records_json', list(records or []), falsy='[]')

    def get_created_records(self):
        return self._json_read('created_records_json', [], expect=list)

    def set_created_records(self, records):
        self._json_write('created_records_json', list(records or []), falsy='[]')

    def to_dict(self):
        return {
            'id': self.id,
            'domain': self.domain,
            'provider': self.provider,
            'provider_zone_id': self.provider_zone_id,
            'status': self.status,
            'records': self.get_records(),
            'record_count': len(self.get_records()),
            'created_records': self.get_created_records(),
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'applied_at': self.applied_at.isoformat() + 'Z' if self.applied_at else None,
        }

    def __repr__(self):
        return f'<DnsCutoverSnapshot {self.domain} {self.status}>'
