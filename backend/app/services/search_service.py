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
import base64
import binascii
import logging
from dataclasses import dataclass

from app.exceptions import ValidationError

logger = logging.getLogger(__name__)

PER_TYPE_CAP = 5
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_CURSOR_OFFSET = 10_000


@dataclass(frozen=True)
class SearchPage:
    rows: list[dict]
    next_cursor: str | None


class SearchService:
    """Stateless authz-aware entity search."""

    @staticmethod
    def search(user, term, workspace_header=None):
        """Return a flat list of match rows across the core entity types.

        Rows: {'type', 'label', 'sublabel', 'path'}. `term` is expected to be
        already trimmed and >= 2 chars by the route; we still guard here so the
        service is safe to call directly.
        """
        return SearchService._search_rows(user, term, workspace_header)

    @staticmethod
    def search_page(user, term, workspace_header=None, *, types=None,
                    project_id=None, environment_id=None, capabilities=None,
                    cursor=None, limit=None):
        """Return one cursor page of ResourceRef-shaped search results.

        The palette continues to call :meth:`search`, retaining its five rows
        per type. Resource pickers opt into this contract with ``types`` and a
        global page size.
        """
        page_size = limit or DEFAULT_PAGE_SIZE
        offset = SearchService._decode_cursor(cursor)
        fetch_cap = min(MAX_CURSOR_OFFSET + 1, offset + page_size + 1)
        rows = SearchService._search_rows(
            user,
            term,
            workspace_header,
            types=types,
            project_id=project_id,
            environment_id=environment_id,
            capabilities=capabilities,
            per_type_cap=fetch_cap,
            strict_scope=True,
        )
        page_rows = rows[offset:offset + page_size]
        next_offset = offset + len(page_rows)
        next_cursor = (
            SearchService._encode_cursor(next_offset)
            if next_offset < len(rows) else None
        )
        return SearchPage(page_rows, next_cursor)

    @staticmethod
    def _encode_cursor(offset):
        raw = f'v1:{offset}'.encode('ascii')
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')

    @staticmethod
    def _decode_cursor(cursor):
        if not cursor:
            return 0
        try:
            encoded = cursor.encode('ascii')
            encoded += b'=' * (-len(encoded) % 4)
            version, raw_offset = base64.urlsafe_b64decode(encoded).decode('ascii').split(':', 1)
            offset = int(raw_offset)
            if version != 'v1' or offset < 0 or offset > MAX_CURSOR_OFFSET:
                raise ValueError
            return offset
        except (binascii.Error, UnicodeError, ValueError, TypeError):
            raise ValidationError('Invalid search cursor', code='invalid_cursor')

    @staticmethod
    def _search_rows(user, term, workspace_header=None, *, types=None,
                     project_id=None, environment_id=None, capabilities=None,
                     per_type_cap=PER_TYPE_CAP, strict_scope=False):
        """Build accessible ResourceRef rows before global cursor slicing."""
        if user is None:
            return []
        term = (term or '').strip()
        requested_types = set(types or [])
        if len(term) < 2 and not requested_types:
            return []

        from app.services.workspace_service import WorkspaceService
        ws_id = WorkspaceService.resolve_workspace_id(user, workspace_header)
        if (strict_scope and workspace_header not in (None, '', 'all')
                and ws_id is None):
            return []

        required_capabilities = set(capabilities or [])

        def includes(entity_type):
            return not requested_types or entity_type in requested_types

        like = f'%{term}%'
        needle = term.lower()
        rows = []

        # Resolve the set of application ids this user can see once — several
        # entity types (domains, WordPress sites) inherit access from their
        # parent application rather than carrying their own owner column.
        accessible_app_ids = None  # None => "not computed / failed"; [] => none

        # --- service / app ---
        try:
            if not any(includes(kind) for kind in ('service', 'domain', 'site')):
                raise StopIteration
            from app.models.application import Application
            # Deleted apps are not findable: the recycle bin is where they
            # live now, and this id list also scopes the domain/backup
            # searches below.
            q = WorkspaceService.scope_query(
                Application.query_active(), Application, user,
                workspace_id=ws_id, owner_attr='user_id',
                grant_resource_type='application',
            )
            if project_id is not None:
                q = q.filter(Application.project_id == project_id)
            if environment_id is not None:
                q = q.filter(Application.environment_id == environment_id)
            accessible_app_ids = [a.id for a in q.with_entities(Application.id).all()]

            if includes('service') and not required_capabilities:
                apps = (q.filter(Application.name.ilike(like))
                        .order_by(Application.name)
                        .limit(per_type_cap).all())
                for a in apps:
                    rows.append({
                        'type': 'service',
                        'id': str(a.id),
                        'label': a.name,
                        'sublabel': a.app_type or '',
                        'path': f'/services/{a.id}',
                        'scope': SearchService._scope(a),
                        'status': a.status,
                        'capabilities': [],
                    })
        except StopIteration:
            pass
        except Exception:
            logger.exception('search: service/app fan-out failed')

        # --- server ---
        try:
            if not includes('server') or project_id is not None or environment_id is not None:
                raise StopIteration
            from app.models.server import Server
            q = WorkspaceService.scope_query(
                Server.query, Server, user, workspace_id=ws_id, owner_attr=None,
            )
            from app import db
            server_query_limit = (MAX_CURSOR_OFFSET + 1
                                  if required_capabilities else per_type_cap)
            servers = (q.filter(db.or_(
                        Server.name.ilike(like),
                        Server.hostname.ilike(like),
                        Server.ip_address.ilike(like),
                    ))
                    .order_by(Server.name)
                    .limit(server_query_limit).all())
            for s in servers:
                server_capabilities = SearchService._server_capabilities(s)
                if not required_capabilities.issubset(server_capabilities):
                    continue
                rows.append({
                    'type': 'server',
                    'id': str(s.id),
                    'label': s.name or s.hostname or '',
                    'sublabel': s.ip_address or s.hostname or '',
                    'path': f'/servers/{s.id}',
                    'scope': SearchService._scope(s),
                    'status': s.status,
                    'capabilities': sorted(server_capabilities),
                })
        except StopIteration:
            pass
        except Exception:
            logger.exception('search: server fan-out failed')

        # --- project / environment (access derives from Workspace membership) ---
        accessible_workspace_ids = SearchService._accessible_workspace_ids(user, ws_id)
        try:
            if (not includes('project') or required_capabilities
                    or environment_id is not None):
                raise StopIteration
            from app.models.project import Project
            projects_q = Project.query.filter(Project.workspace_id.in_(accessible_workspace_ids))
            if project_id is not None:
                projects_q = projects_q.filter(Project.id == project_id)
            projects = (projects_q.filter(Project.name.ilike(like))
                        .order_by(Project.name)
                        .limit(per_type_cap).all())
            for project in projects:
                rows.append({
                    'type': 'project',
                    'id': str(project.id),
                    'label': project.name,
                    'sublabel': project.description or '',
                    'path': f'/projects/{project.id}',
                    'scope': {
                        'workspace_id': project.workspace_id,
                        'project_id': project.id,
                        'environment_id': None,
                    },
                    'status': None,
                    'capabilities': [],
                })
        except StopIteration:
            pass
        except Exception:
            logger.exception('search: project fan-out failed')

        try:
            if not includes('environment') or required_capabilities:
                raise StopIteration
            from app.models.environment import Environment
            from app.models.project import Project
            environments_q = (Environment.query
                              .join(Project, Project.id == Environment.project_id)
                              .filter(Project.workspace_id.in_(accessible_workspace_ids)))
            if project_id is not None:
                environments_q = environments_q.filter(Environment.project_id == project_id)
            if environment_id is not None:
                environments_q = environments_q.filter(Environment.id == environment_id)
            environments = (environments_q.filter(Environment.name.ilike(like))
                            .order_by(Project.name, Environment.order, Environment.id)
                            .limit(per_type_cap).all())
            for environment in environments:
                rows.append({
                    'type': 'environment',
                    'id': str(environment.id),
                    'label': environment.name,
                    'sublabel': environment.project.name if environment.project else '',
                    'path': f'/projects/{environment.project_id}',
                    'scope': {
                        'workspace_id': (environment.project.workspace_id
                                         if environment.project else None),
                        'project_id': environment.project_id,
                        'environment_id': environment.id,
                    },
                    'status': None,
                    'capabilities': [],
                })
        except StopIteration:
            pass
        except Exception:
            logger.exception('search: environment fan-out failed')

        # --- domain (inherits access from parent Application) ---
        try:
            if includes('domain') and not required_capabilities and accessible_app_ids:
                from app.models.domain import Domain
                domains = (Domain.query
                           .filter(Domain.application_id.in_(accessible_app_ids),
                                   Domain.name.ilike(like))
                           .order_by(Domain.name)
                           .limit(per_type_cap).all())
                for d in domains:
                    rows.append({
                        'type': 'domain',
                        'id': str(d.id),
                        'label': d.name,
                        'sublabel': '',
                        'path': '/domains',
                        'scope': SearchService._scope(d.application),
                        'status': None,
                        'capabilities': [],
                    })
        except Exception:
            logger.exception('search: domain fan-out failed')

        # --- database (workspace-filtered via the service) ---
        try:
            if (not includes('database') or required_capabilities
                    or project_id is not None or environment_id is not None):
                raise StopIteration
            from app.services.managed_database_service import ManagedDatabaseService
            matched = 0
            for mdb in ManagedDatabaseService.list(workspace_id=ws_id):
                if matched >= per_type_cap:
                    break
                haystack = ' '.join(filter(None, [mdb.name, mdb.engine, mdb.host])).lower()
                if needle in haystack:
                    rows.append({
                        'type': 'database',
                        'id': str(mdb.id),
                        'label': mdb.name,
                        'sublabel': mdb.engine or '',
                        'path': '/databases',
                        'scope': SearchService._scope(mdb),
                        'status': None,
                        'capabilities': [],
                    })
                    matched += 1
        except StopIteration:
            pass
        except Exception:
            logger.exception('search: database fan-out failed')

        # --- site (WordPress, inherits access from parent Application) ---
        try:
            if includes('site') and not required_capabilities and accessible_app_ids:
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
                         .limit(per_type_cap).all())
                for site in sites:
                    parent = site.application
                    rows.append({
                        'type': 'site',
                        'id': str(site.id),
                        'label': parent.name if parent else f'site #{site.id}',
                        'sublabel': 'WordPress',
                        'path': f'/services/{site.application_id}',
                        'scope': SearchService._scope(parent),
                        'status': parent.status if parent else None,
                        'capabilities': [],
                    })
        except Exception:
            logger.exception('search: site fan-out failed')

        # --- cron (admin-only system surface) ---
        try:
            if (includes('cron') and not required_capabilities
                    and project_id is None and environment_id is None
                    and getattr(user, 'is_admin', False)):
                from app.services.cron_service import CronService
                jobs = (CronService.list_jobs() or {}).get('jobs', [])
                matched = 0
                for job in jobs:
                    if matched >= per_type_cap:
                        break
                    name = job.get('name') or ''
                    command = job.get('command') or ''
                    haystack = ' '.join(filter(None, [
                        name, job.get('description') or '', command,
                    ])).lower()
                    if needle in haystack:
                        rows.append({
                            'type': 'cron',
                            'id': str(job.get('id') or job.get('job_id') or
                                      f"{name}:{job.get('schedule') or ''}:{command}"),
                            'label': name or command,
                            'sublabel': job.get('schedule') or '',
                            'path': '/cron',
                            'scope': SearchService._empty_scope(),
                            'status': job.get('status'),
                            'capabilities': [],
                        })
                        matched += 1
        except Exception:
            logger.exception('search: cron fan-out failed')

        # --- extension (any authenticated user may list) ---
        try:
            if (not includes('extension') or required_capabilities
                    or project_id is not None or environment_id is not None):
                raise StopIteration
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
                       .limit(per_type_cap).all())
            for p in plugins:
                rows.append({
                    'type': 'extension',
                    'id': str(p.id),
                    'label': p.display_name or p.name,
                    'sublabel': p.author or 'Extension',
                    'path': '/marketplace',
                    'scope': SearchService._empty_scope(),
                    'status': p.status,
                    'capabilities': [],
                })
        except StopIteration:
            pass
        except Exception:
            logger.exception('search: extension fan-out failed')

        # --- vault (NAMES ONLY — never expose secret values) ---
        try:
            if (not includes('vault') or required_capabilities
                    or project_id is not None or environment_id is not None):
                raise StopIteration
            from app.models.secret_vault import SecretVault
            from app import db
            q = SecretVault.query
            if ws_id is not None:
                q = q.filter(SecretVault.workspace_id == ws_id)
            elif not getattr(user, 'is_admin', False):
                q = q.filter(SecretVault.workspace_id.in_(accessible_workspace_ids))
            vaults = (q.filter(db.or_(
                        SecretVault.name.ilike(like),
                        SecretVault.slug.ilike(like),
                        SecretVault.description.ilike(like),
                    ))
                    .order_by(SecretVault.name)
                    .limit(per_type_cap).all())
            for v in vaults:
                rows.append({
                    'type': 'vault',
                    'id': str(v.id),
                    'label': v.name,
                    'sublabel': v.description or 'Vault',
                    'path': '/vaults',
                    'scope': SearchService._scope(v),
                    'status': None,
                    'capabilities': [],
                })
        except StopIteration:
            pass
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
            if requested_types and entity_type not in requested_types:
                continue
            try:
                query = search_provider_registry.SearchQuery(
                    term=term,
                    user=user,
                    workspace_id=ws_id,
                    project_id=project_id,
                    environment_id=environment_id,
                    capabilities=tuple(sorted(required_capabilities)),
                    limit=per_type_cap,
                )
                provider_rows = search_provider_registry.clean_rows(
                    entity_type, provider(query), per_type_cap)
                for row in provider_rows:
                    row_scope = row['scope']
                    if (ws_id is not None
                            and row_scope['workspace_id'] != ws_id):
                        continue
                    if project_id is not None and row_scope['project_id'] != project_id:
                        continue
                    if (environment_id is not None
                            and row_scope['environment_id'] != environment_id):
                        continue
                    if not required_capabilities.issubset(row['capabilities']):
                        continue
                    rows.append(row)
            except Exception:
                logger.exception('search: %s fan-out failed', entity_type)

        return rows

    @staticmethod
    def _empty_scope():
        return {
            'workspace_id': None,
            'project_id': None,
            'environment_id': None,
        }

    @staticmethod
    def _scope(resource):
        if resource is None:
            return SearchService._empty_scope()
        return {
            'workspace_id': getattr(resource, 'workspace_id', None),
            'project_id': getattr(resource, 'project_id', None),
            'environment_id': getattr(resource, 'environment_id', None),
        }

    @staticmethod
    def _server_capabilities(server):
        raw = server.cached_capabilities if isinstance(server.cached_capabilities, dict) else {}
        return {str(name) for name, enabled in raw.items() if enabled is True}

    @staticmethod
    def _accessible_workspace_ids(user, workspace_id):
        if workspace_id is not None:
            return [workspace_id]
        from app.services.workspace_service import WorkspaceService
        if getattr(user, 'is_admin', False):
            from app.models.workspace import Workspace
            return [workspace.id for workspace in Workspace.query.all()]
        return [workspace.id for workspace in
                WorkspaceService.list_workspaces(user_id=user.id)]
