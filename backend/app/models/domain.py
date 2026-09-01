from datetime import datetime
from app import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class Domain(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = 'domains'

    id = db.Column(db.Integer, primary_key=True)
    # NOT unique=True any more. A deleted domain keeps its tombstone, and a
    # table-level UNIQUE would then refuse to let you re-add the same name --
    # deleting a domain would permanently burn it. Migration 083 replaces the
    # constraint with a PARTIAL unique index over rows where deleted_at IS NULL,
    # so live names stay unique and tombstones stay out of the way.
    name = db.Column(db.String(255), nullable=False, index=True)
    is_primary = db.Column(db.Boolean, default=False)

    # SSL
    ssl_enabled = db.Column(db.Boolean, default=False)
    ssl_certificate_path = db.Column(db.String(500), nullable=True)
    ssl_key_path = db.Column(db.String(500), nullable=True)
    ssl_expires_at = db.Column(db.DateTime, nullable=True)
    ssl_auto_renew = db.Column(db.Boolean, default=True)

    # Metadata

    # Foreign keys
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'is_primary': self.is_primary,
            'ssl_enabled': self.ssl_enabled,
            'ssl_expires_at': self.ssl_expires_at.isoformat() if self.ssl_expires_at else None,
            'ssl_auto_renew': self.ssl_auto_renew,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'application_id': self.application_id,
            **self.soft_delete_dict(),
        }

    def __repr__(self):
        return f'<Domain {self.name}>'
