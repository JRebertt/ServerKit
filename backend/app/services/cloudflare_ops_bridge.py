"""Importlib bridge to the ``serverkit-cloudflare-ops`` extension backend.

Cloudflare zone-ops (the ``/api/v1/cloudflare`` blueprint + ``CloudflareService``)
moved into the bundled ``serverkit-cloudflare-ops`` extension, loaded as the dashed
package ``app.plugins.serverkit-cloudflare-ops`` (see #36). Unlike WordPress, **no
core code imports the zone-ops service** — its only caller is its own blueprint,
which moved with it — so this bridge exists purely so tests (and any future core
caller) can reach the extension's service by a dash-safe importlib path.

The DNS layer stays core and is untouched: the moved ``CloudflareService`` still
borrows the single core ``CloudflareClient`` via ``DNSZoneService._resolve_credential``
(absolute ``app.services.*`` imports), so there is exactly one Cloudflare API client.
"""
import importlib

SLUG = 'serverkit-cloudflare-ops'
PKG = f'app.plugins.{SLUG}'


def ensure_loadable():
    """Make ``app.plugins.serverkit-cloudflare-ops`` importable, in-place if needed.

    Delegates to the shared in-place loader in ``plugin_service`` (also used by the
    flagship boot path). Returns ``True`` if the package is (now) importable.
    """
    from app.services.plugin_service import _ensure_builtin_backend_importable
    return _ensure_builtin_backend_importable(SLUG)


def load(module_name):
    """Import a module from the extension backend (e.g. ``'cloudflare_service'``).

    Resolution order (plan 52 Ph2 cutover): a copy-installed extension first
    (the registry install lands under the normal ``app.plugins`` path), then
    the builtin registration (pre-cutover trees), then the historical core
    location. Callers get ImportError when the extension truly is absent —
    every caller is behind the extension's own routes, so absence is a 404
    before this ever raises.
    """
    try:
        return importlib.import_module(f'{PKG}.{module_name}')
    except ImportError:
        pass
    if ensure_loadable():
        try:
            return importlib.import_module(f'{PKG}.{module_name}')
        except ImportError:
            pass
    # Two-speed fallback: the file may still live in core (pre-move).
    return importlib.import_module(f'app.services.{module_name}')


def get(module_name, attr):
    return getattr(load(module_name), attr)


def cloudflare_service():
    return get('cloudflare_service', 'CloudflareService')


def cloudflare_error():
    return get('cloudflare_service', 'CloudflareError')
