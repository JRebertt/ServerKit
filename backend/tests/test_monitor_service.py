"""Monitors: the promoted first-class check engine (app/services/monitor_service).

Covers the behaviours that were broken or missing while the engine lived inside
the serverkit-status extension:

- monitors exist without a status page (page_id nullable)
- a network-probed monitor actually opens and resolves an incident; previously
  only the WordPress health-sync path did, so nothing else ever paged
- ping honours the process return code instead of always reporting 'up'
- expected_status / keyword / redirects / verify_tls are wired to the probe
- the scheduler picks up monitors whose interval has elapsed
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app import db
from app.models.status_page import StatusComponent, HealthCheck, StatusIncident
from app.services.monitor_service import (
    MonitorService, _parse_expected_status, _status_matches,
)


def _monitor(**kwargs):
    data = {
        'name': 'Example',
        'check_type': 'http',
        'check_target': 'https://example.test/health',
        'check_interval': 60,
        'retries': 0,
    }
    data.update(kwargs)
    return MonitorService.create(data)


class _Resp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status_code=200, text=''):
        self.status_code = status_code
        self.text = text


# ---------------------------------------------------------------------------
# Expected-status parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('spec,code,expected', [
    ('200-299', 204, True),
    ('200-299', 301, False),
    ('200', 200, True),
    ('200', 201, False),
    ('200,204,301-302', 302, True),
    ('200,204,301-302', 303, False),
    (' 200 - 299 ', 250, True),
    # An unparseable or empty spec falls back to "anything below 400".
    ('', 302, True),
    (None, 500, False),
    ('nonsense', 200, True),
])
def test_status_matches(spec, code, expected):
    assert _status_matches(code, spec) is expected


def test_parse_expected_status_skips_junk_parts():
    assert _parse_expected_status('200, ,oops,300-399') == [(200, 200), (300, 399)]


# ---------------------------------------------------------------------------
# A monitor needs no status page
# ---------------------------------------------------------------------------

def test_monitor_can_exist_without_a_status_page(app):
    monitor = _monitor(name='Pageless')
    assert monitor.id is not None
    assert monitor.page_id is None


def test_create_rejects_unknown_check_type(app):
    with pytest.raises(ValueError):
        _monitor(check_type='carrier-pigeon')


def test_create_rejects_keyword_check_without_keyword(app):
    with pytest.raises(ValueError):
        _monitor(check_type='keyword', keyword=None)


def test_create_requires_a_target_or_a_bound_site(app):
    with pytest.raises(ValueError):
        MonitorService.create({'name': 'Nothing to probe'})


# ---------------------------------------------------------------------------
# HTTP / keyword probes
# ---------------------------------------------------------------------------

def test_http_check_up_within_expected_status(app):
    monitor = _monitor(expected_status='200-299')
    with patch('requests.request', return_value=_Resp(204)), \
            patch.object(MonitorService, '_maybe_attach_certificate'):
        result = MonitorService._perform_check(monitor)
    assert result['status'] == 'up'
    assert result['status_code'] == 204


def test_http_check_outside_expected_status_is_not_up(app):
    """A 301 passes the old "< 400 is fine" rule but fails an explicit 200-299."""
    monitor = _monitor(expected_status='200-299')
    with patch('requests.request', return_value=_Resp(301)), \
            patch.object(MonitorService, '_maybe_attach_certificate'):
        result = MonitorService._perform_check(monitor)
    assert result['status'] == 'down'
    assert '200-299' in result['error']


def test_http_4xx_is_degraded_5xx_is_down(app):
    monitor = _monitor(expected_status='200-299')
    with patch.object(MonitorService, '_maybe_attach_certificate'):
        with patch('requests.request', return_value=_Resp(404)):
            assert MonitorService._perform_check(monitor)['status'] == 'degraded'
        with patch('requests.request', return_value=_Resp(503)):
            assert MonitorService._perform_check(monitor)['status'] == 'down'


def test_http_probe_passes_method_redirects_and_verify(app):
    monitor = _monitor(check_method='head', follow_redirects=False, verify_tls=False,
                       check_timeout=7)
    with patch('requests.request', return_value=_Resp(200)) as req, \
            patch.object(MonitorService, '_maybe_attach_certificate'):
        MonitorService._perform_check(monitor)
    args, kwargs = req.call_args
    assert args[0] == 'HEAD'
    assert kwargs['allow_redirects'] is False
    assert kwargs['verify'] is False
    assert kwargs['timeout'] == 7


def test_keyword_check_down_when_keyword_missing(app):
    """A 200 carrying the wrong page is an outage — the point of a keyword check."""
    monitor = _monitor(check_type='keyword', keyword='Proceed to checkout')
    with patch('requests.request', return_value=_Resp(200, 'Server Error')), \
            patch.object(MonitorService, '_maybe_attach_certificate'):
        result = MonitorService._perform_check(monitor)
    assert result['status'] == 'down'
    assert 'Proceed to checkout' in result['error']


def test_keyword_check_up_when_keyword_present(app):
    monitor = _monitor(check_type='keyword', keyword='status":"ok')
    with patch('requests.request', return_value=_Resp(200, '{"status":"ok"}')), \
            patch.object(MonitorService, '_maybe_attach_certificate'):
        assert MonitorService._perform_check(monitor)['status'] == 'up'


def test_probe_never_raises_on_transport_error(app):
    monitor = _monitor()
    with patch('requests.request', side_effect=OSError('connection refused')):
        result = MonitorService._perform_check(monitor)
    assert result['status'] == 'down'
    assert 'connection refused' in result['error']


# ---------------------------------------------------------------------------
# Ping — the return code used to be ignored entirely
# ---------------------------------------------------------------------------

def test_ping_failure_is_down_not_up(app):
    monitor = _monitor(check_type='ping', check_target='10.255.255.1')
    with patch('app.utils.system.run_command',
               return_value={'returncode': 1, 'stdout': '', 'stderr': '100% packet loss'}):
        result = MonitorService._perform_check(monitor)
    assert result['status'] == 'down'
    assert 'packet loss' in result['error']


def test_ping_success_is_up(app):
    monitor = _monitor(check_type='ping', check_target='127.0.0.1')
    with patch('app.utils.system.run_command',
               return_value={'returncode': 0, 'stdout': '1 received', 'stderr': ''}):
        assert MonitorService._perform_check(monitor)['status'] == 'up'


def test_ping_uses_platform_appropriate_flags(app):
    monitor = _monitor(check_type='ping', check_target='127.0.0.1', check_timeout=3)
    with patch('app.utils.system.run_command',
               return_value={'returncode': 0, 'stdout': '', 'stderr': ''}) as run:
        with patch('app.services.monitor_service.os.name', 'nt'):
            MonitorService._perform_check(monitor)
        assert run.call_args[0][0][:3] == ['ping', '-n', '1']
        with patch('app.services.monitor_service.os.name', 'posix'):
            MonitorService._perform_check(monitor)
        assert run.call_args[0][0][:3] == ['ping', '-c', '1']


# ---------------------------------------------------------------------------
# TLS certificate throttling
# ---------------------------------------------------------------------------

def test_certificate_is_read_when_never_read_before(app):
    monitor = _monitor(check_target='https://example.test/')
    expires = datetime.utcnow() + timedelta(days=40)
    result = {}
    with patch.object(MonitorService, '_probe_certificate',
                      return_value={'cert_issuer': "Let's Encrypt", 'cert_expires_at': expires}) as probe:
        MonitorService._maybe_attach_certificate(monitor, result)
    assert probe.called
    assert result['cert_issuer'] == "Let's Encrypt"
    assert result['cert_checked_at'] is not None


def test_certificate_read_is_throttled_by_its_own_clock(app):
    """Throttling must key on cert_checked_at, not last_check_at: an active
    monitor is probed every 30s, so gating on the probe clock would read the
    certificate once and then never refresh it."""
    monitor = _monitor(check_target='https://example.test/')
    monitor.cert_checked_at = datetime.utcnow() - timedelta(minutes=5)
    # A recent probe must NOT unblock a cert re-read.
    monitor.last_check_at = datetime.utcnow()
    db.session.commit()

    with patch.object(MonitorService, '_probe_certificate') as probe:
        MonitorService._maybe_attach_certificate(monitor, {})
    assert not probe.called

    monitor.cert_checked_at = datetime.utcnow() - timedelta(hours=7)
    db.session.commit()
    with patch.object(MonitorService, '_probe_certificate', return_value={}) as probe:
        MonitorService._maybe_attach_certificate(monitor, {})
    assert probe.called


def test_certificate_failure_still_stamps_the_clock(app):
    """Otherwise an unreachable TLS endpoint is retried on every single probe."""
    monitor = _monitor(check_target='https://example.test/')
    result = {}
    with patch.object(MonitorService, '_probe_certificate', side_effect=OSError('refused')):
        MonitorService._maybe_attach_certificate(monitor, result)
    assert result['cert_checked_at'] is not None


def test_certificate_skipped_for_non_https(app):
    monitor = _monitor(check_target='http://example.test/')
    result = {}
    with patch.object(MonitorService, '_probe_certificate') as probe:
        MonitorService._maybe_attach_certificate(monitor, result)
    assert not probe.called
    assert result == {}


# ---------------------------------------------------------------------------
# Recording: status, retries, uptime, incidents
# ---------------------------------------------------------------------------

def test_record_writes_a_sample_and_moves_status(app):
    monitor = _monitor()
    MonitorService._record(monitor, {'status': 'up', 'response_time': 42, 'status_code': 200})
    assert monitor.status == StatusComponent.STATUS_OPERATIONAL
    assert monitor.last_response_time == 42
    assert monitor.last_check_at is not None
    assert HealthCheck.query.filter_by(component_id=monitor.id).count() == 1


def test_failure_streak_holds_at_degraded_until_retries_exhausted(app):
    monitor = _monitor(retries=2)
    for _ in range(2):
        MonitorService._record(monitor, {'status': 'down', 'error': 'boom'})
        assert monitor.status == StatusComponent.STATUS_DEGRADED
    MonitorService._record(monitor, {'status': 'down', 'error': 'boom'})
    assert monitor.status == StatusComponent.STATUS_MAJOR


def test_success_clears_the_failure_streak(app):
    monitor = _monitor(retries=2)
    MonitorService._record(monitor, {'status': 'down', 'error': 'boom'})
    assert monitor.consecutive_failures == 1
    MonitorService._record(monitor, {'status': 'up', 'response_time': 10})
    assert monitor.consecutive_failures == 0


def test_network_monitor_opens_and_resolves_an_incident(app):
    """The gap this round closes: only the WordPress health path used to do this,
    so a plain URL monitor never produced an incident."""
    monitor = _monitor(name='Checkout API', retries=0)

    MonitorService._record(monitor, {'status': 'down', 'error': 'connection refused'})
    assert monitor.status == StatusComponent.STATUS_MAJOR
    incident = StatusIncident.query.filter_by(component_id=monitor.id).one()
    assert incident.status != 'resolved'
    assert incident.impact == 'major'
    assert 'Checkout API' in incident.title
    # A pageless monitor still gets an incident; it just isn't published.
    assert incident.page_id is None

    MonitorService._record(monitor, {'status': 'up', 'response_time': 12})
    db.session.refresh(incident)
    assert incident.status == 'resolved'
    assert incident.resolved_at is not None


def test_incident_is_not_duplicated_while_already_open(app):
    monitor = _monitor(retries=0)
    for _ in range(3):
        MonitorService._record(monitor, {'status': 'down', 'error': 'boom'})
    assert StatusIncident.query.filter_by(component_id=monitor.id).count() == 1


def test_recovery_through_degraded_still_resolves(app):
    """Resolving on the leaving-major edge, not only on a clean major->up hop."""
    monitor = _monitor(retries=0)
    MonitorService._record(monitor, {'status': 'down', 'error': 'boom'})
    MonitorService._record(monitor, {'status': 'degraded'})
    incident = StatusIncident.query.filter_by(component_id=monitor.id).one()
    assert incident.status == 'resolved'


def test_recompute_uptime_counts_only_up_samples(app):
    monitor = _monitor()
    for status in ('up', 'up', 'up', 'down'):
        db.session.add(HealthCheck(component_id=monitor.id, status=status,
                                   checked_at=datetime.utcnow()))
    db.session.commit()
    MonitorService.recompute_uptime(monitor)
    assert monitor.uptime_24h == 75.0


def test_uptime_days_marks_unwatched_days_as_none(app):
    monitor = _monitor()
    db.session.add(HealthCheck(component_id=monitor.id, status='up',
                               checked_at=datetime.utcnow()))
    db.session.commit()
    days = MonitorService.uptime_days(monitor.id, days=5)
    assert len(days) == 5
    assert days[-1]['state'] == 'up'
    # Days before the monitor existed report "we weren't watching", not 100%.
    assert [d['state'] for d in days[:-1]] == ['none'] * 4


# ---------------------------------------------------------------------------
# Pause + scheduling
# ---------------------------------------------------------------------------

def test_due_monitors_respects_the_interval(app):
    monitor = _monitor(check_interval=60)
    # Never checked -> due immediately.
    assert monitor.id in [m.id for m in MonitorService.due_monitors()]

    monitor.last_check_at = datetime.utcnow()
    db.session.commit()
    assert monitor.id not in [m.id for m in MonitorService.due_monitors()]

    monitor.last_check_at = datetime.utcnow() - timedelta(seconds=61)
    db.session.commit()
    assert monitor.id in [m.id for m in MonitorService.due_monitors()]


def test_due_monitors_skips_paused_and_site_bound(app):
    paused = _monitor(name='Paused')
    MonitorService.set_paused(paused.id, True)
    site_bound = MonitorService.create({
        'name': 'WP site', 'wordpress_site_id': 1, 'check_target': '',
    })
    due_ids = [m.id for m in MonitorService.due_monitors()]
    assert paused.id not in due_ids
    # Site-bound monitors are driven by the health sweep, not the network probe.
    assert site_bound.id not in due_ids


def test_resume_clears_the_failure_streak(app):
    """A monitor paused mid-outage must not instantly re-page on resume."""
    monitor = _monitor(retries=2)
    MonitorService._record(monitor, {'status': 'down', 'error': 'boom'})
    MonitorService.set_paused(monitor.id, True)
    MonitorService.set_paused(monitor.id, False)
    assert monitor.consecutive_failures == 0


def test_next_check_at_is_none_while_paused(app):
    monitor = _monitor()
    MonitorService._record(monitor, {'status': 'up', 'response_time': 5})
    assert monitor.next_check_at is not None
    MonitorService.set_paused(monitor.id, True)
    assert monitor.next_check_at is None


# ---------------------------------------------------------------------------
# Deletion + stats
# ---------------------------------------------------------------------------

def test_delete_unlinks_and_resolves_incidents(app):
    monitor = _monitor(retries=0)
    MonitorService._record(monitor, {'status': 'down', 'error': 'boom'})
    incident = StatusIncident.query.filter_by(component_id=monitor.id).one()

    assert MonitorService.delete(monitor.id) is True
    db.session.refresh(incident)
    assert incident.component_id is None
    assert incident.status == 'resolved'


def test_stats_counts_by_state(app):
    up = _monitor(name='Up one')
    MonitorService._record(up, {'status': 'up', 'response_time': 5})
    down = _monitor(name='Down one', retries=0)
    MonitorService._record(down, {'status': 'down', 'error': 'boom'})
    paused = _monitor(name='Paused one')
    MonitorService.set_paused(paused.id, True)

    stats = MonitorService.stats()
    assert stats['total'] == 3
    assert stats['paused'] == 1
    assert stats['operational'] == 1
    assert stats['down'] == 1


# ---------------------------------------------------------------------------
# Managed-site bridge
# ---------------------------------------------------------------------------

def test_health_sync_reaches_major_on_the_first_unhealthy_verdict(app):
    """A health verdict is authoritative, not a flaky network blip, so it should
    not have to wait out the retry streak."""
    monitor = MonitorService.create({
        'name': 'Bound site', 'wordpress_site_id': 1, 'check_target': '', 'retries': 3,
    })
    MonitorService.sync_component_from_health(monitor, 'unhealthy')
    assert monitor.status == StatusComponent.STATUS_MAJOR
    assert StatusIncident.query.filter_by(component_id=monitor.id).count() == 1


def test_health_sync_ignores_unknown_verdict(app):
    monitor = MonitorService.create({
        'name': 'Bound site', 'wordpress_site_id': 1, 'check_target': '',
    })
    assert MonitorService.sync_component_from_health(monitor, 'unknown') is None
    assert HealthCheck.query.filter_by(component_id=monitor.id).count() == 0


# ---------------------------------------------------------------------------
# Scheduler handler
# ---------------------------------------------------------------------------

def test_monitors_do_not_depend_on_the_status_extension():
    """The whole point of the promotion: watching a site must keep working on a
    lean panel with serverkit-status uninstalled.

    Walks the AST rather than grepping the source so the modules' own prose about
    the extension doesn't trip it — only real imports and calls count.
    """
    import ast
    import inspect
    from app.services import monitor_service
    from app.api import monitors as monitors_api

    banned_calls = {'get_installed_extension_attr'}
    banned_names = {'StatusPageService'}

    for module in (monitor_service, monitors_api):
        tree = ast.parse(inspect.getsource(module))
        imported = set()
        called = set()
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node, ast.Name):
                used.add(node.id)

        assert not any('plugin' in name for name in imported), \
            f'{module.__name__} imports the plugin loader: {imported}'
        assert not (called & banned_calls), f'{module.__name__} calls {called & banned_calls}'
        assert not (used & banned_names), f'{module.__name__} references {used & banned_names}'


def test_monitor_routes_are_core(app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert '/api/v1/monitors/' in rules or '/api/v1/monitors' in rules
    assert '/api/v1/monitors/<int:monitor_id>/check' in rules
    assert '/api/v1/monitors/incidents' in rules


def test_monitor_sweep_is_registered_as_a_builtin():
    from app.jobs.builtin_handlers import _BUILTINS
    kinds = {kind for kind, _fn, _name, _interval, _delay in _BUILTINS}
    assert 'builtin.monitor_check' in kinds


def test_monitor_sweep_polls_due_monitors(app):
    from app.jobs.builtin_handlers import run_monitor_checks
    monitor = _monitor()
    with patch('requests.request', return_value=_Resp(200)), \
            patch.object(MonitorService, '_maybe_attach_certificate'):
        run_monitor_checks()
    assert monitor.last_check_at is not None
    assert HealthCheck.query.filter_by(component_id=monitor.id).count() == 1


def test_monitor_sweep_survives_one_bad_monitor(app):
    from app.jobs.builtin_handlers import run_monitor_checks
    _monitor(name='First')
    _monitor(name='Second')
    with patch.object(MonitorService, 'run_check',
                      side_effect=[RuntimeError('boom'), None]) as run:
        run_monitor_checks()  # must not raise
    assert run.call_count == 2
