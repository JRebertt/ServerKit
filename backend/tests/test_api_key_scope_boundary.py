"""Restricted keys must never inherit their owner's unrestricted role."""
import pytest
from flask import Blueprint, jsonify

from factories import make_user, headers_for
from app.middleware.api_scope_middleware import require_scope
from app.middleware.rbac import admin_required, auth_required
from app.services.api_key_service import ApiKeyService


def _headers(db, scopes, role='admin'):
    user = make_user(db, role=role)
    _, raw_key = ApiKeyService.create_key(user.id, name='scope-boundary', scopes=scopes)
    return {'X-API-Key': raw_key}


@pytest.mark.parametrize('scopes', [['apps:read'], ['read'], ['apps:*'], ['write']])
def test_restricted_admin_key_cannot_modify_unscoped_ai_settings(client, db_session, scopes):
    response = client.put('/api/v1/ai/settings', headers=_headers(db_session, scopes),
                          json={'ai_enabled': True})
    assert response.status_code == 403
    assert response.json['error'] == 'This endpoint does not allow restricted API keys'


@pytest.mark.fresh_app
def test_scope_declarations_are_required_and_do_not_replace_role_policy(app, db_session):
    bp = Blueprint('scope_boundary', __name__)

    @bp.route('/read')
    @auth_required()
    @require_scope('apps:read')
    def read():
        return jsonify({'ok': True})

    @bp.route('/write', methods=['PUT'])
    @admin_required
    @require_scope('apps:write')
    def write():
        return jsonify({'ok': True})

    @bp.route('/undeclared', methods=['PUT'])
    @admin_required
    def undeclared():
        return jsonify({'ok': True})

    app.register_blueprint(bp, url_prefix='/__scope_boundary')
    client = app.test_client()
    read_key = _headers(db_session, ['apps:read'])
    assert client.get('/__scope_boundary/read', headers=read_key).status_code == 200
    assert client.put('/__scope_boundary/write', headers=read_key).status_code == 403
    assert client.put('/__scope_boundary/undeclared', headers=read_key).status_code == 403
    wrong_resource = _headers(db_session, ['databases:read'])
    assert client.get('/__scope_boundary/read', headers=wrong_resource).status_code == 403
    wildcard = _headers(db_session, ['apps:*'])
    assert client.put('/__scope_boundary/write', headers=wildcard).status_code == 200
    assert client.put('/__scope_boundary/undeclared', headers=wildcard).status_code == 403
    full = _headers(db_session, ['*'])
    assert client.put('/__scope_boundary/undeclared', headers=full).status_code == 200
    viewer = _headers(db_session, ['*'], role='viewer')
    assert client.put('/__scope_boundary/write', headers=viewer).status_code == 403
    jwt = headers_for(make_user(db_session, role='admin'))
    assert client.put('/__scope_boundary/undeclared', headers=jwt).status_code == 200
