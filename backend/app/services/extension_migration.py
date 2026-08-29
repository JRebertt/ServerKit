"""One-shot auto-install of converted builtin extensions (decision D3).

When a core page is converted into a builtin extension, an *upgraded* panel must
not lose the feature. On the first boot after such an upgrade we auto-install the
extension once, recording a per-slug marker so we never do it again — the user is
free to uninstall afterwards and it stays uninstalled.

Fresh installs are different: they never had the page as a core feature, so they
should discover the extension in the Marketplace rather than have it pre-installed
(flagships that ship installed-by-default per D4 are handled separately, not here).
We distinguish the two by whether any user exists yet — a brand-new panel has none
until the setup wizard creates the first admin.

The whole pass is best-effort: a failure to install (e.g. a Docker panel whose
frontend plugins dir isn't writable) is logged and retried on the next boot, and
never blocks startup. The builtin frontends are pre-bundled (D5) regardless, so
the marker only governs whether the contribution is switched on.
"""
import json
import logging
import os
import shutil

from app import db
from app.models.plugin import InstalledPlugin

logger = logging.getLogger(__name__)

# Builtin extensions that were previously shipped as core pages. Append a slug
# here when its page is converted; existing panels then auto-install it once.
CONVERTED_BUILTIN_SLUGS = [
    'serverkit-ftp',
    'serverkit-cloud-provision',
    'serverkit-remote-access',
    'serverkit-status',
]

# Extensions deliberately deleted from the product (replaced or retired) — the
# Workflow Builder was superseded by serverkit-tramo (plan 45). Their leftover
# copy-installed files must be swept from the live tree: update.sh's plugin
# carry-forward would otherwise preserve them into every fresh deploy, where
# their dead imports (workflows → reactflow) sink the bundle build. The updater
# has its own skip list (RETIRED_PLUGIN_SLUGS in scripts/update.sh); this sweep
# is the backstop for trees updated by an older/offline updater.
RETIRED_EXTENSION_SLUGS = [
    'serverkit-workflows',
]


def remove_retired_extensions():
    """Sweep files and DB rows of retired extensions. Idempotent, best-effort.

    Runs at boot BEFORE the plugin loader so a retired backend plugin is never
    loaded and the repair pass never tries to resurrect its row.
    """
    from app.services.plugin_service import (
        BACKEND_PLUGINS_DIR,
        FRONTEND_PLUGINS_DIR,
    )
    for slug in RETIRED_EXTENSION_SLUGS:
        for base in (BACKEND_PLUGINS_DIR, FRONTEND_PLUGINS_DIR):
            path = os.path.join(base, slug)
            if os.path.isdir(path):
                try:
                    shutil.rmtree(path)
                    logger.info(f'Removed retired extension files: {path}')
                except OSError as e:
                    logger.warning(f'Could not remove retired extension {path}: {e}')
        try:
            row = InstalledPlugin.query.filter_by(slug=slug).first()
            if row:
                db.session.delete(row)
                db.session.commit()
                logger.info(f'Removed retired extension row: {slug}')
        except Exception as e:  # noqa: BLE001
            logger.warning(f'Could not remove retired extension row {slug}: {e}')


def _email_was_configured():
    """True if this panel actually ran a mail server before the extraction — any
    email domain/account row exists. Used to gate serverkit-email auto-install so
    only mail users get it back automatically (#34); everyone else uses the
    Marketplace."""
    try:
        from app.models.email import EmailDomain, EmailAccount
        return (db.session.query(EmailDomain.id).first() is not None
                or db.session.query(EmailAccount.id).first() is not None)
    except Exception:
        return False


# Builtins auto-installed on upgrade ONLY when a usage predicate says the panel
# actually used the feature (D3/#34). Fresh installs and panels that never used
# the feature just see it in the Marketplace.
GATED_BUILTIN_SLUGS = {
    'serverkit-email': _email_was_configured,
}


def _has_command(cmd):
    def probe():
        try:
            from app.utils.system import is_command_available
            return is_command_available(cmd)
        except Exception:
            return False
    return probe


