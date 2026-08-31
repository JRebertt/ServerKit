"""Public status pages.

Scope note: this service owns *publishing* — pages, branding, grouping and the
public JSON/badge. It no longer owns the check engine. Monitors (what used to be
called "components") and their incidents are core, in
``app.services.monitor_service``, because watching a site must not depend on
having this extension installed. The component/health/incident methods below are
thin delegates kept so existing callers and the extension's own API blueprint
keep working unchanged.
"""
import logging

from app.models.status_page import StatusPage, StatusComponent, StatusIncident
from app.services.monitor_service import MonitorService
from app.utils.slug import validate_slug
from app import db

logger = logging.getLogger(__name__)


class StatusPageService:
    """Service for public status pages."""

    @staticmethod
    def normalize_slug(value):
        return validate_slug(value)

    # --- Pages ---

    @staticmethod
    def list_pages():
        return StatusPage.query.order_by(StatusPage.name).all()

    @staticmethod
    def get_page(page_id):
        return StatusPage.query.get(page_id)

    @staticmethod
    def get_page_by_slug(slug):
        return StatusPage.query.filter_by(slug=slug).first()

    @staticmethod
    def create_page(data):
        slug = StatusPageService.normalize_slug(data.get('slug'))
        if StatusPage.query.filter_by(slug=slug).first():
            raise ValueError(f"Status page '{slug}' already exists")

        page = StatusPage(
            name=data['name'],
            slug=slug,
            description=data.get('description', ''),
            logo_url=data.get('logo_url'),
            primary_color=data.get('primary_color', '#4f46e5'),
            custom_domain=data.get('custom_domain'),
            is_public=data.get('is_public', True),
            show_uptime=data.get('show_uptime', True),
            show_history=data.get('show_history', True),
        )
        db.session.add(page)
        db.session.commit()
        return page

    @staticmethod
    def update_page(page_id, data):
        page = StatusPage.query.get(page_id)
        if not page:
            return None
        for field in ['name', 'description', 'logo_url', 'primary_color',
                      'custom_domain', 'is_public', 'show_uptime', 'show_history']:
            if field in data:
                setattr(page, field, data[field])
        db.session.commit()
        return page

    @staticmethod
    def delete_page(page_id):
        page = StatusPage.query.get(page_id)
        if not page:
            return False
        db.session.delete(page)
        db.session.commit()
        return True

    @staticmethod
    def get_public_page(slug):
        """Get public status page data (no auth required)."""
        page = StatusPage.query.filter_by(slug=slug, is_public=True).first()
        if not page:
            return None

        # Internal probe config must not appear on the unauthenticated public page
        # (a health-driven WP component may carry an internal localhost:port target).
        public_hidden = ('check_type', 'check_target', 'check_interval', 'check_timeout',
                         'check_method', 'expected_status', 'keyword', 'follow_redirects',
                         'verify_tls', 'retries', 'consecutive_failures',
                         'cert_issuer', 'cert_expires_at', 'next_check_at')
        components = page.components.all()
        grouped = {}
        for comp in components:
            group = comp.group or 'Services'
            cd = comp.to_dict()
            for k in public_hidden:
                cd.pop(k, None)
            grouped.setdefault(group, []).append(cd)

        # Active incidents
        active_incidents = page.incidents.filter(
            StatusIncident.status != 'resolved'
        ).limit(10).all()

        # Recent resolved
        resolved = page.incidents.filter_by(status='resolved').limit(5).all()

        # Overall status
        statuses = [c.status for c in components]
        if any(s == 'major_outage' for s in statuses):
            overall = 'major_outage'
        elif any(s in ('partial_outage', 'degraded') for s in statuses):
            overall = 'degraded'
        elif any(s == 'maintenance' for s in statuses):
            overall = 'maintenance'
        else:
            overall = 'operational'

        return {
            'page': page.to_dict(),
            'overall_status': overall,
            'groups': grouped,
            'active_incidents': [i.to_dict() for i in active_incidents],
            'recent_incidents': [i.to_dict() for i in resolved],
        }

    # --- Components (monitors attached to a page) ---
    # Delegates to MonitorService; a component is just a monitor with a page_id.

    @staticmethod
    def create_component(page_id, data):
        page = StatusPage.query.get(page_id)
        if not page:
            raise ValueError('Status page not found')
        return MonitorService.create({**data, 'page_id': page_id})

    @staticmethod
    def attach_component(page_id, monitor_id):
        """Publish an existing monitor on a page. Lets an operator build a status
        page out of monitors they already have instead of re-declaring probes."""
        if not StatusPage.query.get(page_id):
            raise ValueError('Status page not found')
        return MonitorService.update(monitor_id, {'page_id': page_id})

    @staticmethod
    def detach_component(monitor_id):
        """Remove a monitor from its page without deleting the monitor."""
        return MonitorService.update(monitor_id, {'page_id': None})

    @staticmethod
    def update_component(comp_id, data):
        return MonitorService.update(comp_id, data)

    @staticmethod
    def delete_component(comp_id):
        return MonitorService.delete(comp_id)

    # --- Health Checks (delegated to the core engine) ---

    @staticmethod
    def run_check(component_id):
        return MonitorService.run_check(component_id)

    @staticmethod
    def get_check_history(component_id, hours=24):
        return MonitorService.get_check_history(component_id, hours=hours)

    @staticmethod
    def recompute_uptime(comp):
        return MonitorService.recompute_uptime(comp)

    @staticmethod
    def sync_component_from_health(comp, overall_status, error=None):
        return MonitorService.sync_component_from_health(comp, overall_status, error)

    # --- Incidents (delegated) ---

    @staticmethod
    def create_incident(page_id, data):
        return MonitorService.create_incident(page_id, data)

    @staticmethod
    def update_incident(incident_id, data):
        return MonitorService.update_incident(incident_id, data)

    @staticmethod
    def delete_incident(incident_id):
        return MonitorService.delete_incident(incident_id)

    @staticmethod
    def get_badge(slug):
        """Generate status badge data."""
        page = StatusPage.query.filter_by(slug=slug).first()
        if not page:
            return None

        components = page.components.all()
        statuses = [c.status for c in components]

        if not statuses or all(s == 'operational' for s in statuses):
            return {'label': 'status', 'message': 'operational', 'color': 'brightgreen'}
        elif any(s == 'major_outage' for s in statuses):
            return {'label': 'status', 'message': 'major outage', 'color': 'red'}
        elif any(s in ('partial_outage', 'degraded') for s in statuses):
            return {'label': 'status', 'message': 'degraded', 'color': 'yellow'}
        else:
            return {'label': 'status', 'message': 'maintenance', 'color': 'blue'}
