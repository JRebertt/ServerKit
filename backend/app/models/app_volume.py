from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin


class AppVolume(TimestampMixin, db.Model):
    """A first-class, tracked persistent volume attached to an application.

    Replaces ad-hoc **relative bind mounts** (``./mysql-data:/var/lib/mysql``)
    with a **named Docker volume** that survives redeploys, is visible in the UI,
    and is backup-addressable. v1 is the ``local`` driver only; ``driver`` is
    modeled so networked drivers (NFS/CSI/cloud block) can grow later.

    The real Docker volume is namespaced ``serverkit-app-{app_id}-{slug}`` so it
    is unambiguously ServerKit-owned and never collides with a host admin's
    volumes.
    """

    __tablename__ = 'app_volumes'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer, db.ForeignKey('applications.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    name = db.Column(db.String(120), nullable=False)          # operator label, e.g. "uploads"
    docker_volume_name = db.Column(db.String(200), nullable=False, unique=True)
    mount_path = db.Column(db.String(500), nullable=False)    # absolute path inside the container
    driver = db.Column(db.String(40), nullable=False, default='local')
    read_only = db.Column(db.Boolean, nullable=False, default=False)
    size_bytes = db.Column(db.BigInteger, nullable=True)      # denormalized last-measured size
    declared_size = db.Column(db.String(40), nullable=True)   # operator/manifest-declared size cap, e.g. "10Gi" (plan 35)

    # Deleting the app removes its volume rows (ORM cascade); the underlying
    # Docker volumes are intentionally left on disk so an app delete never nukes
    # data silently — prune them explicitly with a wipe.
    application = db.relationship(
        'Application',
        backref=db.backref('volumes', cascade='all, delete-orphan'),
    )

    __table_args__ = (
        db.UniqueConstraint('application_id', 'mount_path', name='uq_app_volume_mount'),
    )

    def mount_spec(self):
        """The ``docker run -v`` / compose short-syntax spec for this volume,
        e.g. ``serverkit-app-5-uploads:/var/www/html/wp-content/uploads:ro``."""
        spec = f'{self.docker_volume_name}:{self.mount_path}'
        if self.read_only:
            spec += ':ro'
        return spec

    def to_dict(self, live=None):
        data = {
            'id': self.id,
            'application_id': self.application_id,
            'name': self.name,
            'docker_volume_name': self.docker_volume_name,
            'mount_path': self.mount_path,
            'driver': self.driver,
            'read_only': self.read_only,
            'size_bytes': self.size_bytes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if live is not None:
            data['present'] = live.get('present')
            data['mountpoint'] = live.get('mountpoint')
            if live.get('size_bytes') is not None:
                data['size_bytes'] = live.get('size_bytes')
        return data

    def __repr__(self):
        return f'<AppVolume {self.docker_volume_name} -> {self.mount_path}>'
