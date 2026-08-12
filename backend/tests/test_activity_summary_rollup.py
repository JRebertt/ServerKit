"""Tests for /admin/activity/summary's grouped day rollup.

The endpoint used to issue one COUNT per day, twice (90 days x 2 series = 180
sequential queries) purely to discover that most days were empty. It now issues
one GROUP BY per series and fills the gaps in Python, so these tests pin both
halves: the query count, and the zero-fill that keeps the response identical.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app import db
from app.api.admin import _daily_action_counts, _day_key
from app.models import AuditLog, User

DAYS = 90


@pytest.fixture
def admin_and_logs(app):
    """One admin plus audit rows on exactly three known days inside the window."""
    from werkzeug.security import generate_password_hash

    with app.app_context():
        user = User(email='activity@t.local', username='activityadmin',
                    password_hash=generate_password_hash('x'),
                    role=User.ROLE_ADMIN, is_active=True)
        db.session.add(user)
        db.session.commit()

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0,
                                                microsecond=0)
        # today (x3), 5 days ago (x1), 40 days ago (x2). Everything else empty.
        plan = [(0, 3), (5, 1), (40, 2)]
        for days_ago, count in plan:
            stamp = today_start - timedelta(days=days_ago) + timedelta(hours=6)
            for _ in range(count):
                db.session.add(AuditLog(action='user.login', user_id=user.id,
                                        created_at=stamp))
        db.session.commit()
        yield {'user_id': user.id, 'today_start': today_start, 'plan': plan}


class _QueryCounter:
    """Counts statements that actually touch audit_logs."""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0

    def _hook(self, conn, cursor, statement, params, context, executemany):
        if 'audit_logs' in statement.lower():
            self.count += 1

    def __enter__(self):
        event.listen(self.engine, 'before_cursor_execute', self._hook)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, 'before_cursor_execute', self._hook)
        return False


# ------------------------------------------------------------- zero-fill

class TestZeroFill:
    def test_series_length_matches_the_window(self, app, admin_and_logs):
        window_start = admin_and_logs['today_start'] - timedelta(days=DAYS - 1)
        with app.app_context():
            series = _daily_action_counts(window_start, DAYS)
        assert len(series) == DAYS

    def test_empty_days_still_appear_as_zero(self, app, admin_and_logs):
        """The whole point of the Python-side fill: a day with no rows is still
        a point on the chart, not a missing entry."""
        today_start = admin_and_logs['today_start']
        window_start = today_start - timedelta(days=DAYS - 1)
        with app.app_context():
            series = _daily_action_counts(window_start, DAYS)

        by_date = {row['date']: row['count'] for row in series}
        # 3 days carry rows; the other 87 must be present with count 0.
        assert sum(1 for c in by_date.values() if c == 0) == DAYS - 3
        assert by_date[today_start.strftime('%Y-%m-%d')] == 3
        assert by_date[(today_start - timedelta(days=5)).strftime('%Y-%m-%d')] == 1
        assert by_date[(today_start - timedelta(days=40)).strftime('%Y-%m-%d')] == 2
        # A day we never wrote to is present and zero.
        assert by_date[(today_start - timedelta(days=6)).strftime('%Y-%m-%d')] == 0

    def test_dates_are_contiguous_and_ascending(self, app, admin_and_logs):
        window_start = admin_and_logs['today_start'] - timedelta(days=DAYS - 1)
        with app.app_context():
            series = _daily_action_counts(window_start, DAYS)

        dates = [row['date'] for row in series]
        assert dates == sorted(dates)
        assert dates[0] == window_start.strftime('%Y-%m-%d')
        assert dates[-1] == admin_and_logs['today_start'].strftime('%Y-%m-%d')
        assert len(set(dates)) == DAYS

    def test_row_shape_is_date_and_count_only(self, app, admin_and_logs):
        window_start = admin_and_logs['today_start'] - timedelta(days=DAYS - 1)
        with app.app_context():
            series = _daily_action_counts(window_start, DAYS)
        assert all(set(row) == {'date', 'count'} for row in series)
        assert all(isinstance(row['count'], int) for row in series)

    def test_empty_table_is_ninety_zeroes(self, app):
        window_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0) - timedelta(days=DAYS - 1)
        with app.app_context():
            series = _daily_action_counts(window_start, DAYS)
        assert len(series) == DAYS
        assert all(row['count'] == 0 for row in series)

    def test_rows_outside_the_window_are_excluded(self, app, admin_and_logs):
        """The range filter is applied once for the whole window; a row just
        outside it must not leak into the first bucket."""
        today_start = admin_and_logs['today_start']
        with app.app_context():
            db.session.add(AuditLog(action='user.login',
                                    user_id=admin_and_logs['user_id'],
                                    created_at=today_start - timedelta(days=200)))
            db.session.commit()
            series = _daily_action_counts(today_start - timedelta(days=DAYS - 1), DAYS)
        assert sum(row['count'] for row in series) == 6  # 3 + 1 + 2

    def test_extra_filter_narrows_the_series(self, app, admin_and_logs):
        today_start = admin_and_logs['today_start']
        with app.app_context():
            other = User(email='other@t.local', username='otheruser',
                         password_hash='x', role=User.ROLE_ADMIN, is_active=True)
            db.session.add(other)
            db.session.commit()
            db.session.add(AuditLog(action='user.login', user_id=other.id,
                                    created_at=today_start + timedelta(hours=2)))
            db.session.commit()

            everyone = _daily_action_counts(today_start - timedelta(days=DAYS - 1), DAYS)
            just_them = _daily_action_counts(
                today_start - timedelta(days=DAYS - 1), DAYS,
                AuditLog.user_id == other.id)

        assert sum(r['count'] for r in everyone) == 7
        assert sum(r['count'] for r in just_them) == 1
        assert len(just_them) == DAYS  # still zero-filled


# ---------------------------------------------------------- query volume

class TestQueryVolume:
    def test_one_grouped_query_per_series(self, app, admin_and_logs):
        """90 sequential COUNTs -> 1 GROUP BY. This is the whole round."""
        window_start = admin_and_logs['today_start'] - timedelta(days=DAYS - 1)
        with app.app_context():
            with _QueryCounter(db.engine) as counter:
                _daily_action_counts(window_start, DAYS)
            assert counter.count == 1

    def test_endpoint_is_no_longer_linear_in_days(self, app, client, admin_and_logs):
        """End to end: the summary route did 180 audit_logs queries for its two
        90-day series alone. Bound it well below that."""
        from flask_jwt_extended import create_access_token

        with app.app_context():
            token = create_access_token(identity=admin_and_logs['user_id'])
            with _QueryCounter(db.engine) as counter:
                response = client.get('/api/v1/admin/activity/summary',
                                      headers={'Authorization': f'Bearer {token}'})
            queries = counter.count

        assert response.status_code == 200
        # 4 aggregates + 2 grouped series = 6; leave headroom for the audit
        # middleware without ever tolerating a per-day loop.
        assert queries <= 12, f'{queries} audit_logs queries — per-day loop is back?'


# --------------------------------------------------------- endpoint shape

class TestEndpointShape:
    def test_payload_keys_and_series_lengths(self, app, client, admin_and_logs):
        from flask_jwt_extended import create_access_token

        with app.app_context():
            token = create_access_token(identity=admin_and_logs['user_id'])
        response = client.get('/api/v1/admin/activity/summary',
                              headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 200
        payload = response.get_json()

        assert set(payload) == {
            'active_users_today', 'actions_this_week', 'total_users',
            'top_users', 'daily_counts', 'top_user_daily',
        }
        assert len(payload['daily_counts']) == DAYS
        # There IS a top user here, so the second series is populated too.
        assert len(payload['top_user_daily']) == DAYS
        assert all(set(row) == {'date', 'count'} for row in payload['daily_counts'])
        assert payload['daily_counts'][-1]['count'] == 3
        assert payload['top_users'][0]['username'] == 'activityadmin'
        assert set(payload['top_users'][0]) == {'user_id', 'username', 'action_count'}

    def test_top_user_daily_is_empty_when_there_is_no_top_user(self, app, client):
        """Preserved edge case: no audit rows at all -> [] , not 90 zeroes."""
        from flask_jwt_extended import create_access_token
        from werkzeug.security import generate_password_hash

        with app.app_context():
            user = User(email='lonely@t.local', username='lonelyadmin',
                        password_hash=generate_password_hash('x'),
                        role=User.ROLE_ADMIN, is_active=True)
            db.session.add(user)
            db.session.commit()
            token = create_access_token(identity=user.id)

        response = client.get('/api/v1/admin/activity/summary',
                              headers={'Authorization': f'Bearer {token}'})
        payload = response.get_json()
        assert payload['top_users'] == []
        assert payload['top_user_daily'] == []
        assert len(payload['daily_counts']) == DAYS


# ------------------------------------------------------ dialect portability

class TestDayKeyPortability:
    """SQLite's date() returns 'YYYY-MM-DD'; PostgreSQL's returns a date object.
    Both have to reduce to the same key or the zero-fill silently misses."""

    def test_string_from_sqlite(self):
        assert _day_key('2026-08-12') == '2026-08-12'

    def test_date_object_from_postgres(self):
        from datetime import date as _date
        assert _day_key(_date(2026, 8, 12)) == '2026-08-12'

    def test_datetime_is_truncated(self):
        assert _day_key(datetime(2026, 8, 12, 13, 45)) == '2026-08-12'

    def test_string_with_time_is_truncated(self):
        assert _day_key('2026-08-12 13:45:00.000000') == '2026-08-12'

    def test_none_is_none(self):
        assert _day_key(None) is None