def _scanners_dir_populated():
    """True if grype/syft were ever installed by the panel's image scanner."""
    try:
        from app import paths
        scanners = os.path.join(paths.SERVERKIT_DATA_DIR, 'scanners')
        return os.path.isdir(scanners) and bool(os.listdir(scanners))
    except Exception:
        return False


# Security-suite extractions (plan 47 Ph3b-4 / plan 55 Phase 3). These left
# core for REGISTRY extensions — there is no builtin folder to copy, so
# upgrade parity means: when the host tool the old core surface managed is
# actually present, install the extension from the registry once. Fail-soft:
# an unreachable registry (or an entry not yet published) leaves the slug
# unmarked so the next boot retries; panels without the host tool just see
# the extension in the Marketplace.
REGISTRY_GATED_SLUGS = {
    'serverkit-fail2ban': _has_command('fail2ban-client'),
    'serverkit-clamav': _has_command('clamscan'),
    'serverkit-lynis': _has_command('lynis'),
    'serverkit-auto-updates': _has_command('unattended-upgrade'),
    'serverkit-image-scan': _scanners_dir_populated,
}

_MARKER_KEY = 'extensions.auto_installed_slugs'
# Slugs whose now-extracted backend has been re-acquired on an upgraded panel
# (plan 47 Phase 2). Separate from _MARKER_KEY so the one-shot backend pickup
# runs even for slugs already auto-installed frontend-only in a prior release.
_BACKEND_ACQUIRED_KEY = 'extensions.backend_acquired_slugs'


def _processed_slugs():
    from app.services.settings_service import SettingsService
    raw = SettingsService.get(_MARKER_KEY, '')
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except (ValueError, TypeError):
        # Tolerate a legacy comma-joined value.
        return {s.strip() for s in str(raw).split(',') if s.strip()}


def _save_processed(slugs):
    from app.services.settings_service import SettingsService
    SettingsService.set(_MARKER_KEY, json.dumps(sorted(slugs)))


def _looks_like_existing_install():
    """True if this panel has prior data (an upgrade), False if brand-new.

    A fresh install has no users yet — the setup wizard creates the first admin.
    """
    from app.models.user import User
    try:
        return db.session.query(User.id).first() is not None
    except Exception:
        return False


def run_auto_install():
    """Install converted builtins once on an upgraded panel. Idempotent."""
    processed = _processed_slugs()
    existing = _looks_like_existing_install()

    try:
        from app.services.plugin_service import (
            install_builtin_extension,
            list_builtin_extensions,
        )
        available = {e['slug'] for e in list_builtin_extensions()}
    except Exception as e:
        logger.warning(f'Extension auto-install skipped (builtins unavailable): {e}')
        return

    # Ungated converted builtins auto-install on any upgrade; gated ones only when
    # their usage predicate is true.
    candidates = [(s, None) for s in CONVERTED_BUILTIN_SLUGS]
    candidates += [(s, gate) for s, gate in GATED_BUILTIN_SLUGS.items()]

    changed = False
    for slug, gate in candidates:
        if slug in processed:
            continue

        # Not yet shipped as a builtin folder — skip quietly, revisit next boot.
        if slug not in available:
            continue

        if existing:
            # Upgrade path: keep the feature alive unless it's already present or
            # (for gated builtins) the panel never used it.
            wants_it = True
            if gate is not None:
                try:
                    wants_it = bool(gate())
                except Exception:
                    wants_it = False
            if wants_it and not InstalledPlugin.query.filter_by(slug=slug).first():
                try:
                    install_builtin_extension(slug)
                    logger.info(f'Auto-installed converted builtin extension: {slug}')
                except Exception as e:
                    logger.warning(
                        f'Auto-install of {slug} failed (retry next boot): {e}'
                    )
                    continue  # leave unmarked so we retry
        # Fresh install (marketplace-only), gate-false (marketplace-only), OR
        # successfully installed: record it so the one-shot never repeats.
        processed.add(slug)
        changed = True

    if changed:
        _save_processed(processed)


_REGISTRY_MARKER_KEY = 'extensions.registry_auto_installed_slugs'


def _registry_processed_slugs():
    from app.services.settings_service import SettingsService
    raw = SettingsService.get(_REGISTRY_MARKER_KEY, '')
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except (ValueError, TypeError):
        return set()


