"""Importlib bridge to the ``serverkit-wordpress`` extension backend.

WordPress is a standalone extension (plan 52 Phase 5 — own repo, registry
install). Its backend loads as the *dashed* package
``app.plugins.serverkit-wordpress``. Because the slug contains a dash it can
never be reached with a normal ``import`` statement
(``import app.plugins.serverkit-wordpress`` is a SyntaxError), so the handful
of core call sites that still reach into the WordPress stack go through this
bridge, which resolves modules with ``importlib`` on a *string* path —
dash-safe.

With the extension registry-installed, its backend copy under
``backend/app/plugins/serverkit-wordpress/`` resolves as an ordinary
subpackage. With it NOT installed, the bridge raises a clear
``WordPressExtensionMissingError`` — callers either guard with try/except
(lazy WP-context paths) or check before calling.
"""
import importlib

SLUG = 'serverkit-wordpress'
PKG = f'app.plugins.{SLUG}'


class WordPressExtensionMissingError(RuntimeError):
    """The serverkit-wordpress extension is not installed/active."""


def ensure_loadable():
    """Make ``app.plugins.serverkit-wordpress`` importable if the extension is
    installed. Idempotent and cheap after the first call. Returns ``True`` if
    the package is (now) importable, ``False`` when the extension is absent.
    """
    from app.services.plugin_service import _ensure_builtin_backend_importable
    return _ensure_builtin_backend_importable(SLUG)


def load(module_name):
    """Import a module from the extension backend (e.g. ``'wordpress_service'``).

    Raises WordPressExtensionMissingError when the extension isn't installed.
    A genuine ImportError inside the extension propagates unchanged.
    """
    if ensure_loadable():
        return importlib.import_module(f'{PKG}.{module_name}')
    raise WordPressExtensionMissingError(
        f'the serverkit-wordpress extension is not installed '
        f'(needed for app.plugins.{SLUG}.{module_name}); '
        f'install it from the Marketplace')


def get(module_name, attr):
    """Return an attribute (usually a service class) from an extension module."""
    return getattr(load(module_name), attr)


# ── Convenience accessors for the service classes core code reaches for ──
# All WordPress *models* stay core (app.models.wordpress_site / wordpress_custom_plugin);
# only these services physically move into the extension, so only these need the bridge.

def wordpress_service():
    return get('wordpress_service', 'WordPressService')


def git_wordpress_service():
    return get('git_wordpress_service', 'GitWordPressService')


def wordpress_env_service():
    return get('wordpress_env_service', 'WordPressEnvService')


def wp_update_service():
    return get('wp_update_service', 'WpUpdateService')
