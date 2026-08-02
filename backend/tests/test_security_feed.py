"""Tests for the security-advisory feed check (security_feed_service)."""
import pytest

from app import db as _db
from app.models.system_settings import SystemSettings
from app.services import security_feed_service as sfs

FEED = [
    {
        'ghsa': 'GHSA-test-0001',
        'cve': None,
        'severity': 'high',
        'summary': 'Test advisory one',
        'affected': '< 1.7.68',
        'fixed_in': '1.7.68',
        'url': 'https://example.test/GHSA-test-0001',
        'published_at': '2026-08-01T00:00:00Z',
        'post_fix_action': 'Rotate JWT_SECRET_KEY.',
    },
    {
        'ghsa': 'GHSA-test-0002',
        'cve': None,
        'severity': 'medium',
        'summary': 'Test advisory two',
        'affected': '>= 1.5.0, < 1.6.0',
        'fixed_in': '1.6.0',
        'url': 'https://example.test/GHSA-test-0002',
        'published_at': '2026-08-01T00:00:00Z',
        'post_fix_action': None,
    },
]


@pytest.fixture
def feed_env(app, monkeypatch):
    """Feed stub + notification recorder, inside an app context."""
    sent = []
    monkeypatch.setattr(sfs, 'fetch_feed', lambda: FEED)
    from app.notifications.service import NotificationBusService
    monkeypatch.setattr(
        NotificationBusService, 'send',
        classmethod(lambda cls, event, to, data=None, **kw: sent.append(
            {'event': event, 'to': to, 'data': data, **kw})))
    with app.app_context():
        yield sent


# --------------------------------------------------------------------------- #
# version range evaluation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('version,range_str,expected', [
    ('1.7.59', '< 1.7.68', True),
    ('1.7.68', '< 1.7.68', False),
    ('1.7.67', '< 1.7.68', True),
    ('1.5.4', '>= 1.5.0, < 1.6.0', True),
    ('1.6.0', '>= 1.5.0, < 1.6.0', False),
    ('1.4.9', '>= 1.5.0, < 1.6.0', False),
    ('1.7.59', '', False),
    ('1.7.59', None, False),
    ('1.7.59', 'banana', False),
])
def test_version_in_range(version, range_str, expected):
    assert sfs.version_in_range(version, range_str) is expected


# --------------------------------------------------------------------------- #
# affected-version alerting
# --------------------------------------------------------------------------- #

def test_alerts_when_current_version_affected(feed_env):
    result = sfs.check_security_feed(current_version='1.7.59')
    assert result['alerts'] == 1
    assert len(feed_env) == 1
    note = feed_env[0]
    assert note['event'] == 'security.alert'
    assert note['to'] == 'admins'
    assert 'GHSA-test-0001' in note['data']['alert_type']
    assert '1.7.59' in note['data']['message']


def test_no_alert_when_version_not_affected(feed_env):
    result = sfs.check_security_feed(current_version='1.7.77')
    assert result['alerts'] == 0
    assert feed_env == []


def test_alert_fires_once_per_advisory(feed_env):
    sfs.check_security_feed(current_version='1.7.59')
    result = sfs.check_security_feed(current_version='1.7.59')
    assert result['alerts'] == 0
    assert len(feed_env) == 1


def test_multi_clause_range_alerts(feed_env):
    result = sfs.check_security_feed(current_version='1.5.4')
    assert result['alerts'] == 2  # both advisories match 1.5.4


def test_disabled_skips_everything(app, feed_env):
    SystemSettings.set(sfs.ENABLED_KEY, False, 'boolean')
    _db.session.commit()
    result = sfs.check_security_feed(current_version='1.7.59')
    assert result == {'skipped': 'disabled'}
    assert feed_env == []


# --------------------------------------------------------------------------- #
# post-fix reminders after an upgrade crosses the fix boundary
# --------------------------------------------------------------------------- #

def test_post_fix_reminder_after_upgrade_crossing(feed_env):
    # Panel was last seen on an affected version...
    sfs.check_security_feed(current_version='1.7.59')
    assert len(feed_env) == 1
    # ...and comes up fixed: the advisory carries a post_fix_action.
    result = sfs.check_security_feed(current_version='1.7.77')
    assert result['alerts'] == 1
    note = feed_env[-1]
    assert 'Post-update action' in note['data']['alert_type']
    assert 'Rotate JWT_SECRET_KEY' in note['data']['message']


def test_no_post_fix_reminder_without_action(feed_env):
    # 1.5.4 -> 1.6.0 crosses GHSA-test-0002, which declares no post-fix action.
    sfs.check_security_feed(current_version='1.5.4')
    sent_before = len(feed_env)
    sfs.check_security_feed(current_version='1.6.0')
    assert len(feed_env) == sent_before


def test_post_fix_reminder_fires_once(feed_env):
    sfs.check_security_feed(current_version='1.7.59')
    sfs.check_security_feed(current_version='1.7.77')
    result = sfs.check_security_feed(current_version='1.7.77')
    assert result['alerts'] == 0


def test_first_seen_version_records_without_reminder(feed_env):
    """A fresh panel (no last_version) never gets post-fix reminders."""
    result = sfs.check_security_feed(current_version='1.7.77')
    assert result['alerts'] == 0
    assert SystemSettings.get(sfs.LAST_VERSION_KEY) == '1.7.77'
