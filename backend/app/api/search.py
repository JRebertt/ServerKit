"""Unified entity omnisearch API (plan 41, Phase 4).

A single authz-aware endpoint the command palette calls to search across the
core entity types (services, servers, domains, databases, WordPress sites, cron
jobs, extensions, vaults). Business logic lives in SearchService; this blueprint
just validates the term, resolves the user, and shapes the JSON.
"""
from flask import Blueprint, request
from app.api.contracts import api_contract
from app.api.responses import list_response
from app.api.schemas.search import SearchQuerySchema, SearchResponseSchema
from app.services.search_service import SearchService
from app.middleware.rbac import auth_required, get_current_user

search_bp = Blueprint('search', __name__)


@search_bp.route('', methods=['GET'])
@auth_required()
@api_contract(query=SearchQuerySchema, responses={200: SearchResponseSchema})
def search(query):
    """Search accessible resources without making the palette a second API."""
    q = query['q']
    extended = any(query.get(key) is not None for key in (
        'types', 'project_id', 'environment_id', 'capabilities', 'cursor', 'limit',
    ))
    if len(q) < 2 and not query.get('types'):
        return list_response([], legacy_key='results')

    user = get_current_user()
    workspace = request.headers.get('X-Workspace-Id') or query['workspace_id']
    if not extended:
        rows = SearchService.search(user, q, workspace)
        return list_response(rows, legacy_key='results')

    page = SearchService.search_page(
        user,
        q,
        workspace,
        types=query.get('types'),
        project_id=query.get('project_id'),
        environment_id=query.get('environment_id'),
        capabilities=query.get('capabilities'),
        cursor=query.get('cursor'),
        limit=query.get('limit'),
    )
    return list_response(
        page.rows,
        meta={'next_cursor': page.next_cursor},
        legacy_key='results',
    )
