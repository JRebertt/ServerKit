"""Tests for the shared $select/$filter/$orderby/$skip/$top layer."""

import pytest

from app.api._query import (
    QueryParseError, apply_query, parse_filter, parse_orderby, parse_select,
)
from app.models import Application


class FakeRequest:
    def __init__(self, **args):
        self.args = args


@pytest.fixture
def sample_app(app):
    """One persisted Application — to_dict needs a real row to walk."""
    from app import db
    from app.models import User
    from werkzeug.security import generate_password_hash
    with app.app_context():
        # applications.user_id is NOT NULL, so the row needs an owner.
        owner = User.query.first() or User(
            email='probe@t.local', username='probe',
            password_hash=generate_password_hash('x'), role='admin', is_active=True)
        if owner.id is None:
            db.session.add(owner)
            db.session.commit()
        row = Application(name='probe-app', app_type='static', status='stopped',
                          user_id=owner.id)
        db.session.add(row)
        db.session.commit()
        db.session.refresh(row)
        yield row


# ---------------------------------------------------------------- $filter

def test_filter_none_when_absent(app):
    with app.app_context():
        assert parse_filter('', Application) is None
        assert parse_filter(None, Application) is None


def test_filter_comparison_operators(app):
    with app.app_context():
        for op in ('eq', 'ne', 'gt', 'ge', 'lt', 'le'):
            assert parse_filter(f"name {op} 'demo'", Application) is not None


def test_filter_rejects_unknown_field(app):
    """The mapped-column set is the allowlist — not a getattr into the model."""
    with app.app_context():
        with pytest.raises(QueryParseError):
            parse_filter("query eq 'x'", Application)
        with pytest.raises(QueryParseError):
            parse_filter("__class__ eq 'x'", Application)


def test_filter_string_functions(app):
    with app.app_context():
        for expr in ("contains(name, 'ap')", "startswith(name, 'a')",
                     "endswith(name, 'p')", 'notempty(name)'):
            assert parse_filter(expr, Application) is not None


def test_filter_date_helpers(app):
    with app.app_context():
        assert parse_filter("date(created_at, '2026-01-02')", Application) is not None
        assert parse_filter('daysAgo(created_at, 7)', Application) is not None
        with pytest.raises(QueryParseError):
            parse_filter("date(created_at, 'nope')", Application)
        with pytest.raises(QueryParseError):
            parse_filter('daysAgo(created_at, soon)', Application)


def test_filter_refuses_mixed_combiners(app):
    """`a and b or c` has no unambiguous reading; guessing one is worse."""
    with app.app_context():
        with pytest.raises(QueryParseError):
            parse_filter("name eq 'a' and status eq 'b' or port eq 1", Application)


def test_filter_malformed_condition(app):
    with app.app_context():
        with pytest.raises(QueryParseError):
            parse_filter('name', Application)


# --------------------------------------------------------------- $orderby

def test_orderby_defaults_to_asc_and_accepts_desc(app):
    with app.app_context():
        assert parse_orderby('name', Application)
        assert len(parse_orderby('name asc, created_at desc', Application)) == 2
        with pytest.raises(QueryParseError):
            parse_orderby('name sideways', Application)
        with pytest.raises(QueryParseError):
            parse_orderby('nope asc', Application)


# ---------------------------------------------------------------- $select

def test_select_none_means_everything(app):
    with app.app_context():
        assert parse_select('', Application) is None


def test_select_always_includes_the_primary_key(app):
    """A row the client cannot identify is not useful; every UI keys on id."""
    with app.app_context():
        assert parse_select('name', Application) == {'name', 'id'}


def test_select_accepts_declared_derived_fields(app):
    with app.app_context():
        fields = parse_select('name,project_name,image_scan', Application,
                              extra=Application.DERIVED_FIELDS)
        assert {'name', 'project_name', 'image_scan', 'id'} == fields


def test_select_rejects_underived_unknown_field(app):
    with app.app_context():
        with pytest.raises(QueryParseError):
            parse_select('name,not_a_field', Application)


# ------------------------------------------------------------- apply_query

def test_apply_query_is_a_noop_without_params(app):
    """Adoption must not change any existing caller's response."""
    with app.app_context():
        result = apply_query(Application.query, Application, FakeRequest())
        assert result.fields is None
        assert result.total is None
        assert result.top is None


def test_apply_query_caps_top(app):
    with app.app_context():
        result = apply_query(Application.query, Application, FakeRequest(**{'$top': '99999'}))
        assert result.top == 500


def test_apply_query_rejects_non_integer_paging(app):
    with app.app_context():
        with pytest.raises(QueryParseError):
            apply_query(Application.query, Application, FakeRequest(**{'$top': 'ten'}))
        with pytest.raises(QueryParseError):
            apply_query(Application.query, Application, FakeRequest(**{'$skip': '-1'}))


def test_apply_query_counts_before_paging(app):
    """`total` must be the unpaged count, or "12 of 340" reads "12 of 12"."""
    with app.app_context():
        result = apply_query(Application.query, Application, FakeRequest(**{'$top': '1'}))
        assert result.total is not None
        assert result.top == 1


# ------------------------------------------------- to_dict field narrowing

def test_to_dict_full_payload_is_unchanged_by_default(app, sample_app):
    with app.app_context():
        data = sample_app.to_dict()
        for key in ('id', 'name', 'project_name', 'server_name', 'domains',
                    'image_scan', 'image_update', 'sleep', 'has_linked_app',
                    'ingress_plane'):
            assert key in data


def test_to_dict_narrows_to_requested_fields(app, sample_app):
    """The point of $select: the expensive derived fields are not computed."""
    with app.app_context():
        data = sample_app.to_dict(fields={'id', 'name'})
        assert set(data) == {'id', 'name'}
        for skipped in ('image_scan', 'image_update', 'sleep', 'domains',
                        'project_name', 'server_name'):
            assert skipped not in data


def test_to_dict_can_opt_into_one_derived_field(app, sample_app):
    with app.app_context():
        data = sample_app.to_dict(fields={'id', 'name', 'image_scan'})
        assert set(data) == {'id', 'name', 'image_scan'}


# --------------------------------------------- Server: the same narrowing

def test_server_to_dict_is_unchanged_by_default(app):
    from app import db
    from app.models.server import Server
    with app.app_context():
        row = Server(id='probe-srv', name='probe')
        db.session.add(row)
        db.session.commit()
        data = row.to_dict()
        assert 'onboarding_progress' in data
        assert 'group_name' in data


def test_server_to_dict_skips_the_expensive_derived_fields(app):
    """onboarding_progress alone is ~29% of a server row and is read by exactly
    one screen; group_name is a relationship load."""
    from app import db
    from app.models.server import Server
    with app.app_context():
        row = Server(id='probe-srv2', name='probe2')
        db.session.add(row)
        db.session.commit()
        data = row.to_dict(fields={'id', 'name'})
        assert set(data) == {'id', 'name'}
        assert 'onboarding_progress' not in data
        assert 'group_name' not in data


def test_server_select_accepts_its_derived_fields(app):
    from app.models.server import Server
    with app.app_context():
        fields = parse_select('name,group_name', Server, extra=Server.DERIVED_FIELDS)
        assert fields == {'name', 'group_name', 'id'}
