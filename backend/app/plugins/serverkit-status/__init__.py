"""ServerKit Status Pages extension backend package.

Extracted from core (plan 47): the status-pages blueprint (public status/badge
routes + authenticated management API) and its service ship here so a fresh panel
that never publishes a status page loads none of it. Mounted under
``/api/v1/status`` via the manifest's ``url_prefix``; the public /status/<slug>
and /status/badge/<slug> pages work whenever the extension is installed. The
StatusPage / StatusComponent / StatusIncident / HealthCheck models stay in core
(G2). Core's WordPress health-check job reaches
``StatusPageService.sync_component_from_health`` through
``plugin_service.get_installed_extension_attr`` only when installed. Upgrades
re-acquire it automatically (``CONVERTED_BUILTIN_SLUGS``).
"""
from .status_pages import status_pages_bp

__all__ = ['status_pages_bp']
