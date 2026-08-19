"""Per-app managed volumes — first-class, tracked persistent storage.

Wraps the raw ``docker volume`` plumbing in ``DockerService`` and links each
volume to an ``Application`` so it survives redeploys, is visible in the UI, and
is backup-addressable. The real Docker volume is namespaced
``serverkit-app-{app_id}-{slug}``.

Two mount surfaces are supported:
  - single-container deploys — :meth:`run_args` returns the ``-v`` specs the
    ``docker run`` (``DockerService.run_container``) appends;
  - compose stacks — :meth:`compose_fragment` returns the service-level specs +
    the top-level ``volumes:`` declaration a generated stack needs.

Safety: :meth:`delete` only removes the underlying Docker volume when
``wipe=True`` **and** nothing is running off it, so a detach never nukes data by
accident.
"""
import logging
import os
import re

from app import db
from app.models.app_volume import AppVolume
from app.services.docker_service import DockerService
from app.utils.system import run_checked

logger = logging.getLogger(__name__)


class VolumeError(Exception):
    """Raised for invalid volume operations (bad mount path, duplicate, unsafe wipe)."""


class VolumeService:
    """CRUD + docker orchestration for per-app managed volumes."""

    # A throwaway image for size measurement / data copies. Small + ubiquitous.
    HELPER_IMAGE = 'alpine'

    # ── helpers ──
    @staticmethod
    def _slug(name):
        slug = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-')
        return slug or 'data'

    @classmethod
    def _unique_docker_name(cls, app_id, name):
        """``serverkit-app-{id}-{slug}``, suffixed if that collides with an
        existing managed volume name (two labels can slugify the same)."""
        base = f'serverkit-app-{app_id}-{cls._slug(name)}'
        candidate = base
        n = 2
        while AppVolume.query.filter_by(docker_volume_name=candidate).first() is not None:
            candidate = f'{base}-{n}'
            n += 1
        return candidate

    @staticmethod
    def _normalize_mount_path(mount_path):
        mount_path = (mount_path or '').strip()
        if not mount_path.startswith('/'):
            raise VolumeError('mount_path must be an absolute container path (e.g. /var/www/html/uploads)')
        # Normalize trailing slash (but keep root '/')
        return mount_path.rstrip('/') or '/'

    # ── CRUD ──
    @classmethod
    def get(cls, volume_id):
        if not volume_id:
            return None
        return AppVolume.query.get(volume_id)

    @classmethod
    def list_for_app(cls, app, with_live=True):
        """DB rows for an app, each optionally joined with live Docker state
        (present / mountpoint)."""
        rows = (AppVolume.query
                .filter_by(application_id=app.id)
                .order_by(AppVolume.created_at.asc())
                .all())
        if not with_live:
            return [(v, None) for v in rows]
        return [(v, DockerService.inspect_volume(v.docker_volume_name)) for v in rows]

    @classmethod
    def create(cls, app, name, mount_path, driver='local', read_only=False):
        """Create the namespaced Docker volume and persist the tracking row.
        Refuses a duplicate mount path for the same app."""
        name = (name or '').strip()
        if not name:
            raise VolumeError('name is required')
        mount_path = cls._normalize_mount_path(mount_path)

        existing = AppVolume.query.filter_by(application_id=app.id, mount_path=mount_path).first()
        if existing is not None:
            raise VolumeError(f'A volume is already mounted at {mount_path}')

        docker_volume_name = cls._unique_docker_name(app.id, name)
        result = DockerService.create_volume(docker_volume_name, driver=driver)
        if not result.get('success'):
            raise VolumeError(result.get('error') or 'Failed to create Docker volume')

        volume = AppVolume(
            application_id=app.id,
            name=name,
            docker_volume_name=docker_volume_name,
            mount_path=mount_path,
            driver=driver or 'local',
            read_only=bool(read_only),
        )
        db.session.add(volume)
        db.session.commit()
        return volume

    @classmethod
    def delete(cls, volume, wipe=False):
        """Detach a volume. Removes only the tracking row by default; with
        ``wipe=True`` also ``docker volume rm`` — but never while a container is
        running off it (loud refusal), so a detach can't destroy live data."""
        if wipe:
            app = volume.application
            if app is not None and app.status == 'running':
                raise VolumeError('Stop the app before wiping a volume')
            running = DockerService.containers_using_volume(volume.docker_volume_name, running_only=True)
            if running:
                raise VolumeError(f'Volume is in use by a running container ({", ".join(running)}); stop it first')
            rm = DockerService.remove_volume(volume.docker_volume_name)
            if not rm.get('success'):
                raise VolumeError(rm.get('error') or 'Failed to remove Docker volume')

        db.session.delete(volume)
        db.session.commit()

    @classmethod
    def measure(cls, volume):
        """Best-effort ``du -sb`` of the volume via a throwaway container. Linux
        only; returns the size in bytes (and caches it) or None."""
        if os.name != 'posix':
            return None
        try:
            result = run_checked(
                ['docker', 'run', '--rm', '-v', f'{volume.docker_volume_name}:/data:ro',
                 cls.HELPER_IMAGE, 'du', '-sb', '/data'],
                timeout=120)
            if result['success'] and result['output'].strip():
                size = int(result['output'].split()[0])
                volume.size_bytes = size
                db.session.commit()
                return size
        except Exception as e:  # pragma: no cover - best-effort/defensive
            logger.debug('Volume measure failed for %s: %s', volume.docker_volume_name, e)
        return None

    @classmethod
    def convert_bind_mount(cls, app, host_path, mount_path, name=None):
        """Guided migration: create a managed volume and copy an existing host
        directory's contents into it (so a fragile relative bind mount becomes a
        tracked named volume). Returns the new AppVolume. The stack still has to
        be pointed at the volume — the caller/UI handles that explicitly rather
        than rewriting a live compose file silently."""
        mount_path = cls._normalize_mount_path(mount_path)
        volume = cls.create(app, name or os.path.basename(mount_path.rstrip('/')) or 'data', mount_path)

        host_path = os.path.abspath(host_path or '')
        if host_path and os.path.isdir(host_path) and os.name == 'posix':
            try:
                run_checked(
                    ['docker', 'run', '--rm',
                     '-v', f'{host_path}:/src:ro',
                     '-v', f'{volume.docker_volume_name}:/dst',
                     cls.HELPER_IMAGE, 'sh', '-c', 'cp -a /src/. /dst/'],
                    timeout=600)
            except Exception as e:  # pragma: no cover - best-effort/defensive
                logger.warning('Bind-mount data copy failed for %s: %s', volume.docker_volume_name, e)
        return volume

    # ── mount wiring ──
    @classmethod
    def run_args(cls, app):
        """``-v`` specs for a single-container ``docker run`` (list of strings)."""
        return [v.mount_spec() for v in AppVolume.query.filter_by(application_id=app.id).all()]

    @classmethod
    def compose_fragment(cls, app):
        """Compose pieces for an app's managed volumes:
        ``{'service': [<name:/mount[:ro]>, …], 'top_level': {<name>: {}, …}}``.
        A generated stack references ``service`` from the service and declares
        ``top_level`` at the compose root."""
        rows = AppVolume.query.filter_by(application_id=app.id).all()
        return {
            'service': [v.mount_spec() for v in rows],
            'top_level': {v.docker_volume_name: {} for v in rows},
        }

    @classmethod
    def host_path_for_mount(cls, app, mount_path):
        """Live host mountpoint for the app's volume at ``mount_path`` (or None).

        Used to route a manifest disk's backup at the real bytes rather than the
        in-container path (plan 35)."""
        if app is None:
            return None
        vol = AppVolume.query.filter_by(
            application_id=app.id, mount_path=mount_path).first()
        if not vol:
            return None
        live = DockerService.inspect_volume(vol.docker_volume_name)
        if live.get('present') and live.get('mountpoint'):
            return live['mountpoint']
        return None

    @classmethod
    def host_paths_for_app(cls, app):
        """Live host mountpoints of an app's managed volumes, for backup
        addressability. Skips volumes not currently present on the host."""
        paths = []
        for volume in AppVolume.query.filter_by(application_id=app.id).all():
            live = DockerService.inspect_volume(volume.docker_volume_name)
            if live.get('present') and live.get('mountpoint'):
                paths.append(live['mountpoint'])
        return paths
