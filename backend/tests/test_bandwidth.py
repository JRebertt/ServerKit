"""Tests for per-domain bandwidth accounting (BandwidthService + API).

Covers: access-log parsing (combined + vhost-prefixed, bad lines skipped),
per-domain sums with app attribution via Domain rows, upsert idempotency,
rotated-file spillover, series/monthly math across a month boundary,
retention pruning, and the /api/v1/bandwidth surface.
"""
from datetime import date, timedelta

import pytest

from app import db
# Ensure the table is on db.Model metadata before the app fixture's
# create_all() (production wiring imports it in app/models/__init__.py).
import app.models.site_bandwidth  # noqa: F401
from app.services.bandwidth_service import (
    BandwidthService,
    RETENTION_DAYS,
    _day_prefix,
)

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


# ── helpers ──────────────────────────────────────────────────────────────────

def _tl(day):
    """$time_local for noon of ``day``."""
    return f'{_day_prefix(day)}:12:00:00 +0000'


def _combined(day, nbytes, path='/index.html', ip='203.0.113.7'):
    return (f'{ip} - - [{_tl(day)}] "GET {path} HTTP/1.1" 200 {nbytes} '
            f'"-" "Mozilla/5.0"')


def _vhost(day, host, nbytes, path='/index.html'):
    return (f'{host}:443 198.51.100.9 - - [{_tl(day)}] '
            f'"GET {path} HTTP/1.1" 200 {nbytes} "-" "curl/8"')


def _owner_id():
    from app.models import User
    from werkzeug.security import generate_password_hash
    user = User.query.filter_by(username='bwowner').first()
    if user is None:
        user = User(
            email='bwowner@test.local', username='bwowner',
            password_hash=generate_password_hash('x'),
            role=User.ROLE_ADMIN, is_active=True,
        )
        db.session.add(user)
        db.session.flush()
    return user.id


def _make_app(name, domains=(), primary=None):
    from app.models.application import Application
    from app.models.domain import Domain
    app_row = Application(name=name, app_type='php', user_id=_owner_id())
    db.session.add(app_row)
    db.session.flush()
    for dom in domains:
        db.session.add(Domain(
            name=dom, application_id=app_row.id,
            is_primary=(dom == (primary or (domains[0] if domains else None))),
        ))
    db.session.commit()
    return app_row


@pytest.fixture
def day():
    return date.today() - timedelta(days=1)


# ── log parsing ──────────────────────────────────────────────────────────────

def test_parse_combined_lines_sums_and_day_filter(tmp_path, day):
    other_day = day - timedelta(days=1)
    log = tmp_path / 'a.access.log'
    log.write_text('\n'.join([
        _combined(day, 1000),
        _combined(day, 250),
        _combined(other_day, 999999),  # wrong day: excluded
    ]) + '\n')
    per_host, plain, skipped = BandwidthService.parse_log_file(str(log), day)
    assert per_host == {}
    assert plain == [1250, 2]
    assert skipped == 0


def test_parse_vhost_prefixed_lines_split_by_host(tmp_path, day):
    log = tmp_path / 'access.log'
    log.write_text('\n'.join([
        _vhost(day, 'alpha.test', 100),
        _vhost(day, 'ALPHA.test', 50),      # case-normalized
        _vhost(day, 'beta.test', 7),
    ]) + '\n')
    per_host, plain, skipped = BandwidthService.parse_log_file(str(log), day)
    assert per_host == {'alpha.test': [150, 2], 'beta.test': [7, 1]}
    assert plain == [0, 0]
    assert skipped == 0


def test_parse_skips_and_counts_bad_lines(tmp_path, day):
    log = tmp_path / 'a.access.log'
    log.write_text('\n'.join([
        'utter garbage not a log line',
        _combined(day, 10),
        'another bad one [nope',
    ]) + '\n')
    _hosts, plain, skipped = BandwidthService.parse_log_file(str(log), day)
    assert plain == [10, 1]
    assert skipped == 2


def test_parse_missing_file_is_clean_zero(tmp_path, day):
    per_host, plain, skipped = BandwidthService.parse_log_file(
        str(tmp_path / 'nope.access.log'), day)
    assert (per_host, plain, skipped) == ({}, [0, 0], 0)


def test_parse_dash_bytes_counts_request_zero_bytes(tmp_path, day):
    log = tmp_path / 'a.access.log'
    line = _combined(day, 100).replace(' 200 100 ', ' 304 - ')
    log.write_text(line + '\n')
    _hosts, plain, skipped = BandwidthService.parse_log_file(str(log), day)
    assert plain == [0, 1]
    assert skipped == 0


# ── aggregation ──────────────────────────────────────────────────────────────

