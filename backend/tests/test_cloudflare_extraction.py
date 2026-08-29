"""Prove the Cloudflare zone-ops extraction (Phase 5, #36; standalone repo
since the plan 52 Ph2 cutover).

Zone-ops (the /api/v1/cloudflare blueprint + CloudflareService) lives in the
standalone serverkit-cloudflare-ops repo now — no longer a seeded flagship. A
lean panel boots with no cloudflare routes; the suite mounts the extension
from the sibling checkout (skip when absent). The DNS layer stays core: the
moved service borrows the single core CloudflareClient via DNSZoneService.
"""
import importlib

import pytest

from app.models.plugin import InstalledPlugin
from app.services import cloudflare_ops_bridge

SLUG = 'serverkit-cloudflare-ops'


def test_cloudflare_service_left_core():
    """The zone-ops service is gone from core after extraction."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('app.services.cloudflare_service')


def test_dns_client_stays_core_single_source():
    """The one Cloudflare API client remains core (no duplicate in the extension)."""
    from app.services.dns import CloudflareClient
    assert CloudflareClient.__module__ == 'app.services.dns.cloudflare'


def test_bridge_resolves_service_from_extension(cf_extension):
    CloudflareService = cloudflare_ops_bridge.cloudflare_service()
    assert CloudflareService.__name__ == 'CloudflareService'
    assert CloudflareService.__module__.startswith(f'app.plugins.{SLUG}')
    # And it does not vendor its own client — it imports the core one lazily.
    import inspect
    src = inspect.getsource(CloudflareService)
    assert 'from app.services.dns import CloudflareClient' in src
    assert 'DNSZoneService._resolve_credential' in src


@pytest.mark.fresh_app
def test_cloudflare_is_not_seeded_on_a_lean_panel(app):
    """The flagship era ended with the cutover: a fresh panel has no
    cloudflare-ops row and no zone routes until a registry install."""
    assert InstalledPlugin.query.filter_by(slug=SLUG).first() is None
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert not any(r.startswith('/api/v1/cloudflare/') for r in rules)


def test_cloudflare_blueprint_registered_from_extension(cf_extension, app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert any(r.startswith('/api/v1/cloudflare/zones') for r in rules), \
        'Cloudflare zone-ops API should be registered from the extension'


def test_cloudflare_api_reachable_not_404(cf_extension, app, client, auth_headers):
    """The extension blueprint is live (not 404) and the status guard passes for
    the mounted extension (not 503). It may 400/502 without a real CF zone — we
    only assert the route is wired."""
    resp = client.get('/api/v1/cloudflare/zones/1/settings', headers=auth_headers)
    assert resp.status_code not in (404, 503), resp.status_code
