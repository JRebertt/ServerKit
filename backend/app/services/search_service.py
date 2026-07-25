"""Unified entity omnisearch (plan 41, Phase 4).

Fans a short search term out across the panel's core entity types and returns a
flat list of lightweight, deep-linkable rows. Each entity type reuses its
domain's existing access helpers so a member never sees resources they can't
already reach elsewhere — the search endpoint invents no new ACL.

Design rules:
  - Case-insensitive substring match (SQL ILIKE / Python `in` on lowered text).
  - Per-type cap of ``PER_TYPE_CAP`` rows so one noisy type can't drown the rest.
  - Every entity block is isolated in its own try/except: one failing type
    (missing table, migration skew, service error) degrades to "no rows of that
    type" instead of 500-ing the whole search.
"""
import logging

logger = logging.getLogger(__name__)

PER_TYPE_CAP = 5


class SearchService:
    """Stateless authz-aware entity search."""

    @staticmethod
    def search(user, term, workspace_header=None):
        """Return a flat list of match rows across the core entity types.

        Rows: {'type', 'label', 'sublabel', 'path'}. `term` is expected to be
        already trimmed and >= 2 chars by the route; we still guard here so the
        service is safe to call directly.
        """
        if user is None:
            return []
        term = (term or '').strip()
        if len(term) < 2:
            return []

        from app.services.workspace_service import WorkspaceService
        ws_id = WorkspaceService.resolve_workspace_id(user, workspace_header)

        like = f'%{term}%'
        needle = term.lower()
        rows = []

        # Resolve the set of application ids this user can see once — several
        # entity types (domains, WordPress sites) inherit access from their
        # parent application rather than carrying their own owner column.
        accessible_app_ids = None  # None => "not computed / failed"; [] => none

        # --- service / app ---
        try:
            from app.models.application import Application
            q = WorkspaceService.scope_query(
                Application.query, Application, user,
                workspace_id=ws_id, owner_attr='user_id',
                grant_resource_type='application',
            )
            accessible_app_ids = [a.id for a in q.with_entities(Application.id).all()]

            apps = (q.filter(Application.name.ilike(like))
                    .order_by(Application.name)
                    .limit(PER_TYPE_CAP).all())
            for a in apps:
                rows.append({
                    'type': 'service',
                    'label': a.name,
                    'sublabel': a.app_type or '',
                    'path': f'/services/{a.id}',
                })
        except Exception:
            logger.exception('search: service/app fan-out failed')

        # --- server ---
        try:
            from app.models.server import Server
            q = WorkspaceService.scope_query(
                Server.query, Server, user, workspace_id=ws_id, owner_attr=None,
            )
            from app import db
            servers = (q.filter(db.or_(
                        Server.name.ilike(like),
                        Server.hostname.ilike(like),
                        Server.ip_address.ilike(like),
                    ))
                    .order_by(Server.name)
                    .limit(PER_TYPE_CAP).all())
            for s in servers:
                rows.append({
                    'type': 'server',
                    'label': s.name or s.hostname or '',
                    'sublabel': s.ip_address or s.hostname or '',
                    'path': f'/servers/{s.id}',
                })
        except Exception:
            logger.exception('search: server fan-out failed')

        # --- domain (inherits access from parent Application) ---
        try:
            if accessible_app_ids:
                from app.models.domain import Domain
                domains = (Domain.query
                           .filter(Domain.application_id.in_(accessible_app_ids),
                                   Domain.name.ilike(like))
                           .order_by(Domain.name)
                           .limit(PER_TYPE_CAP).all())
                for d in domains:
                    rows.append({
                        'type': 'domain',
                        'label': d.name,
                        'sublabel': '',
                        'path': '/domains',
                    })
        except Exception:
            logger.exception('search: domain fan-out failed')

        # --- database (workspace-filtered via the service) ---
        try:
            from app.services.managed_database_service import ManagedDatabaseService
            matched = 0
            for mdb in ManagedDatabaseService.list(workspace_id=ws_id):
                if matched >= PER_TYPE_CAP:
                    break
                haystack = ' '.join(filter(None, [mdb.name, mdb.engine, mdb.host])).lower()
                if needle in haystack:
                    rows.append({
                        'type': 'database',
                        'label': mdb.name,
                        'sublabel': mdb.engine or '',
                        'path': '/databases',
                    })
                    matched += 1
        except Exception:
            logger.exception('search: database fan-out failed')

        # --- site (WordPress, inherits access from parent Application) ---
        try:
            if accessible_app_ids:
                from app.models.wordpress_site import WordPressSite
                from app.models.application import Application
                from app import db
                sites = (WordPressSite.query
                         .join(Application, Application.id == WordPressSite.application_id)
                         .filter(WordPressSite.application_id.in_(accessible_app_ids),
                                 db.or_(
                                     Application.name.ilike(like),
                                     WordPressSite.admin_email.ilike(like),
                                 ))
                         .order_by(Application.name)
                         .limit(PER_TYPE_CAP).all())
                for site in sites:
                    parent = site.application
                    rows.append({
                        'type': 'site',
                        'label': parent.name if parent else f'site #{site.id}',
                        'sublabel': 'WordPress',
                        'path': f'/services/{site.application_id}',
                    })
        except Exception:
            logger.exception('search: site fan-out failed')

        # --- cron (admin-only system surface) ---
        try:
            if getattr(user, 'is_admin', False):
                from app.services.cron_service import CronService
                jobs = (CronService.list_jobs() or {}).get('jobs', [])
                matched = 0
                for job in jobs:
                    if matched >= PER_TYPE_CAP:
                        break
                    name = job.get('name') or ''
                    command = job.get('command') or ''
                    haystack = ' '.join(filter(None, [
                        name, job.get('description') or '', command,
                    ])).lower()
                    if needle in haystack:
                        rows.append({
                            'type': 'cron',
                            'label': name or command,
                            'sublabel': job.get('schedule') or '',
                            'path': '/cron',
                        })
                        matched += 1
        except Exception:
            logger.exception('search: cron fan-out failed')

        # --- extension (any authenticated user may list) ---
        try:
            from app.models.plugin import InstalledPlugin
            from app import db
            plugins = (InstalledPlugin.query
                       .filter(db.or_(
                           InstalledPlugin.name.ilike(like),
                           InstalledPlugin.display_name.ilike(like),
                           InstalledPlugin.slug.ilike(like),
                           InstalledPlugin.description.ilike(like),
                       ))
                       .order_by(InstalledPlugin.display_name)
                       .limit(PER_TYPE_CAP).all())
            for p in plugins:
                rows.append({
                    'type': 'extension',
                    'label': p.display_name or p.name,
                    'sublabel': p.author or 'Extension',
                    'path': '/marketplace',
                })
        except Exception:
            logger.exception('search: extension fan-out failed')

        # --- vault (NAMES ONLY — never expose secret values) ---
        try:
            from app.models.secret_vault import SecretVault
            from app import db
            q = SecretVault.query
            if ws_id is not None:
                q = q.filter(SecretVault.workspace_id == ws_id)
            vaults = (q.filter(db.or_(
                        SecretVault.name.ilike(like),
                        SecretVault.slug.ilike(like),
                        SecretVault.description.ilike(like),
                    ))
                    .order_by(SecretVault.name)
                    .limit(PER_TYPE_CAP).all())
            for v in vaults:
                rows.append({
                    'type': 'vault',
                    'label': v.name,
                    'sublabel': v.description or 'Vault',
                    'path': '/vaults',
                })
        except Exception:
            logger.exception('search: vault fan-out failed')

        # --- entities contributed by extensions (see search_provider_registry) ---
        # Same isolation and cap as a core block: one broken provider degrades
        # to "no rows of that type", and the cap is re-applied on this side
        # rather than trusted from the provider.
        try:
            from app.services import search_provider_registry
            contributed = search_provider_registry.providers()
        except Exception:
            logger.exception('search: provider registry unavailable')
            contributed = []
        for entity_type, provider in contributed:
            try:
                query = search_provider_registry.SearchQuery(
                    term=term, user=user, workspace_id=ws_id, limit=PER_TYPE_CAP)
                rows.extend(search_provider_registry.clean_rows(
                    entity_type, provider(query), PER_TYPE_CAP))
            except Exception:
                logger.exception('search: %s fan-out failed', entity_type)

        return rows