def test_aggregate_per_site_log_attributes_primary_domain(app, tmp_path, day):
    from app.models.site_bandwidth import SiteBandwidthDaily
    site = _make_app('mysite', domains=('mysite.com', 'www.mysite.com'),
                     primary='mysite.com')
    (tmp_path / 'mysite.access.log').write_text('\n'.join([
        _combined(day, 500),
        _combined(day, 300),
    ]) + '\n')

    result = BandwidthService.aggregate(day=day, log_dir=str(tmp_path))
    assert result['requests'] == 2
    assert result['bytes_sent'] == 800

    rows = SiteBandwidthDaily.query.all()
    assert len(rows) == 1
    assert rows[0].domain == 'mysite.com'
    assert rows[0].app_id == site.id
    assert rows[0].bytes_sent == 800
    assert rows[0].requests == 2


def test_aggregate_rerun_overwrites_not_duplicates(app, tmp_path, day):
    from app.models.site_bandwidth import SiteBandwidthDaily
    _make_app('mysite', domains=('mysite.com',))
    log = tmp_path / 'mysite.access.log'
    log.write_text(_combined(day, 100) + '\n')
    BandwidthService.aggregate(day=day, log_dir=str(tmp_path))

    # Log grew; re-run the same day.
    log.write_text(_combined(day, 100) + '\n' + _combined(day, 60) + '\n')
    BandwidthService.aggregate(day=day, log_dir=str(tmp_path))

    rows = SiteBandwidthDaily.query.filter_by(day=day).all()
    assert len(rows) == 1
    assert rows[0].bytes_sent == 160
    assert rows[0].requests == 2


def test_aggregate_default_log_vhost_split_attributes_via_domain_rows(
        app, tmp_path, day):
    from app.models.site_bandwidth import SiteBandwidthDaily
    site = _make_app('alpha', domains=('alpha.test',))
    (tmp_path / 'access.log').write_text('\n'.join([
        _vhost(day, 'alpha.test', 400),
        _vhost(day, 'unknown.example', 9),   # no Domain row: app_id None
        _combined(day, 12345),               # unattributable: dropped
    ]) + '\n')

    BandwidthService.aggregate(day=day, log_dir=str(tmp_path))

    known = SiteBandwidthDaily.query.filter_by(domain='alpha.test').one()
    assert known.app_id == site.id
    assert known.bytes_sent == 400
    unknown = SiteBandwidthDaily.query.filter_by(domain='unknown.example').one()
    assert unknown.app_id is None
    assert unknown.bytes_sent == 9
    # The plain (host-less) default-log line must not create a row.
    assert SiteBandwidthDaily.query.count() == 2


def test_aggregate_reads_rotated_file_spillover(app, tmp_path, day):
    from app.models.site_bandwidth import SiteBandwidthDaily
    _make_app('mysite', domains=('mysite.com',))
    # Target day's traffic split across the live log and its rotation.
    (tmp_path / 'mysite.access.log').write_text(_combined(day, 70) + '\n')
    (tmp_path / 'mysite.access.log.1').write_text(_combined(day, 30) + '\n')

    BandwidthService.aggregate(day=day, log_dir=str(tmp_path))
    row = SiteBandwidthDaily.query.filter_by(domain='mysite.com').one()
    assert row.bytes_sent == 100
    assert row.requests == 2


def test_aggregate_no_logs_clean_zero(app, tmp_path, day):
    """Windows/dev boxes with no nginx logs: clean empty result, no rows."""
    from app.models.site_bandwidth import SiteBandwidthDaily
    _make_app('mysite', domains=('mysite.com',))
    result = BandwidthService.aggregate(day=day, log_dir=str(tmp_path))
    assert result['domains'] == 0
    assert result['bytes_sent'] == 0
    assert SiteBandwidthDaily.query.count() == 0


def test_aggregate_app_without_domains_uses_app_name(app, tmp_path, day):
    from app.models.site_bandwidth import SiteBandwidthDaily
    site = _make_app('barebones')
    (tmp_path / 'barebones.access.log').write_text(_combined(day, 42) + '\n')
    BandwidthService.aggregate(day=day, log_dir=str(tmp_path))
    row = SiteBandwidthDaily.query.one()
    assert row.domain == 'barebones'
    assert row.app_id == site.id


def test_aggregate_prunes_beyond_retention(app, tmp_path, day):
    from app.models.site_bandwidth import SiteBandwidthDaily
    old_day = date.today() - timedelta(days=RETENTION_DAYS + 5)
    keep_day = date.today() - timedelta(days=RETENTION_DAYS - 5)
    db.session.add(SiteBandwidthDaily(domain='old.test', day=old_day,
                                      bytes_sent=1, requests=1))
    db.session.add(SiteBandwidthDaily(domain='keep.test', day=keep_day,
                                      bytes_sent=1, requests=1))
    db.session.commit()

    result = BandwidthService.aggregate(day=day, log_dir=str(tmp_path))
    assert result['pruned'] == 1
    domains = {r.domain for r in SiteBandwidthDaily.query.all()}
    assert domains == {'keep.test'}


def test_aggregate_accepts_iso_day_string(app, tmp_path):
    day = date.today() - timedelta(days=3)
    result = BandwidthService.aggregate(day=day.isoformat(),
                                        log_dir=str(tmp_path))
    assert result['day'] == day.isoformat()