def run_registry_auto_install():
    """Upgrade parity for the extracted security suite. Idempotent, fail-soft.

    Only on an upgraded panel, only for slugs whose host-tool predicate is
    true, and only when the registry actually lists the slug (an unpublished
    or unreachable registry defers to the next boot instead of burning the
    one-shot). Fresh installs go through the wizard/Marketplace instead.
    """
    processed = _registry_processed_slugs()
    pending = {s: gate for s, gate in REGISTRY_GATED_SLUGS.items()
               if s not in processed}
    if not pending:
        return

    if not _looks_like_existing_install():
        # Fresh install: never auto-install, mark everything done once.
        _save_registry_processed(processed | set(pending))
        return

    from app.services import registry_service
    from app.services.plugin_service import install_registry_extension

    changed = False
    for slug, gate in pending.items():
        try:
            wants_it = bool(gate())
        except Exception:
            wants_it = False
        if not wants_it:
            processed.add(slug)
            changed = True
            continue
        if InstalledPlugin.query.filter_by(slug=slug).first():
            processed.add(slug)
            changed = True
            continue
        try:
            entry = registry_service.get_entry(slug)
        except Exception:
            entry = None
        if not entry:
            # Not published / registry unreachable — retry next boot.
            continue
        try:
            install_registry_extension(slug)
            logger.info(f'Auto-installed security extension from registry: {slug}')
            processed.add(slug)
            changed = True
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f'Registry auto-install of {slug} failed (retry next boot): {e}')

    if changed:
        _save_registry_processed(processed)


def _save_registry_processed(slugs):
    from app.services.settings_service import SettingsService
    SettingsService.set(_REGISTRY_MARKER_KEY, json.dumps(sorted(slugs)))


def _backend_acquired_slugs():
    from app.services.settings_service import SettingsService
    raw = SettingsService.get(_BACKEND_ACQUIRED_KEY, '')
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except (ValueError, TypeError):
        return {s.strip() for s in str(raw).split(',') if s.strip()}


def run_backend_acquisition():
    """Re-acquire the backend for converted builtins that gained one (plan 47).

    Some builtins (ftp, cloud-provision, remote-access, status) first shipped as
    *frontend-only* extensions whose API was still served by CORE. Plan 47 moves
    that backend into the extension and deregisters it from core. On an upgraded
    panel that already installed such an extension frontend-only, the installed
    row has ``has_backend=False`` and no backend on disk — so without this pass
    the API would simply vanish. For each converted slug that is installed but
    missing the now-available backend, force-reinstall from ``builtin-extensions/``
    once (idempotent via a marker). Best-effort; never blocks startup.
    """
    import os

    done = _backend_acquired_slugs()
    try:
        from app.services import plugin_service
        builtins = {e['slug']: e for e in plugin_service.list_builtin_extensions()}
    except Exception as e:
        logger.warning(f'Backend acquisition skipped (builtins unavailable): {e}')
        return

    changed = False
    for slug in CONVERTED_BUILTIN_SLUGS:
        if slug in done:
            continue
        entry = builtins.get(slug)
        # Only slugs that now actually ship a backend/ dir are candidates.
        if not entry or not os.path.isdir(os.path.join(entry['path'], 'backend')):
            continue
        row = InstalledPlugin.query.filter_by(slug=slug).first()
        if not row:
            # Not installed — run_auto_install handles fresh (re-)acquisition,
            # and a fresh panel discovers it in the Marketplace.
            continue
        backend_on_disk = os.path.isdir(
            os.path.join(plugin_service.BACKEND_PLUGINS_DIR, slug))
        if row.has_backend and backend_on_disk:
            done.add(slug)
            changed = True
            continue
        try:
            plugin_service.install_from_path(
                entry['path'], user_id=row.installed_by, force=True,
                source_type='builtin')
            logger.info(f'Acquired extracted backend for {slug} (plan 47)')
            done.add(slug)
            changed = True
        except Exception as e:
            logger.warning(
                f'Backend acquisition for {slug} failed (retry next boot): {e}')
            continue  # leave unmarked so we retry

    if changed:
        from app.services.settings_service import SettingsService
        SettingsService.set(_BACKEND_ACQUIRED_KEY, json.dumps(sorted(done)))
