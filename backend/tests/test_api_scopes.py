"""Tests for API-key scope enforcement and sensitive-data masking."""
import pytest
from flask import Blueprint, g, jsonify

from app.middleware.api_scope_middleware import require_scope, SCOPES, SCOPE_KEYS
from app.utils.sensitive_data_filter import (
    mask_sensitive,
    is_sensitive_key,
    scopes_for_request,
    MASK,
    SENSITIVE_KEY_PATTERNS,
)
from app.models.api_key import ApiKey

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _key_with_scopes(scopes):
    """Build an unsaved ApiKey carrying the given scopes."""
    k = ApiKey(user_id=1, name='test', key_prefix='sk_test', key_hash='x')
    k.set_scopes(scopes)
    return k


@pytest.fixture
def scoped_app(app):
    """Register a throwaway blueprint whose route requires 'apps:read'."""
    bp = Blueprint('scope_probe', __name__)

    @bp.route('/probe')
    @require_scope('apps:read')
    def probe():
        return jsonify({'ok': True})

    app.register_blueprint(bp, url_prefix='/__test')
    return app


# ---------------------------------------------------------------------------
# require_scope: API-key requests
# ---------------------------------------------------------------------------
def test_require_scope_blocks_key_missing_scope(scoped_app):
    @scoped_app.route('/__probe_block')
    @require_scope('apps:read')
    def _block():  # pragma: no cover - exercised via client
        return jsonify({'ok': True})

    with scoped_app.test_request_context('/__probe_block'):
        g.api_key = _key_with_scopes(['databases:read'])
        rv = _block()
        body, status = rv
        assert status == 403
        assert 'Insufficient API key scope' in body.get_json()['error']


def test_require_scope_allows_key_with_exact_scope(scoped_app):
    @scoped_app.route('/__probe_exact')
    @require_scope('apps:read')
    def _exact():
        return jsonify({'ok': True})

    with scoped_app.test_request_context('/__probe_exact'):
        g.api_key = _key_with_scopes(['apps:read'])
        rv = _exact()
        assert rv.get_json() == {'ok': True}


def test_require_scope_allows_full_access_star(scoped_app):
    @scoped_app.route('/__probe_star')
    @require_scope('apps:read', 'databases:write')
    def _star():
        return jsonify({'ok': True})

    with scoped_app.test_request_context('/__probe_star'):
        g.api_key = _key_with_scopes(['*'])
        rv = _star()
        assert rv.get_json() == {'ok': True}


def test_require_scope_allows_resource_wildcard(scoped_app):
    @scoped_app.route('/__probe_wild')
    @require_scope('apps:read')
    def _wild():
        return jsonify({'ok': True})

    with scoped_app.test_request_context('/__probe_wild'):
        g.api_key = _key_with_scopes(['apps:*'])
        rv = _wild()
        assert rv.get_json() == {'ok': True}


def test_require_scope_requires_all_listed_scopes(scoped_app):
    @scoped_app.route('/__probe_all')
    @require_scope('apps:read', 'apps:deploy')
    def _all():
        return jsonify({'ok': True})

    # Has apps:read but not apps:deploy -> blocked.
    with scoped_app.test_request_context('/__probe_all'):
        g.api_key = _key_with_scopes(['apps:read'])
        rv = _all()
        _, status = rv
        assert status == 403


# ---------------------------------------------------------------------------
# require_scope: JWT/session requests pass through
# ---------------------------------------------------------------------------
def test_require_scope_passthrough_for_jwt(scoped_app):
    @scoped_app.route('/__probe_jwt')
    @require_scope('apps:read')
    def _jwt():
        return jsonify({'ok': True})

    # No g.api_key set -> treated as JWT/session -> pass through.
    with scoped_app.test_request_context('/__probe_jwt'):
        assert getattr(g, 'api_key', None) is None
        rv = _jwt()
        assert rv.get_json() == {'ok': True}


# ---------------------------------------------------------------------------
# Scope catalog sanity
# ---------------------------------------------------------------------------
def test_scope_catalog_covers_required_scopes():
    required = {
        'read', 'write', 'apps:read', 'apps:write', 'apps:deploy',
        'databases:read', 'databases:write', 'domains:read', 'domains:write',
        'dns:read', 'dns:write', 'backups:read', 'backups:write',
        'servers:read', 'servers:admin', 'secrets:read',
    }
    assert required.issubset(SCOPE_KEYS)
    # Every entry is well-formed.
    for entry in SCOPES:
        assert {'key', 'label', 'group', 'description'} <= set(entry)


# ---------------------------------------------------------------------------
# mask_sensitive
# ---------------------------------------------------------------------------
def test_mask_sensitive_redacts_known_keys():
    data = {
        'name': 'db1',
        'password': 'hunter2',
        'api_key': 'sk_abc',
        'token': 'tok',
        'private_key': '-----BEGIN-----',
        'nested': {'db_secret': 'shh', 'host': 'localhost'},
        'list': [{'credential': 'c'}, {'plain': 'ok'}],
    }
    out = mask_sensitive(data, allowed_scopes=['apps:read'])

    assert out['name'] == 'db1'
    assert out['password'] == MASK
    assert out['api_key'] == MASK
    assert out['token'] == MASK
    assert out['private_key'] == MASK
    assert out['nested']['db_secret'] == MASK
    assert out['nested']['host'] == 'localhost'
    assert out['list'][0]['credential'] == MASK
    assert out['list'][1]['plain'] == 'ok'
    # Original is not mutated.
    assert data['password'] == 'hunter2'


def test_mask_sensitive_respects_secrets_read_scope():
    data = {'password': 'hunter2', 'key_hash': 'deadbeef'}
    out = mask_sensitive(data, allowed_scopes=['secrets:read'])
    assert out['password'] == 'hunter2'
    assert out['key_hash'] == 'deadbeef'


def test_mask_sensitive_full_access_reveals():
    data = {'secret': 's'}
    assert mask_sensitive(data, allowed_scopes=['*'])['secret'] == 's'


def test_mask_sensitive_leaves_none_values():
    data = {'password': None}
    assert mask_sensitive(data, allowed_scopes=['read'])['password'] is None


def test_is_sensitive_key_false_positive_exceptions():
    assert is_sensitive_key('password') is True
    assert is_sensitive_key('is_secret') is False
    assert is_sensitive_key('token_expires_at') is False
    assert is_sensitive_key('name') is False


def test_sensitive_key_patterns_exported():
    assert 'password' in SENSITIVE_KEY_PATTERNS
    assert 'token' in SENSITIVE_KEY_PATTERNS


def test_scopes_for_request_defaults_to_full_access_without_key(app):
    with app.test_request_context('/'):
        # No g.api_key -> JWT/session caller -> full access.
        assert scopes_for_request() == ['*']


def test_scopes_for_request_uses_api_key_scopes(app):
    with app.test_request_context('/'):
        g.api_key = _key_with_scopes(['apps:read', 'dns:read'])
        assert scopes_for_request() == ['apps:read', 'dns:read']