# ── read side: series / monthly_total ────────────────────────────────────────

def _seed_row(domain, day, nbytes, requests=1, app_id=None):
    from app.models.site_bandwidth import SiteBandwidthDaily
    db.session.add(SiteBandwidthDaily(
        app_id=app_id, domain=domain, day=day,
        bytes_sent=nbytes, requests=requests))
    db.session.commit()


def test_series_zero_fills_and_sums_domains(app):
    site = _make_app('mysite', domains=('a.test', 'b.test'))
    today = date.today()
    _seed_row('a.test', today, 100, requests=2, app_id=site.id)
    _seed_row('b.test', today, 50, requests=1, app_id=site.id)
    _seed_row('a.test', today - timedelta(days=2), 30, app_id=site.id)

    series = BandwidthService.series(app_id=site.id, days=7)
    assert len(series) == 7
    assert series[-1] == {'day': today.isoformat(),
                          'bytes_sent': 150, 'requests': 3}
    assert series[-3]['bytes_sent'] == 30
    assert series[0] == {'day': (today - timedelta(days=6)).isoformat(),
                         'bytes_sent': 0, 'requests': 0}


def test_monthly_total_excludes_previous_month(app):
    site = _make_app('mysite', domains=('a.test',))
    today = date.today()
    first = today.replace(day=1)
    prev_month_day = first - timedelta(days=1)
    _seed_row('a.test', first, 500, app_id=site.id)
    if today != first:
        _seed_row('a.test', today, 250, app_id=site.id)
        expected = 750
    else:
        expected = 500
    _seed_row('a.test', prev_month_day, 100000, app_id=site.id)

    assert BandwidthService.monthly_total(site.id) == expected
    # The series across the boundary still sees both months.
    days_span = (today - prev_month_day).days + 1
    series = BandwidthService.series(app_id=site.id, days=days_span)
    assert series[0]['bytes_sent'] == 100000


def test_overview_shapes_per_app(app):
    site = _make_app('mysite', domains=('a.test',))
    other = _make_app('quiet', domains=('q.test',))
    today = date.today()
    _seed_row('a.test', today, 900, requests=4, app_id=site.id)

    data = BandwidthService.overview(days=30)
    assert site.id in data
    assert other.id not in data          # no traffic → omitted
    entry = data[site.id]
    assert entry['month_bytes'] == 900
    assert len(entry['series30']) == 30
    assert entry['series30'][-1] == 900
    assert sum(entry['series30'][:-1]) == 0


# ── job plumbing ─────────────────────────────────────────────────────────────

def test_register_jobs_registers_handler(app):
    from app.jobs import registry
    BandwidthService.register_jobs()
    from app.services.bandwidth_service import BANDWIDTH_JOB_KIND
    assert BANDWIDTH_JOB_KIND in registry.registered_kinds()


# ── API ──────────────────────────────────────────────────────────────────────

def _register_bp(app):
    from app.api.bandwidth import bandwidth_bp
    if 'bandwidth' not in app.blueprints:
        app.register_blueprint(bandwidth_bp, url_prefix='/api/v1/bandwidth')


def test_api_requires_auth(app, client):
    _register_bp(app)
    resp = client.get('/api/v1/bandwidth/apps')
    assert resp.status_code == 401


def test_api_apps_overview_shape(app, client, auth_headers):
    _register_bp(app)
    site = _make_app('mysite', domains=('a.test',))
    _seed_row('a.test', date.today(), 1234, requests=3, app_id=site.id)

    resp = client.get('/api/v1/bandwidth/apps', headers=auth_headers)
    assert resp.status_code == 200
    payload = resp.get_json()
    entry = payload['apps'][str(site.id)]
    assert entry['month_bytes'] == 1234
    assert len(entry['series30']) == 30


def test_api_single_app_series(app, client, auth_headers):
    _register_bp(app)
    site = _make_app('mysite', domains=('a.test',))
    _seed_row('a.test', date.today(), 77, app_id=site.id)

    resp = client.get(f'/api/v1/bandwidth/apps/{site.id}?days=14',
                      headers=auth_headers)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['app_id'] == site.id
    assert payload['days'] == 14
    assert len(payload['series']) == 14
    assert payload['series'][-1]['bytes_sent'] == 77
    assert payload['month_bytes'] == 77


def test_api_aggregate_runs_and_rejects_bad_day(app, client, auth_headers,
                                                tmp_path, monkeypatch):
    _register_bp(app)
    from app.services.nginx_service import NginxService
    monkeypatch.setattr(NginxService, 'LOG_DIR', str(tmp_path))

    resp = client.post('/api/v1/bandwidth/aggregate', headers=auth_headers,
                       json={})
    assert resp.status_code == 200
    assert 'bytes_sent' in resp.get_json()

    bad = client.post('/api/v1/bandwidth/aggregate', headers=auth_headers,
                      json={'day': 'not-a-date'})
    assert bad.status_code == 400
    assert 'error' in bad.get_json()
