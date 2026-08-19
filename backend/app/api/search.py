"""Unified entity omnisearch API (plan 41, Phase 4).

A single authz-aware endpoint the command palette calls to search across the
core entity types (services, servers, domains, databases, WordPress sites, cron
jobs, extensions, vaults). Business logic lives in SearchService; this blueprint
just validates the term, resolves the user, and shapes the JSON.
"""
from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.api.contracts import api_contract
from app.api.responses import list_response
from app.api.schemas.search import SearchQuerySchema, SearchResponseSchema
from app.services.search_service import SearchService
from app.middleware.rbac import get_current_user

search_bp = Blueprint('search', __name__)


@search_bp.route('', methods=['GET'])
@jwt_required()
@api_contract(query=SearchQuerySchema, responses={200: SearchResponseSchema})
def search(query):
    """Search entities by name. ``q`` terms shorter than two chars return none."""
    q = query['q']
    if len(q) < 2:
        return list_response([], legacy_key='results')

    user = get_current_user()
    workspace = request.headers.get('X-Workspace-Id') or query['workspace_id']
    rows = SearchService.search(user, q, workspace)
    return list_response(rows, legacy_key='results')
